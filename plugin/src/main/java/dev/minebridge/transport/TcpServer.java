package dev.minebridge.transport;

import dev.minebridge.protocol.CodecException;
import dev.minebridge.protocol.FrameDecoder;
import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;

import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.StandardSocketOptions;
import java.nio.ByteBuffer;
import java.nio.channels.SelectionKey;
import java.nio.channels.Selector;
import java.nio.channels.ServerSocketChannel;
import java.nio.channels.SocketChannel;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * One bounded nonblocking selector reactor. No Paper API, authentication, request execution,
 * per-client worker or executor queue lives here. Closing never joins the reactor thread.
 */
public final class TcpServer implements AutoCloseable {
    private static final int READ_BYTES_PER_TURN = 8192;
    private final String address;
    private final int port;
    private final TransportLimits limits;
    private final int sendBufferBytes;
    private final Session.RequestObserver requestObserver;
    private final AtomicBoolean stopping = new AtomicBoolean();
    private final CompletableFuture<InetSocketAddress> ready = new CompletableFuture<>();
    private final CompletableFuture<Void> terminated = new CompletableFuture<>();
    private volatile Selector selector;
    private volatile List<Session> snapshot = List.of();
    private boolean started;

    public TcpServer(String address, int port, TransportLimits limits) {
        this(address, port, limits, 0, Session.RequestObserver.NONE);
    }

    public TcpServer(String address, int port, TransportLimits limits, Session.RequestObserver observer) {
        this(address, port, limits, 0, observer);
    }

    /** Package-private SO_SNDBUF seam to make a non-reading peer test reproducible. */
    TcpServer(String address, int port, TransportLimits limits, int sendBufferBytes) {
        this(address, port, limits, sendBufferBytes, Session.RequestObserver.NONE);
    }

    private TcpServer(String address, int port, TransportLimits limits, int sendBufferBytes,
                      Session.RequestObserver observer) {
        this.address = Objects.requireNonNull(address);
        if (address.isBlank() || port < 0 || port > 65535 || sendBufferBytes < 0) {
            throw new IllegalArgumentException("Invalid TCP listener configuration");
        }
        this.port = port;
        this.limits = Objects.requireNonNull(limits);
        this.sendBufferBytes = sendBufferBytes;
        this.requestObserver = Objects.requireNonNull(observer);
    }

    /** Starts once; literal address parsing and bind happen outside the caller's thread. */
    public synchronized void start() {
        if (started) throw new IllegalStateException("TCP server already started");
        started = true;
        if (stopping.get()) {
            ready.completeExceptionally(new IOException("TCP server is closed"));
            terminated.complete(null);
            return;
        }
        Thread reactor = new Thread(this::run, "minebridge-tcp-" + Integer.toUnsignedString(hashCode()));
        reactor.start();
    }

    public CompletableFuture<InetSocketAddress> ready() { return ready; }
    public List<Session> sessions() { return snapshot; }

    @Override public void close() {
        stopping.set(true);
        wakeup();
        synchronized (this) {
            if (!started) {
                ready.completeExceptionally(new IOException("TCP server is closed"));
                terminated.complete(null);
            }
        }
    }

    /** Test/off-main-thread helper only. Plugin shutdown must call close without waiting. */
    public boolean awaitTermination(Duration timeout) throws InterruptedException {
        Objects.requireNonNull(timeout);
        if (timeout.isNegative()) throw new IllegalArgumentException("Negative termination timeout");
        try {
            terminated.get(timeout.toNanos(), TimeUnit.NANOSECONDS);
            return true;
        } catch (TimeoutException failure) {
            return false;
        } catch (ExecutionException impossible) {
            throw new IllegalStateException("Unexpected termination failure");
        }
    }

    private void wakeup() {
        Selector current = selector;
        if (current != null) current.wakeup();
    }

