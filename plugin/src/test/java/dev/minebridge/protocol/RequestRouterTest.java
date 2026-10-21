package dev.minebridge.protocol;

import dev.minebridge.config.BridgeConfig;
import dev.minebridge.blocks.BlockService;
import dev.minebridge.execution.ExecutionLimits;
import dev.minebridge.execution.OperationTrace;
import dev.minebridge.session.Session;
import dev.minebridge.session.SessionManager;
import dev.minebridge.session.WorldContext;
import dev.minebridge.transport.TransportLimits;
import org.junit.jupiter.api.Test;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Arrays;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.*;

class RequestRouterTest {
    private static final String TOKEN = "EXAMPLE-NOT-A-SECRET";
    private static final WorldContext LESSON = new WorldContext("lesson", UUID.randomUUID(), -12, 512);
    private static final WorldContext OTHER = new WorldContext("other", UUID.randomUUID(), 0, 256);

    @Test void validHelloPublishesImmutableActualWorldMetadataAndReadyState() {
        Harness h = new Harness();
        Session session = session();
        h.router.route(session, hello(1, TOKEN, null, "1", "0", "absolute"));
        assertTrue(session.isReady());
        assertSame(LESSON, h.sessions.context(session).orElseThrow());
        Response response = response(session, 1, "system.hello");
        assertNull(response.error());
        assertEquals(session.id().toString(), response.result().get("sessionId"));
        assertEquals("0.1.0-dev", response.result().get("pluginVersion"));
        assertEquals("26.2", response.result().get("serverVersion"));
        Map<?, ?> world = (Map<?, ?>) response.result().get("world");
        assertEquals("lesson", world.get("name"));
        assertEquals(LESSON.uuid().toString(), world.get("uuid"));
        assertEquals("-12", ((JsonNumber) world.get("minY")).text());
        assertEquals("512", ((JsonNumber) world.get("maxYExclusive")).text());
        assertEquals(1, h.sessions.readyCount());
    }

    @Test void twoConnectionsMayUseSameTokenAndSameRequestIdWithIndependentContexts() {
        Harness h = new Harness();
        Session a = session(), b = session();
        Request request = hello(1, TOKEN, null, "1", "0", "absolute");
        h.router.route(a, request);
        h.router.route(b, request);
        Response ar = response(a, 1, "system.hello"), br = response(b, 1, "system.hello");
        assertNotEquals(ar.result().get("sessionId"), br.result().get("sessionId"));
        assertEquals(2, h.sessions.readyCount());
        a.close();
        h.router.pruneClosed();
        assertEquals(1, h.sessions.readyCount());
        assertTrue(b.isReady());
    }

    @Test void separateConfigurationSelectsItsOwnDefaultWorld() {
        Harness h = new Harness("other", TOKEN, TransportLimits.defaults(), ExecutionLimits.defaults());
        Session session = session();
        h.router.route(session, hello(1, TOKEN, null, "1", "0", "absolute"));
        response(session, 1, "system.hello");
        assertSame(OTHER, h.sessions.context(session).orElseThrow());
    }

    @Test void explicitConfiguredWorldIsAccepted() {
        Harness h = new Harness();
        Session session = session();
        h.router.route(session, hello(1, TOKEN, "lesson", "1", "0", "absolute"));
        assertNotNull(response(session, 1, "system.hello").result());
        assertTrue(session.isReady());
    }

    @Test void wrongOrBlankTokenRejectsBeforeAnyWorldLookupAndNeverBecomesAnonymous() {
        for (String token : new String[] { "", " ", "wrong", TOKEN + " " }) {
            Harness h = new Harness();
            Session session = session();
            h.router.route(session, hello(1, token, null, "1", "0", "absolute"));
            assertError(session, 1, "AUTH_FAILED", true);
            assertEquals(0, h.lookups.get());
            assertEquals(0, h.sessions.readyCount());
        }
    }

