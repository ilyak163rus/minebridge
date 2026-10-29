package dev.minebridge.execution;

import dev.minebridge.protocol.JsonNumber;
import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;
import dev.minebridge.session.WorldContext;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

class OperationTraceTest {
    private static final WorldContext WORLD = new WorldContext("lesson", "minecraft:overworld", UUID.randomUUID(), -64, 320);

    @Test void retainedHistorySurvivesLoggerDrainAndReportsEvictionAndSequenceBounds() {
        OperationTrace trace = new OperationTrace(true, 2, () -> true);
        OperationTrace.Operation operation = trace.operation(UUID.randomUUID(), 2);
        operation.beforeSetter(); operation.afterSetter();
        trace.drain(event -> {});
        assertEquals(2, trace.snapshot(0).events().size());
        operation.ackEnqueued();
        OperationTrace.Snapshot snapshot = trace.snapshot(1);
        assertEquals(List.of(2L, 3L), snapshot.events().stream().map(OperationTrace.Event::sequence).toList());
        assertEquals(3, snapshot.latestSequence());
        assertEquals(2, snapshot.oldestSequence());
        assertEquals(1, snapshot.evictedEvents());
        assertEquals(0, snapshot.droppedEvents());
        assertThrows(UnsupportedOperationException.class, () -> snapshot.events().clear());
        assertTrue(trace.snapshot(3).events().isEmpty());
    }

    @Test void queueAndCancellationAreRecordedAtPublicationAndClearWithOnlySafeMetadata() {
        OperationTrace trace = new OperationTrace(true, () -> false);
        Session session = new Session(2, 2, () -> {}, 0, null, System::nanoTime, trace);
        byte[] hello = JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", 1, "result", Map.of()));
        assertTrue(session.completeHandshake(hello, WORLD));
        trace.correlate("privacy", session.id(), 2);
        String secret = "EXAMPLE-NOT-A-SECRET";
        Request block = new Request(2L, "blocks.set", Map.of("world", secret,
                "position", List.of(new JsonNumber("-17"), new JsonNumber("80"), new JsonNumber("0")),
                "block", Map.of("key", secret, "states", Map.of())));
        assertTrue(session.reactorOfferRequest(block));
        // A queued event exists before any game tick, and hello/token fields never enter tracing.
        assertTrue(session.reactorOfferRequest(new Request(3L, "system.hello", Map.of("token", secret))));
        assertEquals(1, trace.snapshot(0).events().size());
        session.closeAfterFlush();
        session.reactorClosed();
        List<OperationTrace.Event> events = trace.snapshot(0).events();
        assertEquals(List.of(OperationTrace.Phase.QUEUED, OperationTrace.Phase.CANCELLED),
                events.stream().map(OperationTrace.Event::phase).toList());
        for (OperationTrace.Event event : events) {
            assertEquals("privacy", event.caseId());
            assertEquals("lesson", event.worldName());
            assertEquals(WORLD.uuid(), event.worldUuid());
            assertEquals(-17, event.x()); assertEquals(80, event.y()); assertEquals(0, event.z());
            assertFalse(event.primaryThread());
            assertEquals(0, event.applySequence());
            assertFalse(event.toString().contains(secret));
            assertFalse(event.logLine().contains(secret));
        }
    }

    @Test void invalidCoordinatesCannotSmuggleStringsOrOverflowIntoDiagnosticMetadata() {
        OperationTrace trace = new OperationTrace(true, () -> true);
        Session session = new Session(2, 2, () -> {}, 0, null, System::nanoTime, trace);
        session.markReady();
        session.reactorOfferRequest(new Request(2L, "blocks.set", Map.of("position",
                List.of("EXAMPLE-NOT-A-SECRET", new JsonNumber("1e0"), new JsonNumber("9".repeat(5000))))));
        OperationTrace.Event event = trace.snapshot(0).events().getFirst();
        assertNull(event.x()); assertNull(event.y()); assertNull(event.z());
        assertNull(event.worldName()); assertNull(event.worldUuid());
        assertFalse(event.toString().contains("EXAMPLE-NOT-A-SECRET"));
        session.close();
    }

