package dev.minebridge.gameplay;

import dev.minebridge.blocks.BlockService;
import dev.minebridge.blocks.ChunkService;
import dev.minebridge.players.PlayerService;
import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.protocol.Response;
import dev.minebridge.session.Session;
import dev.minebridge.session.WorldContext;
import org.junit.jupiter.api.Test;

import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;

import static org.junit.jupiter.api.Assertions.*;

class GameplayJobManagerTest {
    static final WorldContext CONTEXT = new WorldContext("lesson", "minecraft:overworld", UUID.randomUUID(), -64, 320);
    static Session session() { Session value = new Session(128, 128, () -> {}); value.markReady(); return value; }
    static Map<String, Object> item(int amount, String name) {
        Map<String, Object> result = new LinkedHashMap<>(); result.put("key", "minecraft:iron_sword"); result.put("amount", amount);
        result.put("name", name); result.put("lore", null); return result;
    }
    static Request give(long id, Object targets, int amount) { return give(id, targets, item(amount, null)); }
    static Request give(long id, Object targets, Map<String, Object> item) {
        Map<String, Object> params = common(targets); params.put("item", item); params.put("overflow", "return");
        return request(id, "players.giveItem", params);
    }
    static Request effect(long id, Object targets) {
        Map<String, Object> params = common(targets); params.put("effect", Map.of("key", "minecraft:speed", "durationTicks", 200, "level", 2, "particles", false));
        return request(id, "effects.add", params);
    }
    static Map<String, Object> common(Object targets) {
        Map<String, Object> params = new LinkedHashMap<>(); params.put("world", "lesson"); params.put("executor", null); params.put("targets", targets); return params;
    }
    static Request spawn(long id) {
        Map<String, Object> params = new LinkedHashMap<>(); params.put("world", "lesson"); params.put("destinationWorld", null);
        params.put("position", List.of(16000.25, 80.5, 16000.75)); params.put("entity", Map.of("key", "minecraft:pig"));
        Map<String, Object> options = new LinkedHashMap<>(); for (String key : List.of("item", "block", "face", "owner")) options.put(key, null);
        params.put("options", options); return request(id, "entities.spawn", params);
    }
    static Request request(long id, String method, Map<String, Object> params) {
        byte[] frame = JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", id, "method", method, "params", params));
        return JsonRpcCodec.decodeRequest(Arrays.copyOf(frame, frame.length - 1));
    }
    static Response response(Session session, long id, String method) {
        ByteBuffer head = session.reactorOutputHead(); assertNotNull(head); byte[] data = new byte[head.remaining() - 1];
        head.get(data); head.get(); session.reactorRemoveOutputHead(head); return JsonRpcCodec.decodeResponse(data, id, method);
    }
    static class Target implements PlayerService.Target {
        final UUID uuid = UUID.randomUUID(); boolean living = true, valid = true;
        @Override public UUID uuid() { return uuid; }
        @Override public boolean living() { return living; }
        @Override public boolean valid() { return valid; }
    }
    static class Person extends Target implements PlayerService.Player {
        final String name; Person(String name) { this.name = name; }
        @Override public String name() { return name; }
        @Override public int entityId() { return 10; }
        @Override public boolean online() { return valid; }
        @Override public PlayerService.Position position() { return new PlayerService.Position("lesson", CONTEXT.uuid(), 0, 80, 0, 0, 0); }
        @Override public CompletionStage<Boolean> teleport(BlockService.WorldAccess world, double x, double y, double z, float yaw, float pitch) { throw new AssertionError(); }
    }
    static class World implements BlockService.WorldAccess {
        boolean loaded = true; int tickets, loads; final CompletableFuture<Boolean> loading = new CompletableFuture<>();
        @Override public String name() { return "lesson"; }
        @Override public UUID uuid() { return CONTEXT.uuid(); }
        @Override public int minY() { return -64; }
        @Override public int maxYExclusive() { return 320; }
        @Override public boolean insideBorder(double x, double z) { return true; }
        @Override public boolean isChunkLoaded(int x, int z) { return loaded; }
        @Override public CompletionStage<Boolean> loadChunk(int x, int z) { loads++; return loading; }
        @Override public void addChunkTicket(int x, int z) { tickets++; }
        @Override public void removeChunkTicket(int x, int z) { tickets--; }
        @Override public BlockService.BlockAccess blockAt(int x, int y, int z) { throw new AssertionError(); }
    }
    static class Harness implements PlayerService.Backend, BlockService.Backend, GameplayService.Backend {
        final Person a = new Person("Alpha"), b = new Person("Beta"); final Target mob = new Target(); final World world = new World();
        final BlockService blocks = new BlockService(this, () -> {}); final PlayerService players = new PlayerService(this, blocks, () -> {});
        final ChunkService chunks = new ChunkService(); final GameplayService service = new GameplayService(this, () -> {});
        final GameplayJobManager jobs = new GameplayJobManager(service, players, chunks);
        List<PlayerService.Target> selected = new ArrayList<>(List.of(a, b));
        int selections, steps, effectCalls, spawns; boolean throwMutation, badLocation, peaceful;
        @Override public PlayerService.Player findPlayer(String value) {
            return List.of(a, b).stream().filter(person -> person.name.equals(value) || person.uuid.toString().equals(value)).findFirst().orElse(null);
        }
        @Override public PlayerService.Target findTarget(UUID uuid) { return uuid.equals(mob.uuid) ? mob : findPlayer(uuid.toString()); }
        @Override public List<PlayerService.Target> select(String selector, PlayerService.Player executor) { selections++; return List.copyOf(selected); }
        @Override public BlockService.WorldAccess findWorld(String value) { return world; }
        @Override public BlockService.WorldAccess findWorld(UUID value) { return world; }
        @Override public BlockService.BlockMaterial resolveBlock(String key) { return null; }
        @Override public void broadcast(String value) { throw new AssertionError(); }
        record PreparedItem(GameplayService.Item item) implements GameplayService.PreparedItem {}
        @Override public GameplayService.PreparedItem prepareItem(GameplayService.Item item) { return new PreparedItem(item); }
        @Override public GameplayService.PreparedEffect prepareEffect(GameplayService.Effect effect) { return new GameplayService.PreparedEffect() {}; }
        @Override public GameplayService.PreparedSpawn prepareSpawn(String key, GameplayService.SpawnOptions options, BlockService.WorldAccess world) { return new GameplayService.PreparedSpawn() {}; }
        @Override public GameplayService.GiveOperation give(PlayerService.Player target, GameplayService.PreparedItem prepared, boolean drop) {
            GameplayService.Item item = ((PreparedItem) prepared).item();
            return new GameplayService.GiveOperation() {
                int count;
                @Override public void step(int pieces) { steps += pieces; count += pieces; if (throwMutation) throw new IllegalStateException("private"); }
                @Override public boolean done() { return count >= item.amount(); }
                @Override public GameplayService.GiveResult result() { return new GameplayService.GiveResult(true, null, item.amount(), item.amount(), List.of(), 0); }
            };
        }
        @Override public boolean addEffect(PlayerService.Target target, GameplayService.PreparedEffect effect) { effectCalls++; return true; }
        @Override public void validateSpawnLocation(BlockService.WorldAccess world, double x, double y, double z, GameplayService.PreparedSpawn spawn) throws GameplayFailure {
            if (badLocation) throw new GameplayFailure("INVALID_ENTITY_TYPE");
            if (peaceful) throw new GameplayFailure("PEACEFUL_SPAWN_BLOCKED");
        }
        @Override public GameplayService.Entity spawn(BlockService.WorldAccess world, double x, double y, double z, GameplayService.PreparedSpawn spawn) {
            spawns++; assertEquals(16000.25, x); return new GameplayService.Entity(UUID.randomUUID(), 99, "minecraft:pig", true);
        }
        void finish(Session session) { for (int count = 0; session.hasActiveOperation() && count < 10_000; count++) jobs.tick(); assertFalse(session.hasActiveOperation()); }
    }
    @Test void giveIsBoundedAndHoldsFifoWithoutReselecting() {
        Harness h = new Harness(); Session session = session(); h.jobs.submit(session, give(1, "@a", 100), CONTEXT);
        assertTrue(session.hasActiveOperation()); assertTrue(h.steps <= 32); assertNull(session.reactorOutputHead());
        h.finish(session); assertEquals(200, h.steps); assertEquals(1, h.selections);
        assertNull(response(session, 1, "players.giveItem").error()); assertEquals(0, h.jobs.activeJobs());
    }
    @Test void mixedTargetListFailsBeforeFirstInventoryMutation() {
        Harness h = new Harness(); h.selected.add(h.mob); Session session = session(); h.jobs.submit(session, give(1, "@e", 1), CONTEXT);
        assertEquals("INVALID_TARGET", response(session, 1, "players.giveItem").error().code()); assertEquals(0, h.steps);
    }
    @Test void effectsAllowLivingEntitiesButPrevalidateEntireSelection() {
        Harness h = new Harness(); h.selected.add(h.mob); Session session = session(); h.jobs.submit(session, effect(1, "@e"), CONTEXT); h.finish(session);
        assertNull(response(session, 1, "effects.add").error()); assertEquals(3, h.effectCalls);
        h.mob.living = false; h.jobs.submit(session, effect(2, "@e"), CONTEXT);
        assertEquals("INVALID_TARGET", response(session, 2, "effects.add").error().code()); assertEquals(3, h.effectCalls);
    }
    @Test void anEmptySelectionIsSuccessfulAndNeedsNoMutation() {
        Harness h = new Harness(); h.selected.clear(); Session session = session(); h.jobs.submit(session, give(1, "@a", 1), CONTEXT);
        assertNull(response(session, 1, "players.giveItem").error()); assertEquals(0, h.steps);
    }
    @Test void spawnWaitsForChunksAndDisconnectCancelsWithoutLateMutation() {
        Harness h = new Harness(); h.world.loaded = false; Session session = session(); h.jobs.submit(session, spawn(1), CONTEXT);
        assertTrue(session.hasActiveOperation()); assertEquals(1, h.world.loads); assertEquals(0, h.spawns);
        session.close(); h.jobs.tick(); h.world.loaded = true; h.world.loading.complete(true); h.jobs.tick();
        assertEquals(0, h.spawns); assertEquals(0, h.world.tickets); assertEquals(0, h.chunks.retainedChunks());
    }
    @Test void spawnAndShutdownShareAndReleaseTicketReferences() throws Exception {
        Harness h = new Harness(); ChunkService.Lease retained = h.chunks.acquire(h.world, 1000, 1000); assertTrue(retained.ready());
        Session session = session(); h.jobs.submit(session, spawn(1), CONTEXT); h.finish(session);
        assertNull(response(session, 1, "entities.spawn").error()); assertEquals(1, h.spawns); assertEquals(1, h.world.tickets);
        retained.close(); h.jobs.close(); assertEquals(0, h.world.tickets);
    }
    @Test void backingValidationFailsBeforeMutationWithKnownOutcome() {
        Harness h = new Harness(); h.badLocation = true; Session session = session(); h.jobs.submit(session, spawn(1), CONTEXT);
        Response result = response(session, 1, "entities.spawn"); assertEquals("INVALID_ENTITY_TYPE", result.error().code());
        assertEquals("not-applied", result.error().outcome()); assertEquals(0, h.spawns); assertEquals(0, h.world.tickets);
    }
    @Test void unexpectedExceptionAfterMutationBeginsIsUnknown() {
        Harness h = new Harness(); h.throwMutation = true; Session session = session(); h.jobs.submit(session, give(1, "Alpha", 1), CONTEXT); h.finish(session);
        Response result = response(session, 1, "players.giveItem"); assertEquals("INTERNAL_ERROR", result.error().code()); assertEquals("unknown", result.error().outcome());
    }
    @Test void peacefulRejectionAfterChunkLoadingIsKnownNotAppliedAndConnectionRemainsUsable() {
        Harness h = new Harness(); h.world.loaded = false; Session session = session();
        h.jobs.submit(session, spawn(1), CONTEXT);
        assertTrue(session.hasActiveOperation()); assertEquals(0, h.spawns);
        // Difficulty can change while a far chunk is being loaded.
        h.peaceful = true; h.world.loaded = true; h.world.loading.complete(true); h.finish(session);
        Response rejected = response(session, 1, "entities.spawn");
        assertEquals("PEACEFUL_SPAWN_BLOCKED", rejected.error().code());
        assertEquals("not-applied", rejected.error().outcome());
        assertEquals(0, h.spawns); assertEquals(0, h.world.tickets); assertEquals(0, h.jobs.activeJobs());
        h.peaceful = false; h.jobs.submit(session, spawn(2), CONTEXT); h.finish(session);
        assertNull(response(session, 2, "entities.spawn").error()); assertEquals(1, h.spawns);
    }
    @Test void oversizedLeftoverResponseIsRejectedBeforeMutation() {
        Harness h = new Harness(); for (int i = 0; i < 30; i++) h.selected.add(new Person("Other" + i));
        Map<String, Object> item = item(2304, "x".repeat(256)); item.put("lore", java.util.Collections.nCopies(16, "y".repeat(256)));
        Session session = session(); h.jobs.submit(session, give(1, "@a", item), CONTEXT);
        assertEquals("LIMIT_EXCEEDED", response(session, 1, "players.giveItem").error().code()); assertEquals(0, h.steps);
    }
    @Test void closingPendingGiveStopsFurtherStacksAndReleasesFifo() {
        Harness h = new Harness(); Session session = session(); h.jobs.submit(session, give(1, "@a", 2304), CONTEXT);
        assertTrue(session.hasActiveOperation()); int before = h.steps; h.jobs.close(); h.jobs.tick();
        assertEquals(before, h.steps); assertFalse(session.hasActiveOperation()); assertNull(session.reactorOutputHead());
    }
}