    @Test void tokenComparisonPreservesConfiguredOuterSpacesExactly() {
        Harness h = new Harness("lesson", " " + TOKEN + " ", TransportLimits.defaults(), ExecutionLimits.defaults());
        Session rejected = session(), accepted = session();
        h.router.route(rejected, hello(1, TOKEN, null, "1", "0", "absolute"));
        assertError(rejected, 1, "AUTH_FAILED", true);
        h.router.route(accepted, hello(1, " " + TOKEN + " ", null, "1", "0", "absolute"));
        assertNotNull(response(accepted, 1, "system.hello").result());
    }

    @Test void missingTokenIsInvalidParamsAndClosesHello() {
        Harness h = new Harness();
        Session session = session();
        Map<String, Object> params = helloParams(TOKEN, null, "1", "0", "absolute");
        params.remove("token");
        h.router.route(session, request(1, "system.hello", params));
        assertError(session, 1, "INVALID_PARAMS", true);
        assertEquals(0, h.lookups.get());
    }

    @Test void invalidTokenPrecedesOtherHelloParameterValidation() {
        Harness h = new Harness();
        Session session = session();
        h.router.route(session, request(1, "system.hello", Map.of("token", "wrong")));
        assertError(session, 1, "AUTH_FAILED", true);
        assertEquals(0, h.lookups.get());
    }

    @Test void unsupportedMajorIncludingUnboundedIntegerRejectsWithoutOverflow() {
        for (String major : new String[] { "0", "-0", "2", "9".repeat(20_000) }) {
            Harness h = new Harness();
            Session session = session();
            h.router.route(session, hello(1, TOKEN, null, major, "0", "absolute"));
            assertError(session, 1, "PROTOCOL_VERSION", true);
            assertEquals(0, h.lookups.get());
        }
    }

    @Test void unboundedMinorAndNegativeZeroNegotiateServerMinorZero() {
        for (String minor : new String[] { "-0", "0", "1", "9".repeat(20_000) }) {
            Harness h = new Harness();
            Session session = session();
            h.router.route(session, hello(1, TOKEN, null, "1", minor, "absolute"));
            Map<?, ?> protocol = (Map<?, ?>) response(session, 1, "system.hello").result().get("protocol");
            assertEquals("0", ((JsonNumber) protocol.get("minor")).text());
            assertTrue(session.isReady());
        }
    }

    @Test void invalidIntegerLexemesRejectAsParamsBeforeVersionNegotiation() {
        for (String major : new String[] { "1.0", "1e0", "-1" }) {
            Harness h = new Harness();
            Session session = session();
            h.router.route(session, hello(1, TOKEN, null, major, "0", "absolute"));
            assertError(session, 1, "INVALID_PARAMS", true);
        }
    }

    @Test void unsupportedCoordinatesCloseHelloWithoutWorldLookup() {
        Harness h = new Harness();
        Session session = session();
        h.router.route(session, hello(1, TOKEN, null, "1", "0", "player"));
        assertError(session, 1, "UNSUPPORTED_FEATURE", true);
        assertEquals(0, h.lookups.get());
    }

    @Test void nonexistentWorldIsDistinguishedFromExistingForbiddenWorld() {
        Harness h = new Harness();
        Session missing = session(), forbidden = session();
        h.router.route(missing, hello(1, TOKEN, "missing", "1", "0", "absolute"));
        assertError(missing, 1, "WORLD_NOT_FOUND", true);
        h.router.route(forbidden, hello(1, TOKEN, "other", "1", "0", "absolute"));
        assertError(forbidden, 1, "PERMISSION_DENIED", true);
        assertEquals(0, h.sessions.readyCount());
    }

    @Test void disappearingConfiguredWorldNeverFallsBackToFirstLoadedWorld() {
        Harness h = new Harness("missing", TOKEN, TransportLimits.defaults(), ExecutionLimits.defaults());
        Session session = session();
        h.router.route(session, hello(1, TOKEN, null, "1", "0", "absolute"));
        assertError(session, 1, "WORLD_NOT_FOUND", true);
    }

    @Test void stateGateRejectsMalformedMutationBeforeItsSchema() {
        Harness h = new Harness();
        Session session = session();
        h.router.route(session, request(1, "blocks.set", Map.of()));
        assertError(session, 1, "NOT_READY", true);
        assertEquals(0, h.lookups.get());
    }

