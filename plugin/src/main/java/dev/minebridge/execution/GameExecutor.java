package dev.minebridge.execution;

import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;
import dev.minebridge.testing.TestControl;

import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.function.BiConsumer;
import java.util.function.LongSupplier;
import java.util.function.Supplier;

/** One bounded Paper tick; socket IO stays on the reactor. No worker or second queue. */
public final class GameExecutor implements Runnable, AutoCloseable {
    private final Supplier<List<Session>> sessions;
    private final BiConsumer<Session, Request> dispatch;
    private final Runnable cleanup;
    private final Runnable requireGameThread;
    private final ExecutionLimits limits;
    private final LongSupplier clock;
    private final TestControl testControl;
    private UUID lastVisited;
    private boolean closed;

    public GameExecutor(Supplier<List<Session>> sessions, BiConsumer<Session, Request> dispatch,
                        Runnable cleanup, Runnable requireGameThread, ExecutionLimits limits) {
        this(sessions, dispatch, cleanup, requireGameThread, limits, System::nanoTime, null);
    }

    public GameExecutor(Supplier<List<Session>> sessions, BiConsumer<Session, Request> dispatch,
                        Runnable cleanup, Runnable requireGameThread, ExecutionLimits limits,
                        TestControl testControl) {
        this(sessions, dispatch, cleanup, requireGameThread, limits, System::nanoTime, testControl);
    }

    /** Clock injection tests budgets without sleeping or relying on machine speed. */
    GameExecutor(Supplier<List<Session>> sessions, BiConsumer<Session, Request> dispatch,
                 Runnable cleanup, Runnable requireGameThread, ExecutionLimits limits,
                 LongSupplier clock) {
        this(sessions, dispatch, cleanup, requireGameThread, limits, clock, null);
    }

    GameExecutor(Supplier<List<Session>> sessions, BiConsumer<Session, Request> dispatch,
                 Runnable cleanup, Runnable requireGameThread, ExecutionLimits limits,
                 LongSupplier clock, TestControl testControl) {
        this.sessions = Objects.requireNonNull(sessions);
        this.dispatch = Objects.requireNonNull(dispatch);
        this.cleanup = Objects.requireNonNull(cleanup);
        this.requireGameThread = Objects.requireNonNull(requireGameThread);
        this.limits = Objects.requireNonNull(limits);
        this.clock = Objects.requireNonNull(clock);
        this.testControl = testControl;
    }

    @Override public void run() {
        requireGameThread.run();
        if (closed) return;
        if (testControl != null) testControl.tick();
        cleanup.run();
        List<Session> active = sessions.get();
        if (active.isEmpty()) return;
        int start = 0;
        for (int i = 0; i < active.size(); i++) {
            if (active.get(i).id().equals(lastVisited)) {
                start = (i + 1) % active.size();
                break;
            }
        }
        int[] used = new int[active.size()];
        int total = 0;
        long began = clock.getAsLong();
        boolean progress;
        do {
            progress = false;
            for (int offset = 0; offset < active.size(); offset++) {
                if (total == limits.maxOperationsPerTick()
                        || clock.getAsLong() - began >= limits.budgetNanos()) return;
                int index = (start + offset) % active.size();
                Session session = active.get(index);
                lastVisited = session.id();
                if (used[index] == limits.maxOperationsPerSessionPerTick()) continue;
                if (session.hasActiveOperation()) continue;
                Request request = session.peekRequest();
                if (request == null) continue;
                if (testControl != null && testControl.hold(session, request)) continue;
                // Close may clear the queue between peek and poll. Never dispatch a cancelled head.
                request = session.pollRequest();
                if (request == null) continue;
                used[index]++;
                total++;
                progress = true;
                dispatch.accept(session, request);
            }
        } while (progress);
    }

    @Override public void close() {
        requireGameThread.run();
        closed = true;
    }
}
