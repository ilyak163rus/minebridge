package dev.minebridge.transport;

import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.protocol.Response;
import dev.minebridge.session.Session;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;

import static org.junit.jupiter.api.Assertions.*;

@Timeout(20)
class TcpServerTest {
    private static final Duration WAIT = Duration.ofSeconds(3);

    @Test void pausedWriterRetainsBoundedOutputWhileReactorReadsAndOtherConnectionProgresses() throws Exception {
        try (Running running = start(ordinary()); Socket a = running.connect()) {
            Session sa = session(running.server, 1);
            sa.markReady();
            sa.testPauseWriter(true);
            a.getOutputStream().write(request(1));
            reply(sa, take(sa));
            await(() -> sa.diagnostics().outputFrames() == 1);
            try (Socket b = running.connect()) {
                await(() -> running.server.sessions().size() == 2);
                Session sb = running.server.sessions().stream().filter(s -> s != sa).findFirst().orElseThrow();
                sb.markReady();
                b.getOutputStream().write(request(1));
                reply(sb, take(sb));
                assertEquals("METHOD_NOT_FOUND", error(b, 1).error().code());
                assertEquals(1, sa.diagnostics().outputFrames());
                assertEquals(1, sa.diagnostics().outputHighWater());
                sa.testPauseWriter(false);
                assertEquals("METHOD_NOT_FOUND", error(a, 1).error().code());
                await(() -> sa.diagnostics().outputFrames() == 0);
            }
        }
    }

    @Test void framingDiagnosticsDistinguishObservedIncompleteFrameFromQueuedRequest() throws Exception {
        try (Running running = start(ordinary()); Socket socket = running.connect()) {
            Session session = session(running.server, 1);
            byte[] frame = request(1);
            socket.getOutputStream().write(Arrays.copyOf(frame, frame.length - 1));
            await(() -> session.diagnostics().partialFrameBytes() == frame.length - 1);
            assertEquals(0, session.diagnostics().receivedFrames());
            assertEquals(0, session.diagnostics().queuedRequests());
            socket.getOutputStream().write('\n');
            assertEquals(1L, take(session).id());
            assertEquals(1, session.diagnostics().receivedFrames());
            assertEquals(0, session.diagnostics().partialFrameBytes());
        }
    }

    @Test void independentConnectionsPermitSameIdsAndSplitOrCoalescedFrames() throws Exception {
        try (Running running = start(ordinary())) {
            try (Socket a = running.connect()) {
                Session sa = session(running.server, 1);
                try (Socket b = running.connect()) {
                    await(() -> running.server.sessions().size() == 2);
                    Session sb = running.server.sessions().stream().filter(s -> s != sa).findFirst().orElseThrow();
                    assertNotEquals(sa.id(), sb.id());
                    sa.markReady(); sb.markReady();
                    byte[] first = request(1);
                    a.getOutputStream().write(Arrays.copyOf(first, 7));
                    assertNull(sa.pollRequest());
                    b.getOutputStream().write(request(1));
                    reply(sb, take(sb));
                    assertEquals(1L, error(b, 1).id());
                    assertTrue(sa.isOpen());
                    a.getOutputStream().write(Arrays.copyOfRange(first, 7, first.length));
                    a.getOutputStream().write(request(2));
                    reply(sa, take(sa)); reply(sa, take(sa));
                    assertEquals(1L, error(a, 1).id());
                    assertEquals(2L, error(a, 2).id());
                }
            }
        }
    }

    @Test void malformedConnectionDoesNotDamageOtherConnection() throws Exception {
        try (Running running = start(ordinary()); Socket a = running.connect()) {
            Session sa = session(running.server, 1);
            try (Socket b = running.connect()) {
                await(() -> running.server.sessions().size() == 2);
                Session sb = running.server.sessions().stream().filter(s -> s != sa).findFirst().orElseThrow();
                a.getOutputStream().write("{broken\n".getBytes(StandardCharsets.UTF_8));
                assertEquals("PARSE_ERROR", error(a, null).error().code());
                assertEquals(-1, a.getInputStream().read());
                b.getOutputStream().write(request(1));
                reply(sb, take(sb));
                assertEquals("METHOD_NOT_FOUND", error(b, 1).error().code());
                assertTrue(sb.isOpen());
            }
        }
    }