    @Test void unknownMethodBeforeHelloIsNotReady() {
        Harness h = new Harness();
        Session session = session();
        h.router.route(session, request(1, "future", Map.of()));
        assertError(session, 1, "NOT_READY", true);
    }

    @Test void repeatedMalformedHelloGetsStateErrorBeforeSchemaAndClearsQueuedWork() {
        Harness h = new Harness();
        Session session = ready(h);
        session.reactorOfferRequest(request(3, "future", Map.of()));
        h.router.route(session, request(2, "system.hello", Map.of()));
        assertError(session, 2, "INVALID_STATE", true);
        assertNull(session.pollRequest());
        assertEquals(0, h.sessions.readyCount());
    }

    @Test void validBlockOperationSucceedsOnlyAfterActualSetterReturns() {
        Harness h = new Harness();
        Session session = ready(h);
        h.backend.worlds.get("lesson").setterAction = () -> assertNull(session.reactorOutputHead(),
                "Successful response must not become visible while setter is executing");
        h.router.route(session, blockRequest(2, "lesson", "minecraft:stone"));
        Response response = response(session, 2, "blocks.set");
        assertEquals(Boolean.TRUE, response.result().get("applied"));
        assertEquals(1, h.backend.worlds.get("lesson").setterCalls);
        assertTrue(session.isReady());
        List<OperationTrace.Event> events = h.events();
        assertEquals(List.of(OperationTrace.Phase.APPLY_BEGIN, OperationTrace.Phase.APPLY_DONE,
                OperationTrace.Phase.ACK_ENQUEUED), events.stream().map(OperationTrace.Event::phase).toList());
        assertTrue(events.get(0).sequence() < events.get(1).sequence());
        assertTrue(events.get(1).sequence() < events.get(2).sequence());
        assertEquals(1L, events.get(0).applySequence());
        for (OperationTrace.Event event : events) {
            assertEquals(session.id(), event.sessionId());
            assertEquals(2L, event.requestId());
            assertEquals(1L, event.applySequence());
            assertEquals(Thread.currentThread().threadId(), event.threadId());
            assertTrue(event.primaryThread());
        }
    }

    @Test void domainFailureKeepsReadyAndNextValidRequestCanApply() {
        Harness h = new Harness();
        Session session = ready(h);
        TestWorld world = h.backend.worlds.get("lesson");
        world.loaded = false;
        h.router.route(session, blockRequest(2, "lesson", "minecraft:stone"));
        assertError(session, 2, "CHUNK_NOT_LOADED", false);
        List<OperationTrace.Event> failures = h.events();
        assertEquals(List.of(OperationTrace.Phase.ERROR), failures.stream().map(OperationTrace.Event::phase).toList());
        assertEquals("CHUNK_NOT_LOADED", failures.getFirst().errorCode());
        assertEquals("not-applied", failures.getFirst().outcome());
        assertEquals(0, world.setterCalls);
        world.loaded = true;
        h.router.route(session, blockRequest(3, "lesson", "minecraft:stone"));
        assertEquals(Boolean.TRUE, response(session, 3, "blocks.set").result().get("applied"));
        assertEquals(1, world.setterCalls);
    }

    @Test void unknownAndForbiddenRawWorldsCannotOverrideHelloWorld() {
        Harness h = new Harness();
        Session session = ready(h);
        h.router.route(session, blockRequest(2, "missing", "minecraft:stone"));
        assertError(session, 2, "WORLD_NOT_FOUND", false);
        h.router.route(session, blockRequest(3, "other", "minecraft:stone"));
        assertError(session, 3, "PERMISSION_DENIED", false);
        assertEquals(0, h.backend.worlds.get("lesson").setterCalls);
        assertEquals(0, h.backend.worlds.get("other").setterCalls);
        List<OperationTrace.Event> failures = h.events();
        assertEquals(List.of("WORLD_NOT_FOUND", "PERMISSION_DENIED"),
                failures.stream().map(OperationTrace.Event::errorCode).toList());
        assertTrue(failures.stream().allMatch(event -> event.worldUuid().equals(LESSON.uuid())));
    }

