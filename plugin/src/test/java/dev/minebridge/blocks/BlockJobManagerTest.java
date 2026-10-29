package dev.minebridge.blocks;

import dev.minebridge.execution.ExecutionLimits;
import dev.minebridge.execution.GameExecutor;
import dev.minebridge.execution.OperationTrace;
import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.JsonNumber;
import dev.minebridge.protocol.Request;
import dev.minebridge.protocol.Response;
import dev.minebridge.session.Session;
import dev.minebridge.session.WorldContext;
import org.junit.jupiter.api.Test;

import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.*;

class BlockJobManagerTest {
    private static final WorldContext CONTEXT = new WorldContext("lesson", "minecraft:overworld", UUID.randomUUID(), -64, 320);

    @Test void loadedSingleWritesCompleteInlineWithoutTickPerBlockRegression() {
        Harness h = new Harness();
        Session a = session();
        for (int i = 0; i < 100; i++) {
            h.jobs.submit(a, set(i + 1, i, 80, 0), CONTEXT);
            assertFalse(a.hasActiveOperation());
            assertEquals(Boolean.TRUE, response(a, i + 1, "blocks.set").result().get("applied"));
        }
        assertEquals(100, h.world.writes);
        assertEquals(0, h.jobs.retainedChunks());
        assertEquals(h.world.ticketAdds, h.world.ticketRemoves);
    }

    @Test void asyncChunkDedupKeepsOnlyItsSessionBusyAndPreservesFifo() {
        Harness h = new Harness();
        h.world.unloaded.add("0,0");
        Session a = session(), b = session();
        a.reactorOfferRequest(set(1, 0, 80, 0));
        a.reactorOfferRequest(set(2, 1, 80, 0));
        b.reactorOfferRequest(set(1, 32, 80, 0));
        GameExecutor executor = new GameExecutor(() -> List.of(a, b),
                (session, request) -> h.jobs.submit(session, request, CONTEXT), h.jobs::tick,
                () -> {}, ExecutionLimits.defaults());
        executor.run();
        assertTrue(a.hasActiveOperation());
        assertEquals(1, a.queuedRequests());
        assertEquals(Boolean.TRUE, response(b, 1, "blocks.set").result().get("applied"));
        assertEquals(1, h.world.writes);
        h.world.completeLoads();
        executor.run();
        assertEquals(Boolean.TRUE, response(a, 1, "blocks.set").result().get("applied"));
        assertEquals(Boolean.TRUE, response(a, 2, "blocks.set").result().get("applied"));
        assertEquals(3, h.world.writes);
        assertFalse(a.hasActiveOperation());
    }

    @Test void twoLoadsOfSameChunkShareFutureAndOneReferenceCountedTicket() {
        Harness h = new Harness();
        h.world.unloaded.add("0,0");
        Session a = session(), b = session();
        h.jobs.submit(a, set(1, 0, 80, 0), CONTEXT);
        h.jobs.submit(b, set(1, 1, 80, 0), CONTEXT);
        assertEquals(1, h.world.loads);
        assertEquals(1, h.jobs.retainedChunks());
        h.world.completeLoads();
        h.jobs.tick();
        assertNull(response(a, 1, "blocks.set").error());
        assertNull(response(b, 1, "blocks.set").error());
        assertEquals(1, h.world.ticketAdds);
        assertEquals(1, h.world.ticketRemoves);
        assertEquals(0, h.jobs.retainedChunks());
    }

    @Test void loadedThirtyCubeCompletesWithoutArtificialTicksAndPreservesEveryBlock() {
        Harness h = new Harness();
        // A normal fill must not become hundreds of ticks merely because the
        // per-block clock passes the former two-millisecond slice deadline.
        h.world.afterWrite = () -> h.now.addAndGet(100_000L);
        Session a = session();
        h.jobs.submit(a, region(1, "blocks.setRegion", List.of(0, 80, 0), List.of(29, 109, 29)), CONTEXT);
        assertFalse(a.hasActiveOperation());
        assertNull(response(a, 1, "blocks.setRegion").error());
        assertEquals(27_000, h.world.writes);
        assertEquals(27_000, h.world.values.size());
        for (int x = 0; x < 30; x++) for (int y = 80; y < 110; y++) for (int z = 0; z < 30; z++) {
            assertEquals("minecraft:stone", h.world.values.get(List.of(x, y, z)).key());
        }
        assertEquals(4, h.world.ticketAdds);
        assertEquals(h.world.ticketAdds, h.world.ticketRemoves);
        assertEquals(0, h.jobs.retainedChunks());
    }