    @Test void duplicateAndDecreasingIdsCloseAndCancelQueuedRequests() throws Exception {
        for (int repeated : new int[] { 2, 1 }) {
            try (Running running = start(ordinary()); Socket socket = running.connect()) {
                Session session = session(running.server, 1);
                socket.getOutputStream().write(request(2));
                assertEquals(2L, take(session).id());
                socket.getOutputStream().write(request(repeated));
                assertEquals("INVALID_REQUEST", error(socket, repeated).error().code());
                assertEquals(-1, socket.getInputStream().read());
                assertNull(session.pollRequest());
            }
        }
    }

    @Test void domainParametersAreQueuedForFutureRouterAndStillConsumeTheirId() throws Exception {
        try (Running running = start(ordinary()); Socket socket = running.connect()) {
            Session session = session(running.server, 1);
            socket.getOutputStream().write("{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"blocks.set\",\"params\":{}}\n"
                    .getBytes(StandardCharsets.UTF_8));
            Request request = take(session);
            assertEquals(2L, request.id());
            assertEquals("blocks.set", request.method());
            assertTrue(request.params().isEmpty());
            assertTrue(session.isOpen());
            socket.getOutputStream().write(request(2));
            assertEquals("INVALID_REQUEST", error(socket, 2).error().code());
            assertEquals(-1, socket.getInputStream().read());
        }
    }

    @Test void fullInputQueueRejectsRequestAndConsumesItsId() throws Exception {
        TransportLimits limits = new TransportLimits(8, 2, 8, Duration.ofSeconds(5),
                Duration.ofSeconds(5), Duration.ofSeconds(5));
        try (Running running = start(limits); Socket socket = running.connect()) {
            Session session = session(running.server, 1);
            socket.getOutputStream().write(join(request(1), request(2), request(3)));
            Response exceeded = error(socket, 3);
            assertEquals("LIMIT_EXCEEDED", exceeded.error().code());
            assertEquals("not-applied", exceeded.error().outcome());
            assertEquals(1L, take(session).id());
            assertEquals(2L, take(session).id());
            assertNull(session.pollRequest());
            socket.getOutputStream().write(request(3));
            assertEquals("INVALID_REQUEST", error(socket, 3).error().code());
            assertEquals(-1, socket.getInputStream().read());
        }
    }

    @Test void eofAndNotificationCancelWithoutExecutingOrReplying() throws Exception {
        try (Running running = start(ordinary())) {
            try (Socket socket = running.connect()) {
                Session session = session(running.server, 1);
                socket.getOutputStream().write("{\"jsonrpc\":\"2.0\",\"method\":\"future\",\"params\":{}}\n"
                        .getBytes(StandardCharsets.UTF_8));
                assertEquals(-1, socket.getInputStream().read());
                assertNull(session.pollRequest());
            }
            await(() -> running.server.sessions().isEmpty());
            try (Socket socket = running.connect()) {
                Session session = session(running.server, 1);
                socket.getOutputStream().write("{\"jsonrpc\":\"2.0\",\"id\":1".getBytes(StandardCharsets.UTF_8));
                socket.shutdownOutput();
                assertEquals(-1, socket.getInputStream().read());
                assertNull(session.pollRequest());
                await(() -> !session.isOpen());
            }
        }
    }

    @Test void invalidUtf8AndOversizeFramesCloseWithoutReply() throws Exception {
        for (byte[] bad : new byte[][] { { (byte) 0xff, '\n' },
                new byte[JsonRpcCodec.MAX_FRAME_BYTES + 1] }) {
            try (Running running = start(ordinary()); Socket socket = running.connect()) {
                Session session = session(running.server, 1);
                socket.getOutputStream().write(bad);
                assertEquals(-1, socket.getInputStream().read());
                assertNull(session.pollRequest());
            }
        }
    }

