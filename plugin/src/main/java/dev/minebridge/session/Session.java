package dev.minebridge.session;

import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;

import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.ArrayDeque;
import java.util.Objects;
import java.util.Map;
import java.util.UUID;
import java.util.function.LongSupplier;

/**
 * Connection-local bounded queues. Methods never perform socket IO or wait for network progress.
 * The reactor owns channel IO; an application consumer later polls requests and queues responses.
 */
public final class Session implements AutoCloseable {
    /** Bounded diagnostic hooks only: implementations must not perform IO or invoke live game APIs. */
    public interface RequestObserver {
        RequestObserver NONE = new RequestObserver() {
            @Override public void queued(Session session, Request request) {}
            @Override public void cancelled(Session session, Request request) {}
        };
        void queued(Session session, Request request);
        void cancelled(Session session, Request request);
    }
    private final UUID id = UUID.randomUUID();
    private final int maxRequests;
    private final int maxOutput;
    private final Runnable wakeup;
    private final long acceptedAt;
    private final long handshakeTimeoutNanos;
    private final LongSupplier clock;
    private final RequestObserver requestObserver;
    private final ArrayDeque<Request> requests = new ArrayDeque<>();
    private final ArrayDeque<ByteBuffer> output = new ArrayDeque<>();
    private static final int MAX_LIVE_EVENTS = 512;
    private static final int MAX_EVENT_CONTROLS = 32;
    private record EventFrame(UUID subscriptionId, ByteBuffer bytes) {}
    private record Overflow(String source, long lostCount) {}
    private final ArrayDeque<EventFrame> eventOutput = new ArrayDeque<>();
    private final java.util.LinkedHashMap<UUID, Overflow> eventOverflows = new java.util.LinkedHashMap<>();
    // A selected frame stays pinned even when higher-priority output arrives mid-write.
    private ByteBuffer writingHead;
    private boolean closed;
    private boolean flushThenClose;
    private boolean ready;
    private Long activeOperation;
    private WorldContext worldContext;
    private SessionActivityLog activityLog;
    private boolean testWriterPaused;
    private int requestHighWater;
    private int outputHighWater;
    private int partialFrameBytes;
    private long receivedFrames;

    /** Payload-free retained counters; closed sessions keep their bounded high-water evidence. */
    public record Diagnostics(boolean writerPaused, int queuedRequests, int outputFrames,
                              int requestHighWater, int outputHighWater,
                              long receivedFrames, int partialFrameBytes) {}

    /** Internal construction seam for TcpServer; it does not start or authenticate a session. */
    public Session(int maxRequests, int maxOutput, Runnable wakeup) {
        this(maxRequests, maxOutput, wakeup, 0, null, System::nanoTime);
    }

    /** Production constructor pins hello completion to the same accept-time deadline as the reactor. */
    public Session(int maxRequests, int maxOutput, Runnable wakeup, long acceptedAt,
                   Duration handshakeTimeout, LongSupplier clock) {
        this(maxRequests, maxOutput, wakeup, acceptedAt, handshakeTimeout, clock, RequestObserver.NONE);
    }

    public Session(int maxRequests, int maxOutput, Runnable wakeup, long acceptedAt,
                   Duration handshakeTimeout, LongSupplier clock, RequestObserver requestObserver) {
        if (maxRequests < 1 || maxOutput < 1 || maxRequests > 1024 || maxOutput > 1024) {
            throw new IllegalArgumentException("Invalid session capacity");
        }
        this.maxRequests = maxRequests;
        this.maxOutput = maxOutput;
        this.wakeup = Objects.requireNonNull(wakeup);
        this.acceptedAt = acceptedAt;
        if (handshakeTimeout != null && (handshakeTimeout.isNegative() || handshakeTimeout.isZero()
                || handshakeTimeout.compareTo(Duration.ofDays(1)) > 0)) {
            throw new IllegalArgumentException("Invalid handshake deadline");
        }
        this.handshakeTimeoutNanos = handshakeTimeout == null ? 0 : handshakeTimeout.toNanos();
        this.clock = Objects.requireNonNull(clock);
        this.requestObserver = Objects.requireNonNull(requestObserver);
    }

