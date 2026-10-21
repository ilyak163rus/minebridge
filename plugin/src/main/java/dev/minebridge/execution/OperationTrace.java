package dev.minebridge.execution;

import dev.minebridge.protocol.JsonNumber;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;
import dev.minebridge.session.WorldContext;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;

/** Optional bounded diagnostics. Recording never calls a sink, performs IO or reads live Paper state. */
public final class OperationTrace implements Session.RequestObserver {
    public enum Phase { QUEUED, APPLY_BEGIN, APPLY_DONE, ERROR, CANCELLED, ACK_ENQUEUED }

    public record Event(long sequence, Phase phase, UUID sessionId, long requestId,
                        long applySequence, long threadId, boolean primaryThread,
                        String caseId, String worldName, UUID worldUuid, Integer x, Integer y, Integer z,
                        String errorCode, String outcome) {
        public String logLine() {
            return "TRACE seq=" + sequence + " phase=" + phase + " sessionId=" + sessionId
                    + " requestId=" + requestId + " applySequence=" + applySequence
                    + " threadId=" + threadId + " primaryThread=" + primaryThread
                    + " caseId=" + caseId + " worldUuid=" + worldUuid
                    + " x=" + x + " y=" + y + " z=" + z
                    + " errorCode=" + errorCode + " outcome=" + outcome;
        }
    }

    /** Retained history is independent of the logger drain. Gaps and retention eviction are explicit. */
    public record Snapshot(List<Event> events, long latestSequence, long oldestSequence,
                           long droppedEvents, long evictedEvents) {
        public Snapshot { events = List.copyOf(events); }
    }

    private record Key(UUID sessionId, long requestId) {}
    private static final int MAX_TRACKED = 256;
    private final boolean enabled;
    private final int capacity;
    private final BooleanSupplier primaryThread;
    private final ArrayDeque<Event> pending = new ArrayDeque<>();
    private final ArrayDeque<Event> retained = new ArrayDeque<>();
    private final Map<Key, Operation> operations = new HashMap<>();
    private final Map<Key, String> cases = new HashMap<>();
    private long sequence;
    private long applySequence;
    private long dropped;
    private long evicted;

    public OperationTrace(boolean enabled, BooleanSupplier primaryThread) {
        this(enabled, 256, primaryThread);
    }

    OperationTrace(boolean enabled, int capacity, BooleanSupplier primaryThread) {
        if (capacity < 1 || capacity > 4096) throw new IllegalArgumentException("Invalid trace capacity");
        this.enabled = enabled;
        this.capacity = capacity;
        this.primaryThread = Objects.requireNonNull(primaryThread);
    }

    public static OperationTrace disabled() { return new OperationTrace(false, () -> false); }

    public synchronized void correlate(String caseId, UUID sessionId, long requestId) {
        Objects.requireNonNull(caseId);
        Key key = new Key(Objects.requireNonNull(sessionId), requestId);
        String previous = cases.get(key);
        if (previous != null && !previous.equals(caseId)) throw new IllegalStateException("Request already tracked");
        if (previous == null && cases.size() == MAX_TRACKED) throw new IllegalStateException("Trace correlation limit");
        cases.put(key, caseId);
    }

    public synchronized void clearCase(String caseId) {
        cases.entrySet().removeIf(entry -> entry.getValue().equals(caseId));
    }

    /** Compatibility seam for direct router/service tests that have no queue publication. */
    public synchronized Operation operation(UUID sessionId, long requestId) {
        Key key = new Key(Objects.requireNonNull(sessionId), requestId);
        Operation existing = operations.get(key);
        return existing == null ? new Operation(key) : existing;
    }

    public synchronized Operation operation(Session session, Request request, WorldContext world) {
        Operation operation = operation(session.id(), request.id());
        operation.context(world, request);
        return operation;
    }

    @Override public void queued(Session session, Request request) {
        if (!enabled || request.notification() || !"blocks.set".equals(request.method())) return;
        WorldContext world = session.worldContext();
        Key key = new Key(session.id(), request.id());
        Operation operation = new Operation(key);
        operation.context(world, request);
        synchronized (this) {
            // The diagnostic index cannot grow with an unbounded stream of connections.
            if (operations.size() < MAX_TRACKED) operations.put(key, operation);
            else dropped++;
            record(Phase.QUEUED, operation, null, null);
        }
    }

