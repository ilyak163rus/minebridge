package dev.minebridge.session;

import dev.minebridge.protocol.JsonRpcCodec;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.*;

class SessionManagerTest {
    private static final WorldContext WORLD = new WorldContext("lesson", UUID.randomUUID(), -64, 320);

    @Test void successfulHandshakeQueuesOnceAndPinsWorldPerConnection() {
        SessionManager manager = new SessionManager(2);
        Session session = session();
        assertTrue(manager.context(session).isEmpty());
        assertTrue(manager.completeHandshake(session, WORLD, frame()));
        assertTrue(session.isReady());
        assertSame(WORLD, manager.context(session).orElseThrow());
        assertNotNull(session.reactorOutputHead());
        assertFalse(manager.completeHandshake(session, WORLD, frame()));
        assertEquals(1, manager.readyCount());
    }

    @Test void registryIsBoundedAndClosedContextsDoNotConsumeCapacity() {
        SessionManager manager = new SessionManager(1);
        Session a = session(), b = session();
        assertTrue(manager.completeHandshake(a, WORLD, frame()));
        assertFalse(manager.completeHandshake(b, WORLD, frame()));
        assertFalse(b.isReady());
        a.close();
        assertTrue(manager.context(a).isEmpty());
        assertTrue(manager.completeHandshake(b, WORLD, frame()));
        assertEquals(1, manager.readyCount());
    }

    @Test void managerCloseClearsContextsAndClosesReadyConnections() {
        SessionManager manager = new SessionManager(2);
        Session a = session(), b = session();
        manager.completeHandshake(a, WORLD, frame());
        manager.completeHandshake(b, WORLD, frame());
        manager.close();
        manager.close();
        assertEquals(0, manager.readyCount());
        assertFalse(a.isOpen());
        assertFalse(b.isOpen());
        Session later = session();
        assertFalse(manager.completeHandshake(later, WORLD, frame()));
        assertFalse(later.isReady());
    }

    @Test void deadlineIsCheckedAtomicallyAtHelloCommitIncludingExactBoundary() {
        AtomicLong now = new AtomicLong(100);
        Session before = new Session(1, 1, () -> { }, 100, Duration.ofNanos(10), now::get);
        Session at = new Session(1, 1, () -> { }, 100, Duration.ofNanos(10), now::get);
        now.set(109);
        assertTrue(before.completeHandshake(frame()));
        now.set(110);
        assertFalse(at.completeHandshake(frame()));
        assertFalse(at.isOpen());
        assertNull(at.reactorOutputHead());
        assertTrue(before.isReady());
        assertFalse(before.handshakeExpired(111));
    }

    @Test void trustedMarkReadyCannotBypassProductionDeadline() {
        AtomicLong now = new AtomicLong(110);
        Session session = new Session(1, 1, () -> { }, 100, Duration.ofNanos(10), now::get);
        session.markReady();
        assertFalse(session.isReady());
        assertFalse(session.isOpen());
    }

    @Test void closedOrFlushClosingConnectionsNeverBecomeReady() {
        SessionManager manager = new SessionManager(2);
        Session closed = session(), flushing = session();
        closed.close();
        flushing.sendFrame(frame());
        flushing.closeAfterFlush();
        assertFalse(manager.completeHandshake(closed, WORLD, frame()));
        assertFalse(manager.completeHandshake(flushing, WORLD, frame()));
        assertEquals(0, manager.readyCount());
    }

    @Test void metadataAndCapacityRejectInvalidConfiguration() {
        assertThrows(IllegalArgumentException.class, () -> new SessionManager(0));
        assertThrows(IllegalArgumentException.class, () -> new SessionManager(1025));
        assertThrows(IllegalArgumentException.class, () -> new WorldContext("", UUID.randomUUID(), 0, 1));
        assertThrows(IllegalArgumentException.class, () -> new WorldContext("lesson", UUID.randomUUID(), 1, 1));
        assertThrows(IllegalArgumentException.class, () -> new Session(1, 1, () -> { }, 0,
                Duration.ZERO, System::nanoTime));
    }

    private static Session session() { return new Session(2, 2, () -> { }); }
    private static byte[] frame() { return JsonRpcCodec.errorFrame(1L, "LIMIT_EXCEEDED", "not-applied"); }
}