    public UUID id() { return id; }

    public synchronized Request pollRequest() {
        return closed || flushThenClose ? null : requests.pollFirst();
    }

    /** The test gate inspects the existing head; it never moves a request to another queue. */
    public synchronized Request peekRequest() {
        return closed || flushThenClose ? null : requests.peekFirst();
    }

    public synchronized int queuedRequests() { return requests.size(); }
    public synchronized int outputFrames() { return output.size(); }
    public synchronized int eventOutputFrames() { return eventOutput.size(); }
    public synchronized WorldContext worldContext() { return worldContext; }
    public synchronized Diagnostics diagnostics() {
        return new Diagnostics(testWriterPaused, requests.size(), output.size(), requestHighWater,
                outputHighWater, receivedFrames, partialFrameBytes);
    }

    /** Local TestControl only; the service exposing this seam is absent by default. No socket IO. */
    public void testPauseWriter(boolean paused) {
        synchronized (this) { testWriterPaused = paused; }
        wakeup.run();
    }

    public synchronized boolean reactorWriterPaused() { return testWriterPaused; }

    /** Reactor-owned framing facts, never payloads. Counters saturate instead of wrapping. */
    public synchronized void reactorFrameProgress(int pendingBytes, int completeFrames) {
        if (pendingBytes < 0 || pendingBytes > JsonRpcCodec.MAX_FRAME_BYTES || completeFrames < 0)
            throw new IllegalArgumentException("Invalid frame progress");
        partialFrameBytes = pendingBytes;
        receivedFrames = receivedFrames > Long.MAX_VALUE - completeFrames
                ? Long.MAX_VALUE : receivedFrames + completeFrames;
    }

    public synchronized boolean hasPendingOperation(long requestId) {
        return (activeOperation != null && activeOperation == requestId)
                || requests.stream().anyMatch(request -> request.id() != null && request.id() == requestId);
    }

    public synchronized boolean hasActiveOperation() { return activeOperation != null; }
    public synchronized Long activeRequestId() { return activeOperation; }

    public synchronized void enableActivityLog(SessionActivityLog log) { activityLog = Objects.requireNonNull(log); }
    public void logEvent(UUID subscriptionId, String phase, long sequence) {
        SessionActivityLog log;
        synchronized (this) { log = activityLog; }
        if (log != null) try { log.event(this, subscriptionId, phase, sequence); } catch (RuntimeException ignored) { }
    }
    public void logRequest(Request request) {
        SessionActivityLog log;
        synchronized (this) { log = activityLog; }
        if (log != null) try { log.received(this, request); } catch (RuntimeException ignored) { }
    }
    public void logResult(Request request, Map<String, Object> result, boolean ackQueued) {
        SessionActivityLog log;
        synchronized (this) { log = activityLog; }
        if (log != null) try { log.completed(this, request, result, ackQueued); } catch (RuntimeException ignored) { }
    }
    public boolean sendResult(Request request, Map<String, Object> result) {
        return sendResult(request, result, () -> {});
    }
    public boolean sendResult(Request request, Map<String, Object> result, Runnable onPublished) {
        byte[] frame = JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", request.id(), "result", result));
        boolean queued = sendFrame(frame, onPublished);
        logResult(request, result, queued);
        return queued;
    }
    public void sendError(Request request, String code, String outcome) {
        sendError(request, code, outcome, Map.of());
    }
    public void sendError(Request request, String code, String outcome, Map<String, Object> details) {
        sendFrame(JsonRpcCodec.errorFrame(request.id(), code, outcome, details));
        SessionActivityLog log;
        synchronized (this) { log = activityLog; }
        if (log != null) try { log.failed(this, request, code, outcome); } catch (RuntimeException ignored) { }
    }

    /** Copies a single encoded LF frame. Overflow closes the connection without blocking. */
    public boolean sendFrame(byte[] frame) {
        return sendFrame(frame, () -> { });
    }