    @Test void smallSwappedRegionPreservesStatesAcrossNegativeChunkBoundariesAndReleasesTickets() {
        Harness h = new Harness();
        Session a = session();
        Map<String, String> states = Map.of("axis", "x");
        h.jobs.submit(a, request(1, "blocks.setRegion", Map.of("world", "lesson", "from", List.of(20, 82, 20),
                "to", List.of(-2, 80, -2), "block", Map.of("key", "minecraft:oak_log", "states", states))), CONTEXT);
        assertFalse(a.hasActiveOperation());
        assertNull(response(a, 1, "blocks.setRegion").error());
        assertEquals(23 * 3 * 23, h.world.writes);
        assertEquals(23 * 3 * 23, h.world.values.size());
        assertTrue(h.world.values.containsKey(List.of(-2, 80, -2)));
        assertTrue(h.world.values.containsKey(List.of(20, 82, 20)));
        assertTrue(h.world.values.values().stream().allMatch(value -> value.key().equals("minecraft:oak_log")
                && value.states().equals(states)));
        assertEquals(9, h.world.ticketAdds);
        assertEquals(9, h.world.ticketRemoves);
        assertEquals(0, h.jobs.activeJobs());
        assertEquals(0, h.jobs.retainedChunks());
    }

    @Test void largeFillYieldsToAnotherSessionAndResumesWithoutMissingOrRepeatedCells() {
        Harness h = new Harness();
        Session a = session(), b = session();
        h.jobs.submit(a, region(1, "blocks.setRegion", List.of(0, 80, 0), List.of(63, 95, 63)), CONTEXT);
        assertTrue(a.hasActiveOperation());
        assertTrue(h.world.writes > 0 && h.world.writes < 65_536);
        h.jobs.submit(b, set(1, 100, 81, 100), CONTEXT);
        assertNull(response(b, 1, "blocks.set").error());
        for (int tick = 0; tick < 100 && a.hasActiveOperation(); tick++) h.jobs.tick();
        assertFalse(a.hasActiveOperation());
        assertNull(response(a, 1, "blocks.setRegion").error());
        assertEquals(65_537, h.world.writes);
        assertEquals(65_537, h.world.values.size());
        assertEquals("minecraft:stone", h.world.values.get(List.of(63, 95, 63)).key());
        assertEquals(h.world.ticketAdds, h.world.ticketRemoves);
        assertEquals(0, h.jobs.retainedChunks());
    }

    @Test void normalFillStillAwaitsChunkLoadBeforeAcknowledgingAndReleasesAllTickets() {
        Harness h = new Harness();
        h.world.unloaded.add("0,0");
        Session a = session();
        h.jobs.submit(a, region(1, "blocks.setRegion", List.of(0, 80, 0), List.of(29, 109, 29)), CONTEXT);
        assertTrue(a.hasActiveOperation());
        assertEquals(0, h.world.writes);
        assertNull(a.reactorOutputHead());
        h.world.completeLoads();
        h.jobs.tick();
        assertFalse(a.hasActiveOperation());
        assertNull(response(a, 1, "blocks.setRegion").error());
        assertEquals(27_000, h.world.writes);
        assertEquals(h.world.ticketAdds, h.world.ticketRemoves);
        assertEquals(0, h.jobs.retainedChunks());
    }

    @Test void conflictingWritesAreRejectedWhileReadAndOtherRegionContinue() {
        Harness h = new Harness();
        Session a = session(), b = session();
        h.jobs.submit(a, region(1, "blocks.setRegion", List.of(0, 80, 0), List.of(63, 95, 63)), CONTEXT);
        h.jobs.submit(b, set(1, 30, 81, 30), CONTEXT);
        assertEquals("REGION_BUSY", response(b, 1, "blocks.set").error().code());
        h.jobs.submit(b, request(2, "blocks.get", Map.of("world", "lesson", "position", List.of(0, 80, 0))), CONTEXT);
        assertNull(response(b, 2, "blocks.get").error());
        h.jobs.submit(b, set(3, 100, 81, 100), CONTEXT);
        assertNull(response(b, 3, "blocks.set").error());
        a.close(); h.jobs.tick();
        assertEquals(0, h.jobs.activeJobs());
        h.jobs.submit(b, set(4, 30, 81, 30), CONTEXT);
        assertNull(response(b, 4, "blocks.set").error());
        assertEquals(0, h.jobs.retainedChunks());
    }

