package dev.minebridge.events;

import dev.minebridge.protocol.JsonNumber;
import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;
import dev.minebridge.session.WorldContext;
import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class EventsServiceTest {
    private static final WorldContext WORLD = new WorldContext("lesson", "minecraft:overworld", UUID.randomUUID(), -64, 320);
    private static final EventsService.PlayerSnapshot ALICE = new EventsService.PlayerSnapshot(UUID.randomUUID(), "Alice", 1, WORLD);
    private static final EventsService.PlayerSnapshot BOB = new EventsService.PlayerSnapshot(UUID.randomUUID(), "Bob", 2, WORLD);

    @Test void captureStartsAtHelloBeforeAckAndDoesNotRequireSubscription() throws Exception {
        Fixture f = new Fixture();
        f.events.captureChat(ALICE, "before", false);
        Session session = f.newSession();
        Map<String, Object> hello = f.events.prepareHello(session, WORLD);
        assertEquals(0L, hello.get("startSequence"));
        f.events.captureChat(ALICE, "after prepare before ACK", false);
        session.markReady(); f.events.commitHello(session); f.drain();
        Map<String, Object> result = f.poll(session, null, 100);
        assertEquals(List.of("after prepare before ACK"), messages(result));
        assertNull(session.reactorOutputHead()); // no unsolicited notifications without a subscription
        f.validateResult("events.pollEvents", result);
    }

    @Test void newConnectionExcludesOlderIngressAndTwoSessionsKeepIndependentClientCursors() throws Exception {
        Fixture f = new Fixture(); Session first = f.connect();
        f.events.captureChat(ALICE, "older waiting ingress", false);
        Session second = f.connect();
        f.events.captureChat(ALICE, "both", false); f.drain();
        Map<String, Object> firstPage = f.poll(first, null, 100);
        assertEquals(List.of("older waiting ingress", "both"), messages(firstPage));
        assertEquals(List.of("both"), messages(f.poll(second, null, 100)));
        assertEquals(List.of("older waiting ingress", "both"), messages(f.poll(first, null, 100)));
        assertEquals(List.of(), messages(f.poll(first, firstPage.get("nextCursor"), 100)));
    }

    @Test void subscribeAckFenceAndCanonicalIdentityAreIndependentFromHistoryReads() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect(); UUID id = UUID.randomUUID();
        Request subscribe = f.subscribeRequest(id, "@a", null);
        f.events.execute(session, subscribe, WORLD);
        f.events.captureChat(ALICE, "pending", false); f.drain();
        assertNull(session.reactorOutputHead());
        f.events.afterResponse(session, subscribe, true);
        f.events.captureChat(ALICE, "live", false); f.drain();
        Map<?, ?> notification = f.notification(session);
        Map<?, ?> params = (Map<?, ?>) notification.get("params");
        Map<?, ?> live = (Map<?, ?>) params.get("event");
        assertEquals(id.toString(), params.get("subscriptionId"));
        assertEquals(new JsonNumber("1"), params.get("deliverySequence"));
        Map<String, Object> result = f.poll(session, null, 100);
        Map<?, ?> historicalLive = (Map<?, ?>) ((List<?>) result.get("events")).getLast();
        assertEquals(live.get("eventId"), historicalLive.get("eventId"));
        assertEquals(live.get("sequence"), new JsonNumber(historicalLive.get("sequence").toString()));
    }

    @Test void liveSubscriptionNeverReceivesChatOrLossCapturedBeforeItsRegistration() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect();
        f.events.captureChat(ALICE, "old pending", false); f.events.captureFailed(ALICE);
        UUID id = f.subscribe(session, "@a", null);
        f.events.captureChat(ALICE, "new", false); f.drain();
        assertEquals("events.event", f.notification(session).get("method"));
        assertNull(session.reactorOutputHead());
        EventFailure loss = assertThrows(EventFailure.class, () -> f.poll(session, null, 100));
        assertEquals("capture-overflow", loss.details().get("reason"));
        f.events.execute(session, f.request("events.unsubscribe", "subscriptionId", id.toString()), WORLD);
    }

    @Test void explicitPlayerFilterResolvesNameOnceAndSelfRequiresExplicitExecutor() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect();
        assertFailure("MISSING_CONTEXT", () -> f.events.execute(session, f.subscribeRequest(UUID.randomUUID(), "@s", null), WORLD));
        assertFailure("INVALID_SELECTOR", () -> f.events.execute(session, f.subscribeRequest(UUID.randomUUID(), "@p", null), WORLD));
        f.subscribe(session, "Alice", null);
        f.names.put("Alice", BOB.uuid());
        f.events.captureChat(BOB, "Bob", false); f.events.captureChat(ALICE, "Alice", false); f.drain();
        Map<?, ?> event = (Map<?, ?>) ((Map<?, ?>) f.notification(session).get("params")).get("event");
        assertEquals("Alice", ((Map<?, ?>) event.get("data")).get("message"));
        assertNull(session.reactorOutputHead());
    }

    @Test void unsubscribePurgesPendingFramesAndUnknownSubscriptionHasTypedRejection() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect(); UUID id = f.subscribe(session, "@a", null);
        f.events.captureChat(ALICE, "queued", false); f.drain();
        assertEquals(1, session.eventOutputFrames());
        f.events.execute(session, f.request("events.unsubscribe", "subscriptionId", id.toString()), WORLD);
        assertEquals(0, session.eventOutputFrames());
        f.events.captureChat(ALICE, "after unsubscribe", false); f.drain(); assertNull(session.reactorOutputHead());
        assertFailure("SUBSCRIPTION_NOT_FOUND", () -> f.events.execute(session,
                f.request("events.unsubscribe", "subscriptionId", id.toString()), WORLD));
    }

    @Test void nativeCancellationAndUnicodeTruncationHaveExplicitSnapshotSemantics() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect();
        f.events.captureChat(ALICE, "cancelled", true);
        f.events.captureChat(ALICE, "\uD83D\uDE00".repeat(4097) + "\nline", false); f.drain();
        Map<String, Object> result = f.poll(session, null, 100);
        assertEquals(1, ((List<?>) result.get("events")).size());
        Map<?, ?> data = (Map<?, ?>) ((Map<?, ?>) ((List<?>) result.get("events")).getFirst()).get("data");
        String message = (String) data.get("message");
        assertEquals(4096, message.codePointCount(0, message.length()));
        assertEquals(true, data.get("truncated")); assertEquals(false, data.get("cancelled"));
        f.validateResult("events.pollEvents", result);
    }

    @Test void captureOverflowIsReportedToPullWithoutAnyLiveSubscription() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect();
        for (int i = 0; i < EventsService.MAX_INGRESS + 10; i++) f.events.captureChat(ALICE, "message", false);
        f.drain();
        EventFailure failure = assertThrows(EventFailure.class, () -> f.poll(session, null, 100));
        assertEquals("EVENT_HISTORY_LOST", failure.code()); assertEquals("capture-overflow", failure.details().get("reason"));
        Map<String, Object> cleared = f.events.execute(session, f.request("events.clearPending", "world", WORLD.key(), "eventType", null), WORLD);
        assertEquals(List.of(), messages(f.poll(session, cleared.get("cursor"), 100)));
    }

    @Test void newCaptureLossBreaksOnlyInterestedLiveSessionAndKeepsRpcOpen() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect(); Session independent = f.connect();
        UUID id = f.subscribe(session, "@a", null);
        f.events.captureFailed(ALICE); f.drain();
        Map<?, ?> overflow = f.notification(session);
        assertEquals("events.overflow", overflow.get("method"));
        assertEquals("capture", ((Map<?, ?>) overflow.get("params")).get("source"));
        assertTrue(session.isReady()); assertTrue(independent.isReady()); assertNull(independent.reactorOutputHead());
        f.events.captureChat(ALICE, "not delivered after break", false); f.drain(); assertNull(session.reactorOutputHead());
        f.events.execute(session, f.request("events.unsubscribe", "subscriptionId", id.toString()), WORLD);
    }

    @Test void liveQueueOverflowIsBoundedAndDoesNotCloseRpc() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect(); UUID id = f.subscribe(session, "@a", null);
        for (int i = 0; i < 520; i++) { f.events.captureChat(ALICE, "message", false); if (i % 32 == 0) f.events.tick(); }
        f.drain();
        assertTrue(session.isReady()); assertTrue(session.eventOutputFrames() <= 512);
        Map<?, ?> overflow = f.notification(session);
        assertEquals("events.overflow", overflow.get("method"));
        assertEquals("server", ((Map<?, ?>) overflow.get("params")).get("source"));
        f.events.execute(session, f.request("events.unsubscribe", "subscriptionId", id.toString()), WORLD);
    }

    @Test void recentDoesNotMoveClientCursorAndClearDoesNotEraseOtherSessionHistory() throws Exception {
        Fixture f = new Fixture(); Session first = f.connect(), second = f.connect();
        for (int i = 0; i < 4; i++) f.events.captureChat(ALICE, "message" + i, false);
        f.drain();
        Map<String, Object> recent = f.events.execute(first, f.request("events.getRecent", "world", WORLD.key(),
                "eventType", EventsService.CHAT_MESSAGE, "limit", 2, "cursor", null, "upperBound", null), WORLD);
        assertEquals(List.of("message2", "message3"), messages(recent)); f.validateResult("events.getRecent", recent);
        assertEquals(4, messages(f.poll(first, null, 100)).size());
        Map<String, Object> cleared = f.events.execute(first, f.request("events.clearPending", "world", WORLD.key(), "eventType", null), WORLD);
        assertEquals(0, messages(f.poll(first, cleared.get("cursor"), 100)).size());
        assertEquals(4, messages(f.poll(second, null, 100)).size());
    }

    @Test void invalidEpochFutureCursorAndFutureEventTypesAreRejected() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect();
        Map<String, Object> cursor = new HashMap<>((Map<String, Object>) f.poll(session, null, 100).get("nextCursor"));
        cursor.put("epoch", UUID.randomUUID().toString());
        assertFailure("INVALID_PARAMS", () -> f.poll(session, cursor, 100));
        Request valid = f.request("events.pollEvents", "world", WORLD.key(), "eventType", EventsService.CHAT_MESSAGE,
                "cursor", null, "limit", 100);
        Map<String, Object> params = new HashMap<>(valid.params());
        params.put("eventType", "future.unknown");
        assertFailure("INVALID_EVENT_TYPE", () -> f.events.execute(session, new Request(1L, valid.method(), params), WORLD));
        params.put("eventType", "imaginary");
        assertFailure("INVALID_EVENT_TYPE", () -> f.events.execute(session, new Request(1L, valid.method(), params), WORLD));
        Map<String, Object> future = new HashMap<>((Map<String, Object>) f.poll(session, null, 100).get("nextCursor"));
        future.put("sequence", 1L);
        assertFailure("INVALID_PARAMS", () -> f.poll(session, future, 100));
    }

    @Test void helloAbortDisconnectAndCloseReleaseCaptureInterest() throws Exception {
        Fixture f = new Fixture(); Session abandoned = f.newSession(); f.events.prepareHello(abandoned, WORLD); f.events.abortHello(abandoned);
        f.events.captureChat(ALICE, "after failed hello", false);
        Session session = f.connect(); f.drain(); assertEquals(List.of(), messages(f.poll(session, null, 100)));
        session.close(); f.events.tick();
        f.events.captureChat(ALICE, "after closed", false);
        Session later = f.connect(); f.drain(); assertEquals(List.of(), messages(f.poll(later, null, 100)));
        f.events.close(); f.events.captureChat(ALICE, "after service close", false);
        assertFailure("INVALID_STATE", () -> f.poll(later, null, 100));
    }

    @Test void asyncIngressDoesNotInvokeWorldOrPlayerDirectoryOrGameThreadBoundary() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Thread thread = new Thread(() -> { try { f.events.captureChat(ALICE, "async", false); } catch (Throwable error) { failure.set(error); } });
        thread.start(); thread.join(); assertNull(failure.get());
        f.drain(); assertEquals(List.of("async"), messages(f.poll(session, null, 100)));
    }

    @Test void subscriptionAndWorldLimitsStayBoundedAndReleasedSubscriptionsCanBeReplaced() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect();
        UUID first = f.subscribe(session, "@a", null);
        for (int i = 1; i < 32; i++) f.subscribe(session, "@a", null);
        assertFailure("LIMIT_EXCEEDED", () -> f.subscribe(session, "@a", null));
        f.events.execute(session, f.request("events.unsubscribe", "subscriptionId", first.toString()), WORLD);
        f.subscribe(session, "@a", null);
        for (int i = 1; i <= 8; i++) {
            WorldContext other = new WorldContext("other" + i, "example:other" + i, UUID.randomUUID(), -64, 320);
            f.loaded.put(other.key(), other);
            Request poll = f.request("events.pollEvents", "world", other.key(), "eventType", EventsService.CHAT_MESSAGE,
                    "cursor", null, "limit", 100);
            if (i < 8) assertEquals(List.of(), messages(f.events.execute(session, poll, WORLD)));
            else assertFailure("LIMIT_EXCEEDED", () -> f.events.execute(session, poll, WORLD));
        }
    }

    @Test void foreignOversizedMetadataCreatesVisibleCaptureLossAndNeverAbortsTick() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect();
        EventsService.PlayerSnapshot oversized = new EventsService.PlayerSnapshot(ALICE.uuid(), "A".repeat(40_000), 1, WORLD);
        f.events.captureChat(oversized, "foreign player metadata", false);
        assertDoesNotThrow(f::drain);
        EventFailure failure = assertThrows(EventFailure.class, () -> f.poll(session, null, 100));
        assertEquals("capture-overflow", failure.details().get("reason"));
    }

    @Test void recentBytePagesKeepFixedUpperBoundWhileNewMessagesArrive() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect();
        for (int i = 0; i < 3; i++) f.events.captureChat(ALICE, "\u0000".repeat(4096), false);
        f.drain();
        Map<String, Object> first = f.events.execute(session, f.request("events.getRecent", "world", WORLD.key(),
                "eventType", EventsService.CHAT_MESSAGE, "limit", 3, "cursor", null, "upperBound", null), WORLD);
        assertEquals(1, messages(first).size()); assertEquals(true, first.get("hasMore"));
        f.events.captureChat(ALICE, "later outside recent window", false); f.drain();
        Map<String, Object> second = f.events.execute(session, f.request("events.getRecent", "world", WORLD.key(),
                "eventType", EventsService.CHAT_MESSAGE, "limit", 2, "cursor", first.get("nextCursor"),
                "upperBound", first.get("upperBound")), WORLD);
        assertEquals(1, messages(second).size());
        Map<String, Object> third = f.events.execute(session, f.request("events.getRecent", "world", WORLD.key(),
                "eventType", EventsService.CHAT_MESSAGE, "limit", 1, "cursor", second.get("nextCursor"),
                "upperBound", first.get("upperBound")), WORLD);
        assertEquals(false, third.get("hasMore")); assertEquals(first.get("upperBound"), third.get("upperBound"));
        int count = 0;
        Object cursor = null;
        for (int pageNumber = 0; pageNumber < 4; pageNumber++) {
            Map<String, Object> page = f.poll(session, cursor, 100);
            count += messages(page).size(); cursor = page.get("nextCursor");
            if (!Boolean.TRUE.equals(page.get("hasMore"))) break;
        }
        assertEquals(4, count);
    }

    @Test void explicitWorldAliasRemainsPinnedAfterWorldRecreationAndBaselineAtFirstAccess() throws Exception {
        Fixture f = new Fixture(); Session session = f.connect();
        WorldContext other = new WorldContext("other", "example:other", UUID.randomUUID(), -64, 320);
        f.loaded.put(other.key(), other);
        Request poll = f.request("events.pollEvents", "world", other.key(), "eventType", EventsService.CHAT_MESSAGE, "cursor", null, "limit", 100);
        assertEquals(List.of(), messages(f.events.execute(session, poll, WORLD)));
        f.loaded.put(other.key(), new WorldContext(other.name(), other.key(), UUID.randomUUID(), -64, 320));
        assertFailure("WORLD_NOT_FOUND", () -> f.events.execute(session, poll, WORLD));
    }

    private static List<String> messages(Map<String, Object> result) {
        return ((List<Map<String, Object>>) result.get("events")).stream()
                .map(event -> (String) ((Map<?, ?>) event.get("data")).get("message")).toList();
    }
    private static void assertFailure(String code, Checked action) {
        EventFailure failure = assertThrows(EventFailure.class, action::run); assertEquals(code, failure.code());
    }
    @FunctionalInterface private interface Checked { Object run() throws Exception; }
    private static final class Fixture {
        final List<Session> sessions = new ArrayList<>();
        final Map<String, UUID> names = new HashMap<>(Map.of("Alice", ALICE.uuid(), "Bob", BOB.uuid()));
        final Map<String, WorldContext> loaded = new HashMap<>(Map.of(WORLD.name(), WORLD, WORLD.key(), WORLD));
        final Thread gameThread = Thread.currentThread();
        final EventsService events = new EventsService(name -> {
            assertSame(gameThread, Thread.currentThread()); return loaded.get(name);
        }, () -> List.copyOf(sessions), name -> { assertSame(gameThread, Thread.currentThread()); return names.get(name); },
                () -> assertSame(gameThread, Thread.currentThread()));
        Session newSession() { Session session = new Session(1024, 1024, () -> {}); sessions.add(session); return session; }
        Session connect() throws EventFailure {
            Session session = newSession(); events.prepareHello(session, WORLD); session.markReady(); events.commitHello(session); return session;
        }
        Request request(String method, Object... entries) {
            Map<String, Object> params = new LinkedHashMap<>();
            for (int i = 0; i < entries.length; i += 2) params.put((String) entries[i], entries[i + 1]);
            return JsonRpcCodec.decodeRequest(JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", 1, "method", method, "params", params)));
        }
        Request subscribeRequest(UUID id, Object players, Object executor) {
            return request("events.subscribe", "subscriptionId", id.toString(), "eventType", EventsService.CHAT_MESSAGE,
                    "world", WORLD.key(), "executor", executor, "players", players);
        }
        UUID subscribe(Session session, Object players, Object executor) throws EventFailure {
            UUID id = UUID.randomUUID(); Request request = subscribeRequest(id, players, executor);
            events.execute(session, request, WORLD); events.afterResponse(session, request, true); return id;
        }
        Map<String, Object> poll(Session session, Object cursor, int limit) throws EventFailure {
            return events.execute(session, request("events.pollEvents", "eventType", EventsService.CHAT_MESSAGE,
                    "world", WORLD.key(), "cursor", cursor, "limit", limit), WORLD);
        }
        void drain() { for (int i = 0; i < 200; i++) events.tick(); }
        Map<String, Object> notification(Session session) {
            ByteBuffer head = session.reactorOutputHead(); assertNotNull(head);
            byte[] frame = new byte[head.remaining()]; head.get(frame); session.reactorRemoveOutputHead(head);
            return JsonRpcCodec.decodeEventNotification(frame);
        }
        void validateResult(String method, Map<String, Object> result) {
            JsonRpcCodec.decodeResponse(JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", 1, "result", result)), 1L, method);
        }
    }
}