    @Test void ninthConnectionIsClosedAndFreedSlotCanBeReused() throws Exception {
        try (Running running = start(ordinary())) {
            List<Socket> sockets = new ArrayList<>();
            try {
                for (int i = 1; i <= 8; i++) {
                    sockets.add(running.connect());
                    int size = i;
                    await(() -> running.server.sessions().size() == size);
                }
                try (Socket ninth = running.connect()) { assertEquals(-1, ninth.getInputStream().read()); }
                assertEquals(8, running.server.sessions().size());
                sockets.getFirst().close();
                await(() -> running.server.sessions().size() == 7);
                try (Socket replacement = running.connect()) {
                    await(() -> running.server.sessions().size() == 8);
                    assertTrue(replacement.isConnected());
                }
            } finally { for (Socket socket : sockets) socket.close(); }
        }
    }

    @Test void partialSlowDripHasAbsoluteDeadlineWhileOtherSessionProgresses() throws Exception {
        TransportLimits limits = new TransportLimits(8, 8, 8, Duration.ofSeconds(5),
                Duration.ofMillis(450), Duration.ofSeconds(5));
        try (Running running = start(limits); Socket a = running.connect()) {
            Session sa = session(running.server, 1);
            sa.markReady();
            a.getOutputStream().write('{');
            long started = System.nanoTime();
            try (Socket b = running.connect()) {
                await(() -> running.server.sessions().size() == 2);
                Session sb = running.server.sessions().stream().filter(s -> s != sa).findFirst().orElseThrow();
                sb.markReady();
                b.getOutputStream().write(request(1));
                reply(sb, take(sb));
                assertEquals(1L, error(b, 1).id());
                assertTrue(sa.isOpen(), "B must progress before A's assembly timeout");
                // Further bytes do not restart the absolute deadline.
                Thread.sleep(150);
                a.getOutputStream().write(' ');
                Thread.sleep(150);
                a.getOutputStream().write(' ');
                assertEquals(-1, a.getInputStream().read());
                assertTrue(System.nanoTime() - started < Duration.ofMillis(850).toNanos());
                assertTrue(sb.isOpen());
            }
        }
    }

    @Test void completingOldFrameStartsFreshTailDeadlineAndReadyIdleHasNoAssemblyTimeout() throws Exception {
        TransportLimits limits = new TransportLimits(8, 8, 8, Duration.ofSeconds(5),
                Duration.ofMillis(400), Duration.ofSeconds(5));
        try (Running running = start(limits); Socket socket = running.connect()) {
            Session session = session(running.server, 1);
            session.markReady();
            socket.getOutputStream().write('{');
            Thread.sleep(200);
            byte[] frame = request(1);
            socket.getOutputStream().write(join(Arrays.copyOfRange(frame, 1, frame.length), new byte[] { '{' }));
            assertEquals(1L, take(session).id());
            Thread.sleep(240); // Old frame's deadline has passed, tail's deadline has not.
            assertTrue(session.isOpen());
            socket.getOutputStream().write(Arrays.copyOfRange(request(2), 1, request(2).length));
            assertEquals(2L, take(session).id());
            Thread.sleep(450);
            assertTrue(session.isReady(), "An empty READY connection has no frame assembly deadline");
        }
    }

    @Test void handshakeDeadlineIsAbsoluteAndAppliesWithOrWithoutInput() throws Exception {
        TransportLimits limits = new TransportLimits(8, 8, 8, Duration.ofMillis(300),
                Duration.ofSeconds(5), Duration.ofSeconds(5));
        for (boolean sendRequest : new boolean[] { false, true }) {
            try (Running running = start(limits); Socket socket = running.connect()) {
                Session session = session(running.server, 1);
                if (sendRequest) {
                    socket.getOutputStream().write(request(1));
                    assertEquals(1L, take(session).id());
                }
                assertEquals(-1, socket.getInputStream().read());
                assertFalse(session.isOpen());
            }
        }
    }