    @Test void schemaFailureTracesOnlyErrorAndNeverReachesBlockSetter() {
        Harness h = new Harness();
        Session session = ready(h);
        h.router.route(session, request(2, "blocks.set", Map.of("world", "lesson", "position", List.of(0, 80.5, 0),
                "block", Map.of("key", "minecraft:stone", "states", Map.of()))));
        assertError(session, 2, "INVALID_PARAMS", false);
        h.router.route(session, request(3, "blocks.set", Map.of("world", "lesson", "position", List.of(0, 80, 0),
                "block", Map.of("key", "minecraft:stone", "states", Map.of("axis", "x")))));
        assertError(session, 3, "UNSUPPORTED_FEATURE", false);
        assertEquals(0, h.backend.worlds.get("lesson").setterCalls);
        List<OperationTrace.Event> failures = h.events();
        assertEquals(List.of("INVALID_PARAMS", "UNSUPPORTED_FEATURE"),
                failures.stream().map(OperationTrace.Event::errorCode).toList());
        assertTrue(failures.stream().allMatch(event -> event.phase() == OperationTrace.Phase.ERROR));
    }

    @Test void setterFailureIsUnknownKeepsReadyAndReleasesActiveOperation() {
        Harness h = new Harness();
        Session session = ready(h);
        TestWorld world = h.backend.worlds.get("lesson");
        world.setterAction = () -> { throw new IllegalStateException(TOKEN); };
        h.router.route(session, blockRequest(2, "lesson", "minecraft:stone"));
        Response failure = response(session, 2, "blocks.set");
        assertEquals("INTERNAL_ERROR", failure.error().code());
        assertEquals("unknown", failure.error().outcome());
        assertEquals(1, world.setterCalls);
        assertTrue(session.isReady());
        List<OperationTrace.Event> failures = h.events();
        assertEquals(List.of(OperationTrace.Phase.APPLY_BEGIN, OperationTrace.Phase.ERROR),
                failures.stream().map(OperationTrace.Event::phase).toList());
        assertEquals("unknown", failures.getLast().outcome());
        assertFalse(failures.toString().contains(TOKEN));
        world.setterAction = () -> {};
        h.router.route(session, blockRequest(3, "lesson", "minecraft:stone"));
        assertEquals(Boolean.TRUE, response(session, 3, "blocks.set").result().get("applied"));
        assertEquals(2, world.setterCalls);
    }

    @Test void failureBeforeSetterIsNotAppliedWithoutApplyTrace() {
        Harness h = new Harness();
        Session session = ready(h);
        h.backend.worlds.get("lesson").blockAtAction = () -> { throw new IllegalStateException(TOKEN); };
        h.router.route(session, blockRequest(2, "lesson", "minecraft:stone"));
        assertError(session, 2, "INTERNAL_ERROR", false);
        List<OperationTrace.Event> failures = h.events();
        assertEquals(List.of(OperationTrace.Phase.ERROR), failures.stream().map(OperationTrace.Event::phase).toList());
        assertEquals("not-applied", failures.getFirst().outcome());
        assertEquals(0, h.backend.worlds.get("lesson").setterCalls);
    }

    @Test void closeBeforeBeginCancelsSetterAndPublishesNoResponse() {
        Harness h = new Harness();
        Session session = ready(h);
        h.backend.worlds.get("lesson").blockAtAction = session::close;
        h.router.route(session, blockRequest(2, "lesson", "minecraft:stone"));
        assertFalse(session.isOpen());
        assertEquals(0, h.backend.worlds.get("lesson").setterCalls);
        assertNull(session.reactorOutputHead());
        List<OperationTrace.Event> failures = h.events();
        assertEquals(List.of(OperationTrace.Phase.CANCELLED), failures.stream().map(OperationTrace.Event::phase).toList());
        assertEquals(0, failures.getFirst().applySequence());
    }

