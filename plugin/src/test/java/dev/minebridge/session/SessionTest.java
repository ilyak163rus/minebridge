package dev.minebridge.session;

import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import org.junit.jupiter.api.Test;

import java.nio.ByteBuffer;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

class SessionTest {
    @Test void payloadFreeCountersRetainExactQueueHighWaterAfterOverflowAndClose() {
        Session session = new Session(2, 2, () -> {});
        assertFalse(session.diagnostics().writerPaused());
        session.reactorFrameProgress(31, 1);
        assertEquals(31, session.diagnostics().partialFrameBytes());
        session.reactorFrameProgress(0, 2);
        assertEquals(3, session.diagnostics().receivedFrames());
        assertThrows(IllegalArgumentException.class, () -> session.reactorFrameProgress(-1, 0));
        for (long id = 1; id <= 2; id++) {
            assertTrue(session.reactorOfferRequest(new Request(id, "future", Map.of())));
            assertTrue(session.sendFrame(JsonRpcCodec.errorFrame(id, "METHOD_NOT_FOUND", "not-applied")));
        }
        assertEquals(2, session.diagnostics().requestHighWater());
        assertEquals(2, session.diagnostics().outputHighWater());
        assertFalse(session.sendFrame(JsonRpcCodec.errorFrame(3L, "METHOD_NOT_FOUND", "not-applied")));
        assertFalse(session.isOpen());
        assertEquals(0, session.diagnostics().queuedRequests());
        assertEquals(0, session.diagnostics().outputFrames());
        assertEquals(2, session.diagnostics().requestHighWater());
        assertEquals(2, session.diagnostics().outputHighWater());
    }

    @Test void writerPauseOnlySignalsReactorAndDoesNotHideBoundedOutputOrPerformIo() {
        AtomicInteger wakes = new AtomicInteger();
        Session session = new Session(1, 1, wakes::incrementAndGet);
        session.testPauseWriter(true);
        assertTrue(session.reactorWriterPaused());
        assertEquals(1, wakes.get());
        assertTrue(session.sendFrame(JsonRpcCodec.errorFrame(1L, "METHOD_NOT_FOUND", "not-applied")));
        assertNotNull(session.reactorOutputHead());
        assertEquals(1, session.diagnostics().outputFrames());
        session.testPauseWriter(false);
        assertFalse(session.reactorWriterPaused());
        assertEquals(3, wakes.get());
    }

    @Test void queueObserverRunsAtBoundedQueueBoundaryAndCannotPreventAcceptOrClose() {
        AtomicInteger queued = new AtomicInteger(), cancelled = new AtomicInteger();
        Session.RequestObserver observer = new Session.RequestObserver() {
            @Override public void queued(Session session, Request request) {
                assertTrue(Thread.holdsLock(session));
                assertSame(request, session.peekRequest());
                queued.incrementAndGet();
                throw new IllegalStateException("diagnostic failure");
            }
            @Override public void cancelled(Session session, Request request) {
                assertTrue(Thread.holdsLock(session));
                cancelled.incrementAndGet();
                throw new IllegalStateException("diagnostic failure");
            }
        };
        Session session = new Session(1, 1, () -> {}, 0, null, System::nanoTime, observer);
        assertTrue(session.reactorOfferRequest(new Request(1L, "blocks.set", Map.of())));
        assertFalse(session.reactorOfferRequest(new Request(2L, "blocks.set", Map.of())));
        assertEquals(1, queued.get());
        assertDoesNotThrow(session::closeAfterFlush);
        assertDoesNotThrow(session::close);
        assertEquals(1, cancelled.get());
        assertEquals(0, session.queuedRequests());
    }

    @Test void successfulPublicationHookRunsAtWriterVisibilityBoundaryAndNeverOnRejection() {
        AtomicInteger wakes = new AtomicInteger(), publications = new AtomicInteger();
        Session session = new Session(1, 1, wakes::incrementAndGet);
        byte[] frame = JsonRpcCodec.errorFrame(1L, "METHOD_NOT_FOUND", "not-applied");
        assertTrue(session.sendFrame(frame, () -> {
            assertTrue(Thread.holdsLock(session));
            assertNotNull(session.reactorOutputHead());
            assertEquals(0, wakes.get());
            publications.incrementAndGet();
        }));
        assertFalse(session.sendFrame(frame, publications::incrementAndGet));
        assertEquals(1, publications.get());
        assertFalse(session.sendFrame(frame, publications::incrementAndGet));
        assertEquals(1, publications.get());
    }

