package dev.minebridge.testing;

import dev.minebridge.execution.OperationTrace;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

class TestControlTest {
    @Test void writerOwnershipKeepsClosedDiagnosticsAndCleanupResumesOnlyOwnedWriter() {
        Session a = new Session(8, 8, () -> {}), b = new Session(8, 8, () -> {});
        a.markReady(); b.markReady();
        TestControl control = new TestControl(() -> List.of(a, b), OperationTrace.disabled(), () -> {});
        assertTrue(control.writerPause("a", a.id()).diagnostics().writerPaused());
        assertFalse(b.diagnostics().writerPaused());
        assertThrows(IllegalStateException.class, () -> control.writerPause("b", a.id()));
        assertThrows(IllegalArgumentException.class, () -> control.writerResume("b", a.id()));
        a.close();
        assertFalse(control.sessionStats("a", a.id()).open());
        control.clearCase("a");
        assertFalse(a.diagnostics().writerPaused());
        assertThrows(IllegalArgumentException.class, () -> control.sessionStats("a", a.id()));
        assertTrue(control.writerPause("b", b.id()).diagnostics().writerPaused());
        control.close();
        assertFalse(b.diagnostics().writerPaused());
    }

    @Test void trackedSessionDiagnosticsRequireCaseOwnershipAndPauseRequiresReadySession() {
        Session session = new Session(8, 8, () -> {});
        TestControl control = new TestControl(() -> List.of(session), OperationTrace.disabled(), () -> {});
        assertThrows(IllegalStateException.class, () -> control.writerPause("case", session.id()));
        session.markReady();
        control.track("case", session.id(), 2);
        session.reactorFrameProgress(17, 1);
        assertEquals(17, control.sessionStats("case", session.id()).diagnostics().partialFrameBytes());
        assertThrows(IllegalArgumentException.class, () -> control.sessionStats("other", session.id()));
        control.writerPause("case", session.id());
        control.cancelCase("case");
        assertFalse(session.isOpen());
        assertDoesNotThrow(() -> control.clearCase("case"));
        assertFalse(session.diagnostics().writerPaused());
    }

    @Test void rejectsInvalidAndMissingOrUnreadyReferencesWithoutPublishingState() {
        Session session = new Session(8, 8, () -> {});
        TestControl control = new TestControl(() -> List.of(session), OperationTrace.disabled(), () -> {});
        assertThrows(IllegalArgumentException.class, () -> control.arm("bad case", session.id(), 2));
        assertThrows(IllegalArgumentException.class, () -> control.arm("case", session.id(), 0));
        assertThrows(IllegalArgumentException.class, () -> control.arm("case", UUID.randomUUID(), 2));
        assertThrows(IllegalStateException.class, () -> control.arm("case", session.id(), 2));
        session.markReady();
        control.arm("case", session.id(), 2);
        assertThrows(IllegalStateException.class, () -> control.track("other", session.id(), 2));
        assertThrows(IllegalArgumentException.class, () -> control.release("other", session.id(), 2));
        assertThrows(IllegalArgumentException.class, () -> control.trace(-1));
    }

    @Test void boundAndGameThreadGuardApplyToAllControlActions() {
        Session session = new Session(8, 8, () -> {});
        session.markReady();
        TestControl bounded = new TestControl(() -> List.of(session), OperationTrace.disabled(), () -> {});
        for (int i = 1; i <= 128; i++) bounded.track("bounded", session.id(), i);
        assertThrows(IllegalStateException.class, () -> bounded.track("bounded", session.id(), 129));
        bounded.clearCase("bounded");
        assertDoesNotThrow(() -> bounded.track("new", session.id(), 129));
        TestControl guarded = new TestControl(() -> fail("Wrong thread"), OperationTrace.disabled(),
                () -> { throw new IllegalStateException("Game thread required"); });
        assertThrows(IllegalStateException.class, () -> guarded.arm("case", session.id(), 2));
        assertThrows(IllegalStateException.class, guarded::sessions);
        assertThrows(IllegalStateException.class, guarded::tick);
        assertThrows(IllegalStateException.class, () -> guarded.trace(0));
        assertThrows(IllegalStateException.class, guarded::close);
    }

    @Test void cleanupRefusesReleasedQueuedAndActiveOperationsUntilTheySettle() {
        Session session = new Session(8, 8, () -> {});
        session.markReady();
        TestControl control = new TestControl(() -> List.of(session), OperationTrace.disabled(), () -> {});
        control.track("case", session.id(), 2);
        session.reactorOfferRequest(new Request(2L, "blocks.set", Map.of()));
        assertThrows(IllegalStateException.class, () -> control.clearCase("case"));
        assertNotNull(session.pollRequest());
        assertTrue(session.tryBeginOperation(2));
        assertThrows(IllegalStateException.class, () -> control.clearCase("case"));
        session.endOperation(2);
        assertDoesNotThrow(() -> control.clearCase("case"));
    }

    @Test void gatesNeverPauseHelloUnknownMethodsOrOtherRequestIds() {
        Session session = new Session(8, 8, () -> {});
        session.markReady();
        TestControl control = new TestControl(() -> List.of(session), OperationTrace.disabled(), () -> {});
        control.arm("case", session.id(), 2);
        assertFalse(control.hold(session, new Request(2L, "system.hello", Map.of())));
        assertFalse(control.hold(session, new Request(2L, "future", Map.of())));
        assertFalse(control.hold(session, new Request(3L, "blocks.set", Map.of())));
        assertFalse(control.hold(session, new Request(null, "blocks.set", Map.of())));
        assertEquals(TestControl.GateState.ARMED, control.gateStatus("case", session.id(), 2).state());
        assertTrue(control.hold(session, new Request(2L, "blocks.set", Map.of())));
        control.close();
        assertThrows(IllegalStateException.class, control::ticks);
    }

    @Test void cancellingOneCaseClosesOnlyItsConnectionsAndKeepsOtherSessionUsable() {
        Session a = new Session(8, 8, () -> {}), b = new Session(8, 8, () -> {});
        a.markReady(); b.markReady();
        TestControl control = new TestControl(() -> List.of(a, b), OperationTrace.disabled(), () -> {});
        control.arm("a", a.id(), 2);
        control.track("b", b.id(), 2);
        control.cancelCase("a");
        assertFalse(a.isOpen());
        assertTrue(b.isReady());
        assertTrue(b.reactorOfferRequest(new Request(2L, "blocks.set", Map.of())));
        assertEquals(1, control.sessions().get(1).queuedRequests());
        assertEquals(TestControl.GateState.CANCELLED, control.gateStatus("a", a.id(), 2).state());
    }
}
