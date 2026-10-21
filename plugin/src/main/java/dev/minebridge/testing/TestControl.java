package dev.minebridge.testing;

import dev.minebridge.execution.OperationTrace;
import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.function.Supplier;

/** Local Java-only control, published only under the opt-in test JVM flag. No network commands. */
public final class TestControl implements AutoCloseable {
    public enum GateState { ARMED, GATED, RELEASED, CANCELLED }
    public record GateStatus(String caseId, UUID sessionId, long requestId, GateState state,
                             boolean sessionOpen, int queuedRequests) {}
    public record SessionStatus(UUID sessionId, boolean ready, boolean open,
                                int queuedRequests, int outputFrames, Session.Diagnostics diagnostics) {}
    private record Key(UUID sessionId, long requestId) {}
    private static final int MAX_TRACKED = 128;

    private static final class Tracked {
        final String caseId;
        final Session session;
        GateState state;
        Tracked(String caseId, Session session, GateState state) {
            this.caseId = caseId;
            this.session = session;
            this.state = state;
        }
    }

    private final Supplier<List<Session>> sessions;
    private final OperationTrace trace;
    private final Runnable requireGameThread;
    private final Map<Key, Tracked> tracked = new HashMap<>();
    private record WriterOwner(String caseId, Session session) {}
    private final Map<UUID, WriterOwner> writers = new HashMap<>();
    private long ticks;
    private boolean closed;

    public TestControl(Supplier<List<Session>> sessions, OperationTrace trace, Runnable requireGameThread) {
        this.sessions = Objects.requireNonNull(sessions);
        this.trace = Objects.requireNonNull(trace);
        this.requireGameThread = Objects.requireNonNull(requireGameThread);
    }

    /** Arm before sending the target RPC. A gate applies only to blocks.set, never hello/state policy. */
    public void arm(String caseId, UUID sessionId, long requestId) {
        register(caseId, sessionId, requestId, GateState.ARMED);
    }

    /** Attach a case ID without pausing the request (for a concurrently progressing session). */
    public void track(String caseId, UUID sessionId, long requestId) {
        register(caseId, sessionId, requestId, GateState.RELEASED);
    }

    private void register(String caseId, UUID sessionId, long requestId, GateState state) {
        checkOpen();
        Key key = key(caseId, sessionId, requestId);
        if (tracked.containsKey(key)) throw new IllegalStateException("Request already tracked");
        if (tracked.size() == MAX_TRACKED) throw new IllegalStateException("Test control capacity reached");
        Session session = sessions.get().stream().filter(value -> value.id().equals(sessionId))
                .findFirst().orElseThrow(() -> new IllegalArgumentException("Session not found"));
        if (!session.isReady()) throw new IllegalStateException("Ready session required");
        trace.correlate(caseId, sessionId, requestId);
        tracked.put(key, new Tracked(caseId, session, state));
    }

    /** Called immediately before dequeue. A held head remains in Session and blocks only its FIFO. */
    public boolean hold(Session session, Request request) {
        checkOpen();
        if (request.notification() || !"blocks.set".equals(request.method())) return false;
        Tracked item = tracked.get(new Key(session.id(), request.id()));
        if (item == null) return false;
        refresh(item);
        if (item.state == GateState.ARMED || item.state == GateState.GATED) {
            item.state = GateState.GATED;
            return true;
        }
        return false;
    }

    public GateStatus release(String caseId, UUID sessionId, long requestId) {
        checkOpen();
        Key key = key(caseId, sessionId, requestId);
        Tracked item = item(key, caseId);
        refresh(item);
        if (item.state != GateState.CANCELLED) item.state = GateState.RELEASED;
        return status(key, item);
    }

    public GateStatus gateStatus(String caseId, UUID sessionId, long requestId) {
        checkOpen();
        Key key = key(caseId, sessionId, requestId);
        Tracked item = item(key, caseId);
        refresh(item);
        return status(key, item);
    }

    public List<SessionStatus> sessions() {
        checkOpen();
        return sessions.get().stream().map(TestControl::sessionStatus).toList();
    }

    /** Pause only a READY connection. The local console owner can retain overflow evidence after close. */
    public SessionStatus writerPause(String caseId, UUID sessionId) {
        checkOpen();
        validateCase(caseId);
        WriterOwner existing = writers.get(Objects.requireNonNull(sessionId));
        if (existing != null && !existing.caseId().equals(caseId))
            throw new IllegalStateException("Writer belongs to another case");
        Session session = existing == null ? sessions.get().stream()
                .filter(value -> value.id().equals(sessionId)).findFirst()
                .orElseThrow(() -> new IllegalArgumentException("Session not found")) : existing.session();
        if (!session.isReady()) throw new IllegalStateException("Ready session required");
        if (existing == null && writers.size() == MAX_TRACKED)
            throw new IllegalStateException("Test control capacity reached");
        writers.put(sessionId, new WriterOwner(caseId, session));
        session.testPauseWriter(true);
        return sessionStatus(session);
    }