    @Test void pagedReadsReturnExactCoordinateOrderAndCanonicalStates() {
        Harness h = new Harness();
        Session a = session();
        Map<String, String> states = Map.of("axis", "x");
        h.world.values.put(List.of(-1, 80, -1), new BlockService.BlockValue("minecraft:oak_log", states));
        h.jobs.submit(a, request(1, "blocks.get", Map.of("world", "lesson", "position", List.of(-1, 80, -1))), CONTEXT);
        Map<?, ?> block = (Map<?, ?>) response(a, 1, "blocks.get").result().get("block");
        assertEquals(states, block.get("states"));
        h.jobs.submit(a, request(2, "blocks.getRegion", Map.of("world", "lesson", "from", List.of(1, 81, 1),
                "to", List.of(-1, 80, -1), "offset", 0, "limit", 10)), CONTEXT);
        Map<String, Object> page = response(a, 2, "blocks.getRegion").result();
        List<?> values = (List<?>) page.get("blocks");
        assertEquals(10, values.size());
        assertEquals("18", ((JsonNumber) page.get("total")).text());
        assertEquals("10", ((JsonNumber) page.get("nextOffset")).text());
        for (int i = 0; i < 10; i++) {
            List<?> position = (List<?>) ((Map<?, ?>) values.get(i)).get("position");
            assertEquals(List.of("" + (-1 + i % 3), "" + (80 + i / 9), "" + (-1 + i / 3 % 3)),
                    position.stream().map(value -> ((JsonNumber) value).text()).toList());
        }
        h.jobs.submit(a, request(3, "blocks.getRegion", Map.of("world", "lesson", "from", List.of(-1, 80, -1),
                "to", List.of(1, 81, 1), "offset", 10, "limit", 64)), CONTEXT);
        Map<String, Object> last = response(a, 3, "blocks.getRegion").result();
        assertEquals(8, ((List<?>) last.get("blocks")).size());
        assertNull(last.get("nextOffset"));
    }

    @Test void oversizedInt32RegionCannotOverflowItsVolumeOrStartLoading() {
        Harness h = new Harness();
        Session a = session();
        h.jobs.submit(a, region(1, "blocks.setRegion", List.of(Integer.MIN_VALUE, Integer.MIN_VALUE, Integer.MIN_VALUE),
                List.of(Integer.MAX_VALUE, Integer.MAX_VALUE, Integer.MAX_VALUE)), CONTEXT);
        assertEquals("LIMIT_EXCEEDED", response(a, 1, "blocks.setRegion").error().code());
        assertEquals(0, h.world.loads);
        assertEquals(0, h.world.writes);
        assertFalse(a.hasActiveOperation());
    }

    @Test void partialSetterFailureIsUnknownAndReleasesReservationAndTicket() {
        Harness h = new Harness();
        h.world.failAtWrite = 300;
        Session a = session(), b = session();
        h.jobs.submit(a, region(1, "blocks.setRegion", List.of(0, 80, 0), List.of(30, 82, 30)), CONTEXT);
        for (int tick = 0; tick < 10 && a.hasActiveOperation(); tick++) h.jobs.tick();
        Response failure = response(a, 1, "blocks.setRegion");
        assertEquals("INTERNAL_ERROR", failure.error().code());
        assertEquals("unknown", failure.error().outcome());
        assertEquals(300, h.world.writes);
        assertEquals(0, h.jobs.retainedChunks());
        assertFalse(a.hasActiveOperation());
        h.jobs.submit(b, set(1, 0, 80, 0), CONTEXT);
        assertNull(response(b, 1, "blocks.set").error());
    }

    @Test void closedConnectionAndShutdownCancelPendingLoadWithoutLateMutation() {
        for (boolean shutdown : List.of(false, true)) {
            Harness h = new Harness();
            h.world.unloaded.add("0,0");
            Session a = session();
            h.jobs.submit(a, set(1, 0, 80, 0), CONTEXT);
            assertTrue(a.hasActiveOperation());
            if (shutdown) h.jobs.close(); else { a.close(); h.jobs.tick(); }
            h.world.completeLoads();
            h.jobs.tick();
            assertEquals(0, h.world.writes);
            assertEquals(0, h.world.ticketAdds);
            assertEquals(0, h.jobs.retainedChunks());
            assertFalse(a.hasActiveOperation());
        }
    }