    @Override public void cancelled(Session session, Request request) {
        if (!enabled || request.notification() || !"blocks.set".equals(request.method())) return;
        WorldContext world = session.worldContext();
        Operation operation = operation(session, request, world);
        operation.cancelled();
    }

    public final class Operation {
        private final Key key;
        private long attempt;
        private WorldContext world;
        private Integer x, y, z;
        private boolean terminal;

        private Operation(Key key) { this.key = key; }

        private void context(WorldContext selectedWorld, Request request) {
            // Only authenticated immutable metadata is retained; raw world/key/token strings never are.
            world = selectedWorld;
            if (request.params().get("position") instanceof List<?> position && position.size() == 3) {
                x = coordinate(position.get(0));
                y = coordinate(position.get(1));
                z = coordinate(position.get(2));
            }
        }

        public void beforeSetter() { record(Phase.APPLY_BEGIN, this, null, null); }
        public void afterSetter() { record(Phase.APPLY_DONE, this, null, null); }
        /** Only the Session publication hook calls this, under its short output lock. */
        public void ackEnqueued() { record(Phase.ACK_ENQUEUED, this, null, null); }
        public void error(String code, String outcome) { record(Phase.ERROR, this, code, outcome); }
        public void cancelled() { record(Phase.CANCELLED, this, null, "not-applied"); }
        /** An applied operation whose connection closed before ACK still releases the bounded index. */
        public void finished() {
            synchronized (OperationTrace.this) { operations.remove(key, this); }
        }
    }

    private static Integer coordinate(Object value) {
        if (!(value instanceof JsonNumber number) || number.text().length() > 11
                || !number.text().matches("-?(0|[1-9][0-9]*)")) return null;
        try { return Integer.valueOf(number.text()); }
        catch (NumberFormatException ignored) { return null; }
    }

    private synchronized void record(Phase phase, Operation operation, String code, String outcome) {
        if (!enabled || operation.terminal) return;
        long eventSequence = ++sequence;
        if (phase == Phase.APPLY_BEGIN) operation.attempt = ++applySequence;
        if (phase == Phase.ERROR || phase == Phase.CANCELLED || phase == Phase.ACK_ENQUEUED) {
            operation.terminal = true;
            operations.remove(operation.key, operation);
        }
        boolean primary;
        try { primary = primaryThread.getAsBoolean(); }
        catch (RuntimeException ignored) { dropped++; return; }
        Event event = new Event(eventSequence, phase, operation.key.sessionId(), operation.key.requestId(),
                operation.attempt, Thread.currentThread().threadId(), primary, cases.get(operation.key),
                operation.world == null ? null : operation.world.name(),
                operation.world == null ? null : operation.world.uuid(), operation.x, operation.y, operation.z,
                code, outcome);
        if (pending.size() == capacity) dropped++;
        else pending.addLast(event);
        if (retained.size() == capacity) { retained.removeFirst(); evicted++; }
        retained.addLast(event);
    }

    public synchronized Snapshot snapshot(long afterSequence) {
        if (afterSequence < 0) throw new IllegalArgumentException("Invalid trace sequence");
        List<Event> events = retained.stream().filter(event -> event.sequence() > afterSequence).toList();
        return new Snapshot(events, sequence, retained.isEmpty() ? sequence + 1 : retained.getFirst().sequence(),
                dropped, evicted);
    }

    /** Drain on the game thread, outside Session locks; diagnostic failure cannot change an ACK. */
    public void drain(Consumer<Event> sink) {
        Objects.requireNonNull(sink);
        List<Event> events;
        synchronized (this) {
            if (pending.isEmpty()) return;
            events = new ArrayList<>(pending);
            pending.clear();
        }
        for (Event event : events) {
            try { sink.accept(event); }
            catch (RuntimeException ignored) { /* Diagnostics must not cancel game dispatch. */ }
        }
    }

    public synchronized long droppedEvents() { return dropped; }
}