    @Test void closeInsideSetterAllowsStartedMutationToFinishButDoesNotPublishAck() {
        Harness h = new Harness();
        Session session = ready(h);
        session.reactorOfferRequest(blockRequest(3, "lesson", "minecraft:cobblestone"));
        h.backend.worlds.get("lesson").setterAction = session::close;
        h.router.route(session, blockRequest(2, "lesson", "minecraft:stone"));
        assertEquals(1, h.backend.worlds.get("lesson").setterCalls);
        assertFalse(session.isOpen());
        assertNull(session.reactorOutputHead());
        assertNull(session.pollRequest());
        assertEquals(List.of(OperationTrace.Phase.APPLY_BEGIN, OperationTrace.Phase.APPLY_DONE),
                h.events().stream().map(OperationTrace.Event::phase).toList());
    }

    @Test void fullOutputAfterApplicationDoesNotTraceAnAckOrPromiseRollback() {
        Harness h = new Harness();
        Session session = new Session(8, 1, () -> {});
        h.router.route(session, hello(1, TOKEN, null, "1", "0", "absolute"));
        response(session, 1, "system.hello");
        assertTrue(session.sendFrame(JsonRpcCodec.errorFrame(99L, "LIMIT_EXCEEDED", "not-applied")));
        h.router.route(session, blockRequest(2, "lesson", "minecraft:stone"));
        assertEquals(1, h.backend.worlds.get("lesson").setterCalls);
        assertFalse(session.isOpen());
        assertNull(session.reactorOutputHead());
        assertEquals(List.of(OperationTrace.Phase.APPLY_BEGIN, OperationTrace.Phase.APPLY_DONE),
                h.events().stream().map(OperationTrace.Event::phase).toList());
    }

    @Test void sameRequestIdsInTwoReadySessionsCorrelateTraceIndependently() {
        Harness h = new Harness();
        Session a = ready(h), b = ready(h);
        h.router.route(a, blockRequest(2, "lesson", "minecraft:stone"));
        h.router.route(b, blockRequest(2, "lesson", "minecraft:cobblestone"));
        assertEquals(Boolean.TRUE, response(a, 2, "blocks.set").result().get("applied"));
        assertEquals(Boolean.TRUE, response(b, 2, "blocks.set").result().get("applied"));
        List<OperationTrace.Event> events = h.events();
        assertEquals(6, events.size());
        assertEquals(a.id(), events.get(0).sessionId());
        assertEquals(b.id(), events.get(3).sessionId());
        assertTrue(events.get(0).applySequence() < events.get(3).applySequence());
        assertEquals(2L, events.get(0).requestId());
        assertEquals(2L, events.get(3).requestId());
    }

    @Test void ordinaryBadParamsAndUnknownMethodKeepReady() {
        Harness h = new Harness();
        Session session = ready(h);
        h.router.route(session, request(2, "blocks.set", Map.of()));
        assertError(session, 2, "INVALID_PARAMS", false);
        h.router.route(session, request(3, "future", Map.of()));
        assertError(session, 3, "METHOD_NOT_FOUND", false);
        assertTrue(session.isReady());
    }

    @Test void notificationNeverExecutesOrReplies() {
        Harness h = new Harness();
        Session session = session();
        h.router.route(session, new Request(null, "system.hello", helloParams(TOKEN, null, "1", "0", "absolute")));
        assertFalse(session.isOpen());
        assertNull(session.reactorOutputHead());
        assertEquals(0, h.lookups.get());
    }

    @Test void closedConnectionIsNeverRouted() {
        Harness h = new Harness();
        Session session = session();
        session.close();
        h.router.route(session, hello(1, TOKEN, null, "1", "0", "absolute"));
        assertNull(session.reactorOutputHead());
        assertEquals(0, h.lookups.get());
    }

    @Test void resolverFailureIsSanitizedAndHelloCloses() {
        SessionManager manager = new SessionManager(8);
        RequestRouter router = router(manager, name -> { throw new IllegalStateException(TOKEN); });
        Session session = session();
        router.route(session, hello(1, TOKEN, null, "1", "0", "absolute"));
        ByteBuffer head = session.reactorOutputHead().duplicate();
        byte[] raw = new byte[head.remaining()];
        head.get(raw);
        assertFalse(new String(raw, StandardCharsets.UTF_8).contains(TOKEN));
        assertError(session, 1, "INTERNAL_ERROR", true);
        assertFalse(router.toString().contains(TOKEN));
        assertEquals(0, manager.readyCount());
    }