    @Test void nonReaderHitsWriteDeadlineWithoutBlockingOtherSession() throws Exception {
        TransportLimits limits = new TransportLimits(8, 8, 8, Duration.ofSeconds(5),
                Duration.ofSeconds(5), Duration.ofMillis(700));
        try (Running running = start(limits, 1024)) {
            try (Socket a = new Socket()) {
                a.setReceiveBufferSize(1024);
                a.connect(running.endpoint);
                a.setSoTimeout(2000);
                Session sa = session(running.server, 1);
                sa.markReady();
                try (Socket b = running.connect()) {
                    await(() -> running.server.sessions().size() == 2);
                    Session sb = running.server.sessions().stream().filter(s -> s != sa).findFirst().orElseThrow();
                    sb.markReady();
                    byte[] huge = JsonRpcCodec.encodeFrame(Map.of("padding", "x".repeat(65_000)));
                    boolean observedBackpressure = false;
                    // SO_SNDBUF is a hint: Windows can absorb more than one full frame.
                    // Refill only after the previous head leaves, never overflowing the queue.
                    for (int frame = 0; frame < 256; frame++) {
                        assertTrue(sa.sendFrame(huge));
                        long probeUntil = System.nanoTime() + Duration.ofMillis(150).toNanos();
                        while (sa.reactorOutputHead() != null && System.nanoTime() < probeUntil && sa.isOpen()) {
                            Thread.sleep(5);
                        }
                        if (sa.reactorOutputHead() != null && sa.isOpen()) {
                            observedBackpressure = true;
                            break;
                        }
                    }
                    assertTrue(observedBackpressure, "The real non-reading socket must leave a pending output head");
                    b.getOutputStream().write(request(1));
                    reply(sb, take(sb));
                    assertEquals(1L, error(b, 1).id());
                    assertTrue(sa.isOpen(), "A is still waiting on its bounded write when B completes");
                    await(() -> !sa.isOpen());
                    assertTrue(sb.isOpen());
                    assertNull(sa.reactorOutputHead());
                }
            }
        }
    }

    @Test void occupiedPortReportsSafeFailureAndCanBeClosed() throws Exception {
        try (ServerSocket occupied = new ServerSocket(0, 1, InetAddress.getLoopbackAddress())) {
            TcpServer server = new TcpServer("127.0.0.1", occupied.getLocalPort(), ordinary());
            server.start();
            ExecutionException failure = assertThrows(ExecutionException.class,
                    () -> server.ready().get(3, TimeUnit.SECONDS));
            assertInstanceOf(IOException.class, failure.getCause());
            assertNull(failure.getCause().getCause());
            assertFalse(failure.getCause().getMessage().contains("127.0.0.1"));
            server.close();
            assertTrue(server.awaitTermination(WAIT));
        }
    }

    @Test void hostnameBindIsRejectedWithoutDnsAndWithoutLeakingItsText() throws Exception {
        TcpServer server = new TcpServer("untrusted-hostname.example", 0, ordinary());
        server.start();
        ExecutionException failure = assertThrows(ExecutionException.class,
                () -> server.ready().get(3, TimeUnit.SECONDS));
        assertEquals("TCP listener could not start or continue", failure.getCause().getMessage());
        assertNull(failure.getCause().getCause());
        assertTrue(server.awaitTermination(WAIT));
        assertTrue(server.sessions().isEmpty());
    }

    @Test void shutdownIsNonblockingCancelsQueuesAndReleasesPortDuringReadAndWrite() throws Exception {
        try (Running running = start(ordinary(), 1024); Socket a = running.connect()) {
            Session session = session(running.server, 1);
            a.getOutputStream().write(request(1));
            assertEquals(1L, take(session).id());
            a.getOutputStream().write('{');
            session.sendFrame(JsonRpcCodec.encodeFrame(Map.of("padding", "x".repeat(65_000))));
            long start = System.nanoTime();
            running.server.close();
            assertTrue(System.nanoTime() - start < Duration.ofMillis(100).toNanos());
            assertTrue(running.server.awaitTermination(WAIT));
            assertFalse(session.isOpen());
            assertNull(session.pollRequest());
            assertNull(session.reactorOutputHead());
            try (ServerSocket rebound = new ServerSocket()) {
                rebound.setReuseAddress(true);
                rebound.bind(running.endpoint);
                assertEquals(running.endpoint.getPort(), rebound.getLocalPort());
            }
        }
    }