    /** Internal publication seam: the hook is bounded, never performs IO and cannot veto delivery. */
    public boolean sendFrame(byte[] frame, Runnable onPublished) {
        validateFrame(frame);
        Objects.requireNonNull(onPublished);
        boolean accepted;
        synchronized (this) {
            if (closed || flushThenClose) return false;
            accepted = output.size() < maxOutput;
            if (accepted) {
                output.addLast(ByteBuffer.wrap(frame.clone()));
                outputHighWater = Math.max(outputHighWater, output.size());
                // The writer cannot acquire the output head until this monitor is released.
                try { onPublished.run(); }
                catch (RuntimeException ignored) { /* Diagnostics cannot turn a published ACK into an error. */ }
            }
            else closeQueues();
        }
        wakeup.run();
        return accepted;
    }

    /** Live output has its own bound; overflowing it never consumes RPC capacity. */
    public boolean offerEvent(byte[] frame, UUID subscriptionId) {
        validateFrame(frame);
        Objects.requireNonNull(subscriptionId);
        synchronized (this) {
            if (!isReady() || eventOutput.size() >= MAX_LIVE_EVENTS) return false;
            eventOutput.addLast(new EventFrame(subscriptionId, ByteBuffer.wrap(frame.clone())));
        }
        wakeup.run();
        return true;
    }

    /** One coalesced control per active subscription, independent of the full live queue. */
    public void offerEventOverflow(UUID subscriptionId, String source, long lostCount) {
        Objects.requireNonNull(subscriptionId);
        if (!("server".equals(source) || "capture".equals(source)) || lostCount < 0)
            throw new IllegalArgumentException("Invalid event overflow");
        synchronized (this) {
            if (!isReady()) return;
            Overflow old = eventOverflows.get(subscriptionId);
            if (old == null && eventOverflows.size() >= MAX_EVENT_CONTROLS)
                throw new IllegalStateException("Too many event controls");
            long count = old == null ? lostCount : Math.min(JsonRpcCodec.MAX_REQUEST_ID,
                    old.lostCount() + Math.min(lostCount, JsonRpcCodec.MAX_REQUEST_ID));
            eventOverflows.put(subscriptionId, new Overflow(source, count));
        }
        wakeup.run();
    }

    /** Unsubscribe fence: an already selected frame finishes; no later frame survives the ACK. */
    public synchronized void purgeEvents(UUID subscriptionId) {
        eventOutput.removeIf(frame -> frame.subscriptionId().equals(subscriptionId)
                && frame.bytes() != writingHead);
        eventOverflows.remove(subscriptionId);
    }

    /** Linearization point for close vs a setter attempt; no game operation runs under this lock. */
    public synchronized boolean tryBeginOperation(long requestId) {
        if (closed || flushThenClose || !ready || activeOperation != null) return false;
        activeOperation = requestId;
        return true;
    }

    public synchronized void endOperation(long requestId) {
        if (activeOperation != null && activeOperation == requestId) activeOperation = null;
    }

    @Override public void close() {
        synchronized (this) { closeQueues(); }
        wakeup.run();
    }

    /** Stops input immediately and sends only frames already queued, under the write deadline. */
    public void closeAfterFlush() {
        synchronized (this) {
            if (closed) return;
            flushThenClose = true;
            cancelRequests();
            eventOutput.removeIf(frame -> frame.bytes() != writingHead);
            eventOverflows.clear();
        }
        wakeup.run();
    }

    /** Trusted test-consumer seam. Production authenticates through completeHandshake instead. */
    public void markReady() {
        synchronized (this) {
            if (closed || flushThenClose) return;
            if (handshakeExpired(clock.getAsLong())) closeQueues();
            else ready = true;
        }
        wakeup.run();
    }

    /** Queue the hello ACK and change state as one bounded operation, without waiting for socket IO. */
    public boolean completeHandshake(byte[] frame) {
        return completeHandshake(frame, null);
    }

