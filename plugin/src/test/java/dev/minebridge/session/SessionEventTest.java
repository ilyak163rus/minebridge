package dev.minebridge.session;

import dev.minebridge.protocol.JsonRpcCodec;
import org.junit.jupiter.api.Test;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

class SessionEventTest {
    private static byte[] frame(long id) {
        return JsonRpcCodec.errorFrame(id, "METHOD_NOT_FOUND", "not-applied");
    }
    private static String text(ByteBuffer buffer) {
        ByteBuffer copy = buffer.duplicate();
        byte[] bytes = new byte[copy.remaining()]; copy.get(bytes);
        return new String(bytes, StandardCharsets.UTF_8);
    }
    private static Session ready() {
        Session session = new Session(4, 4, () -> {}); session.markReady(); return session;
    }

    @Test void saturatedLiveQueueLeavesRpcAndDedicatedOverflowControlUsable() {
        Session session = ready(); UUID subscription = UUID.randomUUID();
        for (int i = 0; i < 512; i++) assertTrue(session.offerEvent(frame(1), subscription));
        assertFalse(session.offerEvent(frame(1), subscription));
        assertTrue(session.isOpen());
        assertEquals(512, session.eventOutputFrames());
        session.offerEventOverflow(subscription, "server", 1);
        assertTrue(session.sendFrame(frame(2)));
        ByteBuffer ack = session.reactorOutputHead();
        assertTrue(text(ack).contains("\"id\":2"));
        session.reactorRemoveOutputHead(ack);
        ByteBuffer notice = session.reactorOutputHead();
        assertTrue(text(notice).contains("events.overflow"));
        assertEquals("1", ((dev.minebridge.protocol.JsonNumber) ((Map<?, ?>)
                JsonRpcCodec.decodeEventNotification(text(notice).strip().getBytes(StandardCharsets.UTF_8)).get("params"))
                .get("lostCount")).text());
        session.reactorRemoveOutputHead(notice);
        assertTrue(text(session.reactorOutputHead()).contains("\"id\":1"));
    }

    @Test void partialLiveFrameIsPinnedAcrossRpcAndOverflowPublication() {
        Session session = ready(); UUID subscription = UUID.randomUUID();
        session.offerEvent(frame(1), subscription);
        ByteBuffer live = session.reactorOutputHead(); live.get();
        session.sendFrame(frame(2)); session.offerEventOverflow(subscription, "server", 3);
        assertSame(live, session.reactorOutputHead());
        live.position(live.limit()); session.reactorRemoveOutputHead(live);
        assertTrue(text(session.reactorOutputHead()).contains("\"id\":2"));
        session.reactorRemoveOutputHead(session.reactorOutputHead());
        assertTrue(text(session.reactorOutputHead()).contains("events.overflow"));
    }

    @Test void unsubscribeDropsQueuedFramesAndControlsButFinishesSelectedFrameBeforeAck() {
        Session session = ready(); UUID retired = UUID.randomUUID(), other = UUID.randomUUID();
        session.offerEvent(frame(1), retired);
        ByteBuffer partial = session.reactorOutputHead(); partial.get();
        session.offerEvent(frame(2), retired); session.offerEvent(frame(3), other);
        session.offerEventOverflow(retired, "server", 2);
        session.purgeEvents(retired); session.sendFrame(frame(4));
        assertSame(partial, session.reactorOutputHead());
        session.reactorRemoveOutputHead(partial);
        ByteBuffer ack = session.reactorOutputHead(); assertTrue(text(ack).contains("\"id\":4"));
        session.reactorRemoveOutputHead(ack);
        ByteBuffer remaining = session.reactorOutputHead(); assertTrue(text(remaining).contains("\"id\":3"));
        session.reactorRemoveOutputHead(remaining); assertNull(session.reactorOutputHead());
    }

    @Test void overflowControlsCoalesceAndNeverDependOnRpcCapacity() {
        Session session = ready(); UUID first = UUID.randomUUID(), second = UUID.randomUUID();
        session.offerEventOverflow(first, "server", 1); session.offerEventOverflow(first, "server", 2);
        session.offerEventOverflow(second, "server", 4);
        String notice = text(session.reactorOutputHead());
        assertTrue(notice.contains(first.toString())); assertTrue(notice.contains(second.toString()));
        assertTrue(notice.contains("\"lostCount\":7"));
        JsonRpcCodec.decodeEventNotification(notice.strip().getBytes(StandardCharsets.UTF_8));
        session.reactorRemoveOutputHead(session.reactorOutputHead()); assertNull(session.reactorOutputHead());
    }

    @Test void closeAfterFlushKeepsPartialFrameAndAcceptedRpcButDropsFutureLiveFrames() {
        Session session = ready(); UUID subscription = UUID.randomUUID();
        session.offerEvent(frame(1), subscription); ByteBuffer partial = session.reactorOutputHead(); partial.get();
        session.offerEvent(frame(2), subscription); session.sendFrame(frame(3));
        session.offerEventOverflow(subscription, "server", 2); session.closeAfterFlush();
        assertFalse(session.offerEvent(frame(4), subscription));
        assertSame(partial, session.reactorOutputHead()); session.reactorRemoveOutputHead(partial);
        ByteBuffer ack = session.reactorOutputHead(); assertTrue(text(ack).contains("\"id\":3"));
        session.reactorRemoveOutputHead(ack); assertNull(session.reactorOutputHead());
        session.close(); assertEquals(0, session.eventOutputFrames());
    }
}