    @Test void closeBeforeStartAndRepeatedStartCloseRacesDoNotLeakThreads() throws Exception {
        TcpServer before = new TcpServer("127.0.0.1", 0, ordinary());
        before.close(); before.start();
        assertTrue(before.awaitTermination(WAIT));
        assertTrue(before.ready().isCompletedExceptionally());
        for (int i = 0; i < 20; i++) {
            TcpServer server = new TcpServer("127.0.0.1", 0, ordinary());
            server.start(); server.close();
            assertTrue(server.awaitTermination(WAIT));
            assertTrue(server.sessions().isEmpty());
        }
        await(() -> Thread.getAllStackTraces().keySet().stream()
                .noneMatch(t -> t.isAlive() && t.getName().startsWith("minebridge-tcp-")));
    }

    @Test void limitsRejectUnboundedOrInvalidInternalOverrides() {
        assertThrows(IllegalArgumentException.class, () -> new TransportLimits(0, 8, 8,
                Duration.ofSeconds(1), Duration.ofSeconds(1), Duration.ofSeconds(1)));
        assertThrows(IllegalArgumentException.class, () -> new TransportLimits(8, 1025, 8,
                Duration.ofSeconds(1), Duration.ofSeconds(1), Duration.ofSeconds(1)));
        assertThrows(IllegalArgumentException.class, () -> new TransportLimits(8, 8, 8,
                Duration.ZERO, Duration.ofSeconds(1), Duration.ofSeconds(1)));
        assertThrows(IllegalArgumentException.class, () -> new TcpServer("127.0.0.1", -1, ordinary()));
    }

    private static TransportLimits ordinary() { return TransportLimits.defaults(); }
    private static Running start(TransportLimits limits) throws Exception { return start(limits, 0); }
    private static Running start(TransportLimits limits, int sendBufferBytes) throws Exception {
        TcpServer server = new TcpServer("127.0.0.1", 0, limits, sendBufferBytes);
        server.start();
        return new Running(server, server.ready().get(3, TimeUnit.SECONDS));
    }

    private static Session session(TcpServer server, int count) throws Exception {
        await(() -> server.sessions().size() == count);
        return server.sessions().getLast();
    }

    private static Request take(Session session) throws Exception {
        long end = System.nanoTime() + WAIT.toNanos();
        Request request;
        while ((request = session.pollRequest()) == null) {
            if (System.nanoTime() >= end) fail("No request became available");
            Thread.sleep(5);
        }
        return request;
    }

    private static void reply(Session session, Request request) {
        assertTrue(session.sendFrame(JsonRpcCodec.errorFrame(request.id(), "METHOD_NOT_FOUND", "not-applied")));
    }

    private static Response error(Socket socket, Integer id) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        int value;
        while ((value = socket.getInputStream().read()) != '\n') {
            if (value == -1) fail("Unexpected EOF before response");
            if (bytes.size() >= JsonRpcCodec.MAX_FRAME_BYTES) fail("Oversize response");
            bytes.write(value);
        }
        return JsonRpcCodec.decodeResponse(bytes.toByteArray(), id == null ? null : id.longValue(), "future");
    }

    private static byte[] request(int id) {
        return JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", id, "method", "future", "params", Map.of()));
    }

    private static byte[] join(byte[]... chunks) {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        for (byte[] chunk : chunks) bytes.writeBytes(chunk);
        return bytes.toByteArray();
    }

    private static void await(BooleanSupplier condition) throws Exception {
        long end = System.nanoTime() + WAIT.toNanos();
        while (!condition.getAsBoolean()) {
            if (System.nanoTime() >= end) fail("Condition did not become true within deadline");
            Thread.sleep(5);
        }
    }

    private record Running(TcpServer server, InetSocketAddress endpoint) implements AutoCloseable {
        Socket connect() throws IOException {
            Socket socket = new Socket();
            socket.connect(endpoint, 1000);
            socket.setSoTimeout(2000);
            return socket;
        }
        @Override public void close() throws InterruptedException {
            server.close();
            assertTrue(server.awaitTermination(WAIT), "Reactor did not terminate");
        }
    }
}