    public boolean completeHandshake(byte[] frame, WorldContext world) {
        validateFrame(frame);
        boolean accepted;
        synchronized (this) {
            if (closed || flushThenClose || ready) return false;
            accepted = !handshakeExpired(clock.getAsLong()) && output.size() < maxOutput;
            if (accepted) {
                output.addLast(ByteBuffer.wrap(frame.clone()));
                outputHighWater = Math.max(outputHighWater, output.size());
                worldContext = world;
                ready = true;
            } else closeQueues();
        }
        wakeup.run();
        return accepted;
    }

    public synchronized boolean handshakeExpired(long now) {
        return !ready && !flushThenClose && handshakeTimeoutNanos != 0
                && now - acceptedAt >= handshakeTimeoutNanos;
    }

    public synchronized boolean isReady() { return ready && !closed && !flushThenClose; }
    public synchronized boolean isOpen() { return !closed && !flushThenClose; }

    // Reactor-only methods are public because the reactor and session have separate packages.
    public synchronized boolean reactorOfferRequest(Request request) {
        if (closed || flushThenClose || requests.size() == maxRequests) return false;
        requests.addLast(Objects.requireNonNull(request));
        requestHighWater = Math.max(requestHighWater, requests.size());
        try { requestObserver.queued(this, request); }
        catch (RuntimeException ignored) { /* Diagnostics cannot reject a queued request. */ }
        return true;
    }

    public synchronized ByteBuffer reactorOutputHead() {
        if (writingHead != null) return writingHead;
        if (!output.isEmpty()) writingHead = output.peekFirst();
        else if (!eventOverflows.isEmpty()) {
            // At most 32 entries; even an overflow control always fits a protocol frame.
            var first = eventOverflows.entrySet().iterator().next();
            String source = first.getValue().source();
            var ids = new java.util.ArrayList<String>();
            long lost = 0;
            var iterator = eventOverflows.entrySet().iterator();
            while (iterator.hasNext()) {
                var entry = iterator.next();
                if (!entry.getValue().source().equals(source)) continue;
                ids.add(entry.getKey().toString());
                lost = Math.min(JsonRpcCodec.MAX_REQUEST_ID, lost + entry.getValue().lostCount());
                iterator.remove();
            }
            writingHead = ByteBuffer.wrap(JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0",
                    "method", "events.overflow", "params", Map.of("subscriptionIds", ids,
                    "source", source, "lostCount", lost))));
        } else if (!eventOutput.isEmpty()) {
            EventFrame frame = eventOutput.peekFirst();
            writingHead = frame.bytes();
        }
        return writingHead;
    }

    public synchronized void reactorRemoveOutputHead(ByteBuffer head) {
        if (output.peekFirst() == head) output.removeFirst();
        if (!eventOutput.isEmpty() && eventOutput.peekFirst().bytes() == head) eventOutput.removeFirst();
        if (writingHead == head) writingHead = null;
    }

    public synchronized boolean reactorCloseImmediately() { return closed; }
    public synchronized boolean reactorFlushThenClose() { return flushThenClose; }

    public synchronized void reactorClosed() { closeQueues(); }

    private void closeQueues() {
        if (!closed && activityLog != null) try { activityLog.disconnected(this); } catch (RuntimeException ignored) { }
        closed = true;
        ready = false;
        cancelRequests();
        output.clear();
        eventOutput.clear();
        eventOverflows.clear();
        writingHead = null;
    }

    private void cancelRequests() {
        Request request;
        while ((request = requests.pollFirst()) != null) {
            try { requestObserver.cancelled(this, request); }
            catch (RuntimeException ignored) { /* Diagnostic failure cannot prevent close. */ }
        }
    }

    private static void validateFrame(byte[] frame) {
        Objects.requireNonNull(frame, "frame");
        if (frame.length < 2 || frame.length > JsonRpcCodec.MAX_FRAME_BYTES + 1
                || frame[frame.length - 1] != '\n') {
            throw new IllegalArgumentException("Expected one bounded LF frame");
        }
        for (int i = 0; i < frame.length - 1; i++) {
            if (frame[i] == '\n') throw new IllegalArgumentException("Expected one bounded LF frame");
        }
    }

    @Override public String toString() { return "Session[id=" + id + "]"; }
}