    private void run() {
        Map<SocketChannel, Connection> connections = new LinkedHashMap<>();
        try (Selector openedSelector = Selector.open(); ServerSocketChannel listener = ServerSocketChannel.open()) {
            selector = openedSelector;
            if (stopping.get()) return;
            listener.configureBlocking(false);
            listener.setOption(StandardSocketOptions.SO_REUSEADDR, true);
            // Binding is local configuration: literal parsing performs no uncancellable DNS IO.
            listener.bind(new InetSocketAddress(InetAddress.ofLiteral(address), port));
            listener.register(openedSelector, SelectionKey.OP_ACCEPT);
            ready.complete((InetSocketAddress) listener.getLocalAddress());
            while (!stopping.get()) {
                maintain(connections, System.nanoTime());
                openedSelector.select(25);
                Iterator<SelectionKey> selected = openedSelector.selectedKeys().iterator();
                while (selected.hasNext() && !stopping.get()) {
                    SelectionKey key = selected.next();
                    selected.remove();
                    if (!key.isValid()) continue;
                    if (key.channel() == listener) {
                        accept(listener, openedSelector, connections);
                    } else {
                        Connection connection = (Connection) key.attachment();
                        try {
                            if (expired(connection, System.nanoTime())) {
                                connection.session.close();
                                continue;
                            }
                            if (key.isReadable()) read(connection);
                            if (key.isValid() && key.isWritable() && !connection.session.reactorCloseImmediately()) {
                                write(connection);
                            }
                        } catch (IOException failure) {
                            connection.session.close();
                        }
                    }
                }
            }
        } catch (IOException | RuntimeException failure) {
            // Deliberately do not retain the cause, address, payload or credentials.
            ready.completeExceptionally(new IOException("TCP listener could not start or continue"));
        } finally {
            stopping.set(true);
            for (Connection connection : connections.values()) dispose(connection);
            snapshot = List.of();
            selector = null;
            if (!ready.isDone()) ready.completeExceptionally(new IOException("TCP server is closed"));
            terminated.complete(null);
        }
    }

    private void accept(ServerSocketChannel listener, Selector openedSelector,
                        Map<SocketChannel, Connection> connections) throws IOException {
        // One accept per turn prevents a connection flood from monopolizing the reactor.
        SocketChannel channel = listener.accept();
        if (channel == null) return;
        long acceptedAt = System.nanoTime();
        if (stopping.get() || connections.size() >= limits.maxSessions()) {
            channel.close();
            return;
        }
        boolean registered = false;
        try {
            channel.configureBlocking(false);
            channel.setOption(StandardSocketOptions.TCP_NODELAY, true);
            if (sendBufferBytes != 0) channel.setOption(StandardSocketOptions.SO_SNDBUF, sendBufferBytes);
            Session session = new Session(limits.maxQueuedRequests(), limits.maxOutputFrames(), this::wakeup,
                    acceptedAt, limits.handshakeTimeout(), System::nanoTime, requestObserver);
            Connection connection = new Connection(channel, session);
            connection.key = channel.register(openedSelector, SelectionKey.OP_READ, connection);
            connections.put(channel, connection);
            publish(connections);
            registered = true;
        } catch (IOException failure) {
            // A client disappearing during registration must not stop the listener.
        } finally {
            if (!registered) channel.close();
        }
    }

    private void maintain(Map<SocketChannel, Connection> connections, long now) {
        boolean changed = false;
        Iterator<Connection> iterator = connections.values().iterator();
        while (iterator.hasNext()) {
            Connection connection = iterator.next();
            Session session = connection.session;
            ByteBuffer head = session.reactorOutputHead();
            if (head != connection.writingHead) {
                connection.writingHead = head;
                connection.writeStarted = head == null ? 0 : now;
            }
            if (expired(connection, now) || session.reactorCloseImmediately()
                    || (session.reactorFlushThenClose() && head == null)) {
                dispose(connection);
                iterator.remove();
                changed = true;
                continue;
            }
            int interest = session.isOpen() ? SelectionKey.OP_READ : 0;
            if (head != null && !session.reactorWriterPaused()) interest |= SelectionKey.OP_WRITE;
            connection.key.interestOps(interest);
        }
        if (changed) publish(connections);
    }

    private static boolean elapsed(long now, long start, Duration duration) {
        return now - start >= duration.toNanos();
    }