    @Test void publicationDiagnosticExceptionDoesNotRetractOrDuplicatePublishedFrame() {
        Session session = new Session(1, 2, () -> { });
        byte[] frame = JsonRpcCodec.errorFrame(1L, "METHOD_NOT_FOUND", "not-applied");
        assertTrue(session.sendFrame(frame, () -> { throw new IllegalStateException(); }));
        ByteBuffer head = session.reactorOutputHead();
        assertNotNull(head);
        session.reactorRemoveOutputHead(head);
        assertNull(session.reactorOutputHead());
        assertTrue(session.isOpen());
    }

    @Test void closeAndBeginHaveOneBoundaryWithoutHoldingLockDuringExecution() {
        Session session = new Session(1, 1, () -> { });
        assertFalse(session.tryBeginOperation(2));
        session.markReady();
        assertTrue(session.tryBeginOperation(2));
        assertFalse(Thread.holdsLock(session));
        assertFalse(session.tryBeginOperation(3));
        session.endOperation(3);
        assertFalse(session.tryBeginOperation(3));
        session.endOperation(2);
        assertTrue(session.tryBeginOperation(3));
        session.close();
        session.endOperation(3);
        assertFalse(session.tryBeginOperation(4));
        Session flushing = new Session(1, 1, () -> { });
        flushing.markReady();
        flushing.closeAfterFlush();
        assertFalse(flushing.tryBeginOperation(2));
    }

    @Test void requestQueueIsBoundedAndFifo() {
        Session session = new Session(2, 2, () -> { });
        Request one = new Request(1L, "future", Map.of());
        Request two = new Request(2L, "future", Map.of());
        assertTrue(session.reactorOfferRequest(one));
        assertTrue(session.reactorOfferRequest(two));
        assertFalse(session.reactorOfferRequest(new Request(3L, "future", Map.of())));
        assertSame(one, session.pollRequest());
        assertSame(two, session.pollRequest());
        assertNull(session.pollRequest());
    }

    @Test void outputCopiesFramesAndCountsPartiallyWrittenHead() {
        AtomicInteger wakes = new AtomicInteger();
        Session session = new Session(2, 2, wakes::incrementAndGet);
        byte[] frame = JsonRpcCodec.errorFrame(1L, "METHOD_NOT_FOUND", "not-applied");
        byte expected = frame[0];
        assertTrue(session.sendFrame(frame));
        frame[0] = '!';
        ByteBuffer first = session.reactorOutputHead();
        assertEquals(expected, first.get());
        assertTrue(session.sendFrame(JsonRpcCodec.errorFrame(2L, "METHOD_NOT_FOUND", "not-applied")));
        assertFalse(session.sendFrame(JsonRpcCodec.errorFrame(3L, "METHOD_NOT_FOUND", "not-applied")));
        assertFalse(session.isOpen());
        assertNull(session.reactorOutputHead());
        assertEquals(3, wakes.get());
    }

    @Test void flushCloseCancelsRequestsButRetainsOnlyAlreadyQueuedOutput() {
        Session session = new Session(2, 2, () -> { });
        session.markReady();
        assertTrue(session.isReady());
        assertTrue(session.reactorOfferRequest(new Request(1L, "future", Map.of())));
        byte[] frame = JsonRpcCodec.errorFrame(1L, "INVALID_REQUEST", "not-applied");
        assertTrue(session.sendFrame(frame));
        session.closeAfterFlush();
        assertNull(session.pollRequest());
        assertFalse(session.isReady());
        assertFalse(session.isOpen());
        assertFalse(session.sendFrame(frame));
        ByteBuffer head = session.reactorOutputHead();
        assertNotNull(head);
        session.reactorRemoveOutputHead(head);
        assertNull(session.reactorOutputHead());
        session.close();
        session.markReady();
        assertFalse(session.isReady());
        assertFalse(session.reactorOfferRequest(new Request(2L, "future", Map.of())));
    }

    @Test void rejectsNonFramesWithoutClosingAnOpenSession() {
        Session session = new Session(1, 1, () -> { });
        for (byte[] frame : new byte[][] { {}, { '\n' }, { 'x' }, { 'x', '\n', 'y', '\n' },
                new byte[JsonRpcCodec.MAX_FRAME_BYTES + 2] }) {
            assertThrows(IllegalArgumentException.class, () -> session.sendFrame(frame));
        }
        assertTrue(session.isOpen());
        assertThrows(IllegalArgumentException.class, () -> new Session(0, 1, () -> { }));
    }

    @Test void identifiersAreConnectionLocalAndToStringContainsNoPayload() {
        Session a = new Session(1, 1, () -> { });
        Session b = new Session(1, 1, () -> { });
        assertNotEquals(a.id(), b.id());
        a.reactorOfferRequest(new Request(1L, "secret", Map.of("token", "private")));
        assertEquals("Session[id=" + a.id() + "]", a.toString());
    }
}