    @Test void closeDuringWorldLookupDoesNotPublishContextOrHelloAck() {
        Session session = session();
        SessionManager manager = new SessionManager(8);
        RequestRouter router = router(manager, name -> { session.close(); return LESSON; });
        router.route(session, hello(1, TOKEN, null, "1", "0", "absolute"));
        assertFalse(session.isReady());
        assertEquals(0, manager.readyCount());
        assertNull(session.reactorOutputHead());
    }

    @Test void delayedWorldLookupCannotResurrectExpiredHandshakeBeforeReactorChecks() {
        AtomicLong now = new AtomicLong(100);
        Session session = new Session(8, 8, () -> { }, 100, Duration.ofNanos(10), now::get);
        SessionManager manager = new SessionManager(8);
        RequestRouter router = router(manager, name -> { now.set(110); return LESSON; });
        router.route(session, hello(1, TOKEN, null, "1", "0", "absolute"));
        assertFalse(session.isReady());
        assertFalse(session.isOpen());
        assertNull(session.reactorOutputHead());
        assertEquals(0, manager.readyCount());
    }

    @Test void fullOutputQueueCannotPublishSuccessfulHelloOrContext() {
        Harness h = new Harness();
        Session session = new Session(8, 1, () -> { });
        session.sendFrame(JsonRpcCodec.errorFrame(7L, "LIMIT_EXCEEDED", "not-applied"));
        h.router.route(session, hello(1, TOKEN, null, "1", "0", "absolute"));
        assertFalse(session.isReady());
        assertFalse(session.isOpen());
        assertNull(session.reactorOutputHead());
        assertEquals(0, h.sessions.readyCount());
    }

    @Test void helloReportsActualTransportAndExecutionLimitsIncludingFractionalDurations() {
        TransportLimits transport = new TransportLimits(3, 5, 6, Duration.ofMillis(1250),
                Duration.ofMillis(250), Duration.ofMillis(750));
        ExecutionLimits execution = new ExecutionLimits(7, 2, 1_500_000);
        Harness h = new Harness("lesson", TOKEN, transport, execution);
        Session session = session();
        h.router.route(session, hello(1, TOKEN, null, "1", "0", "absolute"));
        Map<?, ?> limits = (Map<?, ?>) response(session, 1, "system.hello").result().get("limits");
        for (Map.Entry<String, String> expected : Map.of("maxSessions", "3", "maxQueuedRequests", "5",
                "maxOutputFrames", "6", "maxOperationsPerTick", "7", "maxOperationsPerSessionPerTick", "2",
                "handshakeTimeoutSeconds", "1.25", "frameAssemblyTimeoutSeconds", "0.25",
                "writeTimeoutSeconds", "0.75", "executorBudgetMillis", "1.5").entrySet()) {
            assertEquals(expected.getValue(), ((JsonNumber) limits.get(expected.getKey())).text());
        }
    }

    private static RequestRouter router(SessionManager manager, RequestRouter.WorldLookup worlds) {
        return new RequestRouter(new BridgeConfig("127.0.0.1", 4711, "lesson", TOKEN), manager, worlds,
                "0.1.0-dev", "26.2", TransportLimits.defaults(), ExecutionLimits.defaults(),
                new BlockService(new TestBackend(), () -> {}), OperationTrace.disabled());
    }

    private static Session ready(Harness h) {
        Session session = session();
        h.router.route(session, hello(1, TOKEN, null, "1", "0", "absolute"));
        response(session, 1, "system.hello");
        assertTrue(session.isReady());
        return session;
    }

    private static Session session() { return new Session(8, 8, () -> { }); }

    private static Request hello(long id, String token, String world, String major, String minor, String coordinates) {
        return request(id, "system.hello", helloParams(token, world, major, minor, coordinates));
    }

    private static Map<String, Object> helloParams(String token, String world, String major, String minor, String coordinates) {
        Map<String, Object> params = new LinkedHashMap<>();
        params.put("protocol", Map.of("major", new JsonNumber(major), "minor", new JsonNumber(minor)));
        params.put("token", token);
        params.put("world", world);
        params.put("coordinates", coordinates);
        return params;
    }

