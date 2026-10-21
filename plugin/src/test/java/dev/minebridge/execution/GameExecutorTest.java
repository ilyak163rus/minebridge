package dev.minebridge.execution;

import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;
import dev.minebridge.testing.TestControl;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.*;

class GameExecutorTest {
    @Test void gateKeepsActualHeadAndFifoWithoutStoppingTicksOrOtherSessions() {
        Session a = new Session(8, 8, () -> {}), b = new Session(8, 8, () -> {});
        a.markReady(); b.markReady();
        OperationTrace trace = new OperationTrace(true, () -> true);
        TestControl control = new TestControl(() -> List.of(a, b), trace, () -> {});
        control.arm("gate", a.id(), 2);
        Request a2 = new Request(2L, "blocks.set", Map.of());
        a.reactorOfferRequest(a2);
        a.reactorOfferRequest(new Request(3L, "blocks.set", Map.of()));
        b.reactorOfferRequest(new Request(2L, "blocks.set", Map.of()));
        List<String> dispatched = new ArrayList<>();
        GameExecutor executor = new GameExecutor(() -> List.of(a, b),
                (session, request) -> dispatched.add((session == a ? "a" : "b") + request.id()),
                () -> {}, () -> {}, ExecutionLimits.defaults(), () -> 0, control);
        executor.run();
        assertEquals(List.of("b2"), dispatched);
        assertSame(a2, a.peekRequest());
        assertEquals(2, a.queuedRequests());
        assertEquals(TestControl.GateState.GATED, control.gateStatus("gate", a.id(), 2).state());
        executor.run();
        assertEquals(2, control.ticks());
        assertEquals(List.of("b2"), dispatched);
        control.release("gate", a.id(), 2);
        assertThrows(IllegalStateException.class, () -> control.clearCase("gate"));
        executor.run();
        assertEquals(List.of("b2", "a2", "a3"), dispatched);
        assertNull(a.peekRequest());
        assertDoesNotThrow(() -> control.clearCase("gate"));
    }

    @Test void closingHeldHeadCancelsQueueAndReleaseNeverResurrectsIt() {
        OperationTrace trace = new OperationTrace(true, () -> true);
        Session session = new Session(8, 8, () -> {}, 0, null, System::nanoTime, trace);
        session.markReady();
        TestControl control = new TestControl(() -> List.of(session), trace, () -> {});
        control.arm("cancel", session.id(), 2);
        session.reactorOfferRequest(new Request(2L, "blocks.set", Map.of()));
        session.reactorOfferRequest(new Request(3L, "blocks.set", Map.of()));
        GameExecutor executor = new GameExecutor(() -> List.of(session), (s, r) -> fail("Cancelled"),
                () -> {}, () -> {}, ExecutionLimits.defaults(), () -> 0, control);
        executor.run();
        control.cancelCase("cancel");
        assertEquals(TestControl.GateState.CANCELLED, control.release("cancel", session.id(), 2).state());
        executor.run();
        assertEquals(List.of(OperationTrace.Phase.QUEUED, OperationTrace.Phase.QUEUED,
                OperationTrace.Phase.CANCELLED, OperationTrace.Phase.CANCELLED),
                trace.snapshot(0).events().stream().map(OperationTrace.Event::phase).toList());
        assertFalse(control.gateStatus("cancel", session.id(), 2).sessionOpen());
        assertDoesNotThrow(() -> control.clearCase("cancel"));
    }

    private static Session queued(int count) {
        Session session = new Session(8, 8, () -> { });
        for (long id = 1; id <= count; id++) {
            assertTrue(session.reactorOfferRequest(new Request(id, "future", Map.of())));
        }
        return session;
    }

    @Test void boundsPerTickAndPerSessionAndPreservesFifo() {
        Session a = queued(8), b = queued(8);
        List<String> seen = new ArrayList<>();
        GameExecutor executor = new GameExecutor(() -> List.of(a, b),
                (session, request) -> seen.add((session == a ? "a" : "b") + request.id()),
                () -> { }, () -> { }, new ExecutionLimits(6, 4, 100), () -> 0);
        executor.run();
        assertEquals(List.of("a1", "b1", "a2", "b2", "a3", "b3"), seen);
        executor.run();
        assertEquals(List.of("a4", "b4", "a5", "b5", "a6", "b6"), seen.subList(6, 12));
        List<Long> one = new ArrayList<>();
        Session solo = queued(8);
        GameExecutor bounded = new GameExecutor(() -> List.of(solo),
                (session, request) -> one.add(request.id()), () -> { }, () -> { },
                new ExecutionLimits(32, 4, 100), () -> 0);
        bounded.run();
        assertEquals(List.of(1L, 2L, 3L, 4L), one);
        assertEquals(5L, solo.pollRequest().id());
    }

    @Test void elapsedBudgetStopsBetweenRequestsAndResumesWithNextSession() {
        Session a = queued(2), b = queued(2);
        List<Session> seen = new ArrayList<>();
        AtomicLong now = new AtomicLong();
        GameExecutor executor = new GameExecutor(() -> List.of(a, b), (session, request) -> {
            seen.add(session);
            now.addAndGet(2_000_000);
        }, () -> { }, () -> { }, ExecutionLimits.defaults(), now::get);
        executor.run();
        assertEquals(List.of(a), seen);
        executor.run();
        assertEquals(List.of(a, b), seen);
        assertEquals(2L, a.pollRequest().id());
        assertEquals(2L, b.pollRequest().id());
    }

    @Test void eightBusyConnectionsReachGlobalDefaultBudget() {
        List<Session> active = new ArrayList<>();
        for (int i = 0; i < 8; i++) active.add(queued(8));
        AtomicInteger dispatched = new AtomicInteger();
        GameExecutor executor = new GameExecutor(() -> active,
                (session, request) -> dispatched.incrementAndGet(), () -> { }, () -> { },
                ExecutionLimits.defaults(), () -> 0);
        executor.run();
        assertEquals(32, dispatched.get());
        active.forEach(session -> assertEquals(5L, session.pollRequest().id()));
    }

    @Test void closedConnectionAndIdleConnectionDoNotBlockOtherSession() {
        Session closed = queued(2), idle = queued(0), busy = queued(2);
        closed.close();
        AtomicInteger dispatched = new AtomicInteger(), cleanups = new AtomicInteger();
        GameExecutor executor = new GameExecutor(() -> List.of(closed, idle, busy),
                (session, request) -> {
                    assertSame(busy, session);
                    dispatched.incrementAndGet();
                }, cleanups::incrementAndGet, () -> { }, ExecutionLimits.defaults(), () -> 0);
        executor.run();
        assertEquals(2, dispatched.get());
        assertEquals(1, cleanups.get());
        executor.close();
        executor.run();
        assertEquals(1, cleanups.get());
    }

    @Test void threadGuardRunsBeforeConsumingAnyRequest() {
        Session session = queued(1);
        GameExecutor executor = new GameExecutor(() -> List.of(session), (s, r) -> fail(),
                () -> fail(), () -> { throw new IllegalStateException("Game thread required"); },
                ExecutionLimits.defaults());
        assertThrows(IllegalStateException.class, executor::run);
        assertEquals(1L, session.pollRequest().id());
    }

    @Test void validatesBudgets() {
        assertThrows(IllegalArgumentException.class, () -> new ExecutionLimits(0, 1, 1));
        assertThrows(IllegalArgumentException.class, () -> new ExecutionLimits(1, 2, 1));
        assertThrows(IllegalArgumentException.class, () -> new ExecutionLimits(1, 1, 0));
    }
}