    public SessionStatus writerResume(String caseId, UUID sessionId) {
        checkOpen();
        validateCase(caseId);
        WriterOwner owner = writers.get(sessionId);
        if (owner == null || !owner.caseId().equals(caseId))
            throw new IllegalArgumentException("Writer not owned by case");
        owner.session().testPauseWriter(false);
        return sessionStatus(owner.session());
    }

    public SessionStatus sessionStats(String caseId, UUID sessionId) {
        checkOpen();
        validateCase(caseId);
        WriterOwner owner = writers.get(sessionId);
        if (owner != null && owner.caseId().equals(caseId)) return sessionStatus(owner.session());
        return tracked.entrySet().stream()
                .filter(entry -> entry.getKey().sessionId().equals(sessionId)
                        && entry.getValue().caseId.equals(caseId))
                .map(entry -> sessionStatus(entry.getValue().session)).findFirst()
                .orElseThrow(() -> new IllegalArgumentException("Session not tracked by case"));
    }

    private static SessionStatus sessionStatus(Session session) {
        Session.Diagnostics diagnostics = session.diagnostics();
        return new SessionStatus(session.id(), session.isReady(), session.isOpen(),
                diagnostics.queuedRequests(), diagnostics.outputFrames(), diagnostics);
    }

    public OperationTrace.Snapshot trace(long afterSequence) {
        checkOpen();
        return trace.snapshot(afterSequence);
    }

    public void tick() {
        checkOpen();
        ticks++;
        tracked.values().forEach(TestControl::refresh);
    }

    public long ticks() { checkOpen(); return ticks; }

    /** Observer shutdown owns its tracked connections: cancel before restoring baseline positions. */
    public void cancelCase(String caseId) {
        checkOpen();
        validateCase(caseId);
        tracked.values().stream().filter(item -> item.caseId.equals(caseId))
                .map(item -> item.session).distinct().forEach(Session::close);
        writers.values().stream().filter(item -> item.caseId().equals(caseId))
                .map(WriterOwner::session).forEach(Session::close);
        tracked.values().forEach(TestControl::refresh);
    }

    /** Refuse cleanup while a request could still run and overwrite a restored observer position. */
    public void clearCase(String caseId) {
        checkOpen();
        validateCase(caseId);
        for (Map.Entry<Key, Tracked> entry : tracked.entrySet()) {
            Tracked item = entry.getValue();
            if (!item.caseId.equals(caseId)) continue;
            refresh(item);
            if (item.state == GateState.ARMED || item.state == GateState.GATED
                    || item.session.hasPendingOperation(entry.getKey().requestId())) {
                throw new IllegalStateException("Case still has pending requests");
            }
        }
        tracked.entrySet().removeIf(entry -> entry.getValue().caseId.equals(caseId));
        writers.entrySet().removeIf(entry -> {
            if (!entry.getValue().caseId().equals(caseId)) return false;
            entry.getValue().session().testPauseWriter(false);
            return true;
        });
        trace.clearCase(caseId);
    }

    private static void refresh(Tracked item) {
        if (!item.session.isOpen() && (item.state == GateState.ARMED || item.state == GateState.GATED)) {
            item.state = GateState.CANCELLED;
        }
    }

    private Tracked item(Key key, String caseId) {
        Tracked item = tracked.get(key);
        if (item == null || !item.caseId.equals(caseId)) throw new IllegalArgumentException("Tracked request not found");
        return item;
    }

    private static GateStatus status(Key key, Tracked item) {
        return new GateStatus(item.caseId, key.sessionId(), key.requestId(), item.state,
                item.session.isOpen(), item.session.queuedRequests());
    }

    private static Key key(String caseId, UUID sessionId, long requestId) {
        validateCase(caseId);
        if (sessionId == null || requestId < 1 || requestId > JsonRpcCodec.MAX_REQUEST_ID) {
            throw new IllegalArgumentException("Invalid request reference");
        }
        return new Key(sessionId, requestId);
    }

    private static void validateCase(String caseId) {
        if (caseId == null || !caseId.matches("[A-Za-z0-9_.-]{1,64}")) {
            throw new IllegalArgumentException("Invalid case identifier");
        }
    }

    private void checkOpen() {
        requireGameThread.run();
        if (closed) throw new IllegalStateException("Test control is closed");
    }

    @Override public void close() {
        requireGameThread.run();
        closed = true;
        writers.values().forEach(item -> item.session().testPauseWriter(false));
        writers.clear();
        tracked.clear();
    }
}