    private boolean expired(Connection connection, long now) {
        Session session = connection.session;
        return session.handshakeExpired(now)
                || (connection.frameStarted != 0
                    && elapsed(now, connection.frameStarted, limits.frameAssemblyTimeout()))
                || (connection.writingHead != null
                    && elapsed(now, connection.writeStarted, limits.writeTimeout()));
    }

    private void read(Connection connection) throws IOException {
        Session session = connection.session;
        if (!session.isOpen()) return;
        ByteBuffer buffer = connection.readBuffer;
        buffer.clear();
        int count = connection.channel.read(buffer);
        if (count < 0) {
            // A partial frame never enters the request queue; EOF cancels pending work.
            try { connection.decoder.finish(); } catch (CodecException ignored) { }
            session.close();
            return;
        }
        if (count == 0) return;
        byte[] chunk = new byte[count];
        buffer.flip();
        buffer.get(chunk);
        long now = System.nanoTime();
        try {
            List<byte[]> frames = connection.decoder.feed(chunk);
            session.reactorFrameProgress(connection.decoder.pendingBytes(), frames.size());
            if (connection.decoder.pendingBytes() == 0) connection.frameStarted = 0;
            else if (connection.frameStarted == 0 || !frames.isEmpty()) connection.frameStarted = now;
            for (byte[] frame : frames) {
                if (!session.isOpen()) break;
                processFrame(connection, frame);
            }
        } catch (CodecException failure) {
            reject(connection, failure);
        }
    }

    private void processFrame(Connection connection, byte[] frame) {
        try {
            Request request = JsonRpcCodec.decodeEnvelope(frame);
            if (request.notification()) {
                connection.session.close();
                return;
            }
            if (!advanceId(connection, request.id())) return;
            if (!connection.session.reactorOfferRequest(request) && connection.session.isOpen()) {
                connection.session.sendFrame(JsonRpcCodec.errorFrame(request.id(), "LIMIT_EXCEEDED", "not-applied"));
            }
        } catch (CodecException failure) {
            reject(connection, failure);
        }
    }

    private boolean advanceId(Connection connection, long id) {
        if (id <= connection.lastId) {
            connection.session.sendFrame(JsonRpcCodec.errorFrame(id, "INVALID_REQUEST", "not-applied"));
            connection.session.closeAfterFlush();
            return false;
        }
        connection.lastId = id;
        return true;
    }

    private void reject(Connection connection, CodecException failure) {
        if (failure.requestId() != null && !advanceId(connection, failure.requestId())) return;
        if (failure.reply()) {
            connection.session.sendFrame(JsonRpcCodec.errorFrame(failure.requestId(), failure.code(), "not-applied"));
            if (failure.close()) connection.session.closeAfterFlush();
        } else connection.session.close();
    }

    private void write(Connection connection) throws IOException {
        if (connection.session.reactorWriterPaused()) return;
        ByteBuffer head = connection.session.reactorOutputHead();
        if (head == null) return;
        if (head != connection.writingHead) {
            connection.writingHead = head;
            connection.writeStarted = System.nanoTime();
        }
        connection.channel.write(head); // At most one nonblocking frame write per selected turn.
        if (!head.hasRemaining()) {
            connection.session.reactorRemoveOutputHead(head);
            connection.writingHead = null;
            connection.writeStarted = 0;
        }
    }

    private void publish(Map<SocketChannel, Connection> connections) {
        List<Session> sessions = new ArrayList<>(connections.size());
        for (Connection connection : connections.values()) sessions.add(connection.session);
        snapshot = List.copyOf(sessions);
    }

    private static void dispose(Connection connection) {
        connection.session.reactorClosed();
        connection.key.cancel();
        try { connection.channel.close(); } catch (IOException ignored) { }
    }

    private static final class Connection {
        final SocketChannel channel;
        final Session session;
        final FrameDecoder decoder = new FrameDecoder();
        final ByteBuffer readBuffer = ByteBuffer.allocate(READ_BYTES_PER_TURN);
        SelectionKey key;
        long lastId;
        long frameStarted;
        long writeStarted;
        ByteBuffer writingHead;

        Connection(SocketChannel channel, Session session) {
            this.channel = channel;
            this.session = session;
        }
    }
}