    @Test void livePendingJobPulsesWhileLoadingAndFailedLoadDoesNotMutate() {
        Harness h = new Harness();
        h.world.unloaded.add("0,0");
        Session a = session();
        h.jobs.submit(a, set(17, 0, 80, 0), CONTEXT);
        h.now.set(500_000_000L);
        h.jobs.tick();
        byte[] notification = take(a);
        String text = new String(notification, java.nio.charset.StandardCharsets.UTF_8);
        assertTrue(text.contains("\"method\":\"system.progress\""));
        assertTrue(text.contains("\"requestId\":17"));
        h.world.pending.values().forEach(future -> future.completeExceptionally(new IllegalStateException("private")));
        h.jobs.tick();
        Response failure = response(a, 17, "blocks.set");
        assertEquals("CHUNK_LOAD_FAILED", failure.error().code());
        assertEquals("not-applied", failure.error().outcome());
        assertEquals(0, h.world.writes);
        assertEquals(0, h.jobs.retainedChunks());
    }

    private static Session session() { Session s = new Session(128, 128, () -> {}); s.markReady(); return s; }
    private static Request set(long id, int x, int y, int z) {
        return request(id, "blocks.set", Map.of("world", "lesson", "position", List.of(x, y, z),
                "block", Map.of("key", "minecraft:stone", "states", Map.of())));
    }
    private static Request region(long id, String method, List<Integer> from, List<Integer> to) {
        return request(id, method, Map.of("world", "lesson", "from", from, "to", to,
                "block", Map.of("key", "minecraft:stone", "states", Map.of())));
    }
    private static Request request(long id, String method, Map<String, Object> params) {
        byte[] frame = JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", id, "method", method, "params", params));
        return JsonRpcCodec.decodeRequest(Arrays.copyOf(frame, frame.length - 1));
    }
    private static byte[] take(Session session) {
        ByteBuffer head = session.reactorOutputHead();
        assertNotNull(head, "Expected response");
        byte[] result = new byte[head.remaining() - 1];
        head.duplicate().get(result);
        session.reactorRemoveOutputHead(head);
        return result;
    }
    private static Response response(Session session, long id, String method) { return JsonRpcCodec.decodeResponse(take(session), id, method); }

    private record Material(String key, Map<String, String> states) implements BlockService.BlockMaterial {}
    private static final class Harness {
        final FakeWorld world = new FakeWorld();
        final AtomicLong now = new AtomicLong();
        final BlockService service = new BlockService(new BlockService.Backend() {
            @Override public BlockService.WorldAccess findWorld(UUID uuid) { return CONTEXT.uuid().equals(uuid) ? world : null; }
            @Override public BlockService.WorldAccess findWorld(String name) { return CONTEXT.name().equals(name) ? world : null; }
            @Override public BlockService.BlockMaterial resolveBlock(String key) { return new Material(key, Map.of()); }
            @Override public BlockService.BlockMaterial resolveBlock(String key, Map<String, String> states) { return new Material(key, states); }
        }, () -> {});
        final BlockJobManager jobs = new BlockJobManager(service, OperationTrace.disabled(), now::get);
    }
    private static final class FakeWorld implements BlockService.WorldAccess {
        final Map<List<Integer>, BlockService.BlockValue> values = new HashMap<>();
        final Set<String> unloaded = new HashSet<>();
        final Map<String, CompletableFuture<Boolean>> pending = new HashMap<>();
        int loads, writes, ticketAdds, ticketRemoves, failAtWrite = -1;
        Runnable afterWrite = () -> {};
        @Override public String name() { return CONTEXT.name(); }
        @Override public UUID uuid() { return CONTEXT.uuid(); }
        @Override public int minY() { return -64; }
        @Override public int maxYExclusive() { return 320; }
        @Override public boolean insideBorder(double x, double z) { return true; }
        @Override public boolean isChunkLoaded(int x, int z) { return !unloaded.contains(x + "," + z); }
        @Override public CompletionStage<Boolean> loadChunk(int x, int z) { loads++; return pending.computeIfAbsent(x + "," + z, key -> new CompletableFuture<>()); }
        @Override public void addChunkTicket(int x, int z) { ticketAdds++; }
        @Override public void removeChunkTicket(int x, int z) { ticketRemoves++; }
        @Override public BlockService.BlockValue readBlock(int x, int y, int z) {
            return values.getOrDefault(List.of(x, y, z), new BlockService.BlockValue("minecraft:air", Map.of()));
        }
        @Override public BlockService.BlockAccess blockAt(int x, int y, int z) {
            return (material, physics) -> {
                assertTrue(physics);
                writes++;
                Material value = (Material) material;
                values.put(List.of(x, y, z), new BlockService.BlockValue(value.key(), value.states()));
                afterWrite.run();
                if (writes == failAtWrite) throw new IllegalStateException("private");
            };
        }
        void completeLoads() { unloaded.clear(); pending.values().forEach(future -> future.complete(true)); }
    }
}