    private static Request request(long id, String method, Map<String, Object> params) {
        byte[] frame = JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", id, "method", method, "params", params));
        return JsonRpcCodec.decodeEnvelope(Arrays.copyOf(frame, frame.length - 1));
    }

    private static Request blockRequest(long id, String world, String key) {
        return request(id, "blocks.set", Map.of("world", world, "position", List.of(0, 80, 0),
                "block", Map.of("key", key, "states", Map.of())));
    }

    private static Response response(Session session, long id, String method) {
        ByteBuffer head = session.reactorOutputHead();
        assertNotNull(head, "Expected response frame");
        byte[] frame = new byte[head.remaining()];
        head.duplicate().get(frame);
        session.reactorRemoveOutputHead(head);
        return JsonRpcCodec.decodeResponse(Arrays.copyOf(frame, frame.length - 1), id, method);
    }

    private static void assertError(Session session, long id, String code, boolean closing) {
        Response response = response(session, id, "system.hello");
        assertNotNull(response.error());
        assertEquals(code, response.error().code());
        assertEquals("not-applied", response.error().outcome());
        assertEquals(!closing, session.isOpen());
        if (closing) assertFalse(session.isReady());
    }

    private static final class Harness {
        final SessionManager sessions;
        final AtomicInteger lookups = new AtomicInteger();
        final TestBackend backend = new TestBackend();
        final OperationTrace trace = new OperationTrace(true, () -> true);
        final RequestRouter router;

        Harness() { this("lesson", TOKEN, TransportLimits.defaults(), ExecutionLimits.defaults()); }

        Harness(String defaultWorld, String token, TransportLimits transport, ExecutionLimits execution) {
            sessions = new SessionManager(transport.maxSessions());
            router = new RequestRouter(new BridgeConfig("127.0.0.1", 4711, defaultWorld, token), sessions,
                    name -> { lookups.incrementAndGet(); return Map.of("lesson", LESSON, "other", OTHER).get(name); },
                    "0.1.0-dev", "26.2", transport, execution,
                    new BlockService(backend, () -> {}), trace);
        }

        List<OperationTrace.Event> events() {
            List<OperationTrace.Event> events = new ArrayList<>();
            trace.drain(events::add);
            return events;
        }
    }

    /** Pure port fake: tests do not require Paper classes or a server at runtime. */
    private static final class TestBackend implements BlockService.Backend {
        final Map<String, TestWorld> worlds = new HashMap<>(Map.of("lesson", new TestWorld(LESSON),
                "other", new TestWorld(OTHER)));
        @Override public BlockService.WorldAccess findWorld(UUID uuid) {
            return worlds.values().stream().filter(world -> world.context.uuid().equals(uuid)).findFirst().orElse(null);
        }
        @Override public BlockService.WorldAccess findWorld(String name) { return worlds.get(name); }
        @Override public BlockService.BlockMaterial resolveBlock(String key) {
            return List.of("minecraft:stone", "minecraft:cobblestone", "minecraft:air").contains(key)
                    ? new BlockService.BlockMaterial() {} : null;
        }
    }

    private static final class TestWorld implements BlockService.WorldAccess {
        final WorldContext context;
        int setterCalls;
        boolean loaded = true;
        Runnable setterAction = () -> {};
        Runnable blockAtAction = () -> {};
        TestWorld(WorldContext context) { this.context = context; }
        @Override public String name() { return context.name(); }
        @Override public UUID uuid() { return context.uuid(); }
        @Override public int minY() { return context.minY(); }
        @Override public int maxYExclusive() { return context.maxYExclusive(); }
        @Override public boolean insideBorder(double x, double z) { return true; }
        @Override public boolean isChunkLoaded(int x, int z) { return loaded; }
        @Override public BlockService.BlockAccess blockAt(int x, int y, int z) {
            blockAtAction.run();
            return (material, physics) -> {
                assertTrue(physics);
                setterCalls++;
                setterAction.run();
            };
        }
    }
}