    @Test void queuedOperationCarriesOneApplyAttemptAcrossQueueSetterAndAck() {
        OperationTrace trace = new OperationTrace(true, () -> true);
        Session session = new Session(2, 2, () -> {}, 0, null, System::nanoTime, trace);
        session.markReady();
        Request request = new Request(2L, "blocks.set", Map.of());
        session.reactorOfferRequest(request);
        assertSame(request, session.pollRequest());
        OperationTrace.Operation operation = trace.operation(session, request, WORLD);
        operation.beforeSetter(); operation.afterSetter(); operation.ackEnqueued();
        List<OperationTrace.Event> events = trace.snapshot(0).events();
        assertEquals(List.of(OperationTrace.Phase.QUEUED, OperationTrace.Phase.APPLY_BEGIN,
                OperationTrace.Phase.APPLY_DONE, OperationTrace.Phase.ACK_ENQUEUED),
                events.stream().map(OperationTrace.Event::phase).toList());
        assertEquals(List.of(0L, 1L, 1L, 1L), events.stream().map(OperationTrace.Event::applySequence).toList());
        assertEquals(WORLD.uuid(), events.getLast().worldUuid());
    }

    @Test void correlatesAttemptsAndEmitsOrderedEventsWithoutCallingSinkDuringRecord() {
        OperationTrace trace = new OperationTrace(true, () -> true);
        UUID a = UUID.randomUUID(), b = UUID.randomUUID();
        OperationTrace.Operation one = trace.operation(a, 2), two = trace.operation(b, 2);
        one.beforeSetter();
        one.afterSetter();
        one.ackEnqueued();
        two.beforeSetter();
        two.afterSetter();
        two.ackEnqueued();
        List<OperationTrace.Event> events = new ArrayList<>();
        trace.drain(events::add);
        assertEquals(6, events.size());
        assertEquals(List.of(OperationTrace.Phase.APPLY_BEGIN, OperationTrace.Phase.APPLY_DONE,
                OperationTrace.Phase.ACK_ENQUEUED), events.subList(0, 3).stream()
                .map(OperationTrace.Event::phase).toList());
        for (int i = 0; i < 6; i++) {
            OperationTrace.Event event = events.get(i);
            assertEquals(i + 1, event.sequence());
            assertEquals(i < 3 ? a : b, event.sessionId());
            assertEquals(i < 3 ? 1 : 2, event.applySequence());
            assertEquals(2, event.requestId());
            assertEquals(Thread.currentThread().threadId(), event.threadId());
            assertTrue(event.primaryThread());
        }
        assertEquals(0, trace.droppedEvents());
        trace.drain(event -> fail("Already drained"));
    }

    @Test void bufferIsBoundedAndSequenceGapsExposeDrops() {
        OperationTrace trace = new OperationTrace(true, 2, () -> true);
        OperationTrace.Operation one = trace.operation(UUID.randomUUID(), 2);
        one.beforeSetter(); one.afterSetter(); one.ackEnqueued();
        List<OperationTrace.Event> events = new ArrayList<>();
        trace.drain(events::add);
        assertEquals(2, events.size());
        assertEquals(1, trace.droppedEvents());
        trace.operation(UUID.randomUUID(), 3).beforeSetter();
        trace.drain(events::add);
        assertEquals(4, events.getLast().sequence());
        assertEquals(2, events.getLast().applySequence());
    }

    @Test void disabledRecordingDoesNotConsultThreadSupplier() {
        OperationTrace trace = new OperationTrace(false, () -> { fail("Disabled"); return false; });
        OperationTrace.Operation operation = trace.operation(UUID.randomUUID(), 2);
        operation.beforeSetter(); operation.afterSetter(); operation.ackEnqueued();
        trace.drain(event -> fail("Disabled"));
        assertEquals(0, trace.droppedEvents());
    }

    @Test void diagnosticFailuresCannotInterruptOperationOrDrainRemainingEvents() {
        OperationTrace brokenMetadata = new OperationTrace(true, () -> { throw new IllegalStateException(); });
        assertDoesNotThrow(() -> brokenMetadata.operation(UUID.randomUUID(), 2).beforeSetter());
        assertEquals(1, brokenMetadata.droppedEvents());
        OperationTrace trace = new OperationTrace(true, () -> true);
        OperationTrace.Operation operation = trace.operation(UUID.randomUUID(), 2);
        operation.beforeSetter(); operation.afterSetter(); operation.ackEnqueued();
        List<OperationTrace.Event> seen = new ArrayList<>();
        assertDoesNotThrow(() -> trace.drain(event -> {
            seen.add(event);
            throw new IllegalStateException();
        }));
        assertEquals(3, seen.size());
    }
}
