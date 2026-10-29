package dev.minebridge.players;

import dev.minebridge.blocks.BlockService;
import dev.minebridge.session.WorldContext;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;

import static org.junit.jupiter.api.Assertions.*;

class PlayerServiceTest {
    static final WorldContext CONTEXT = new WorldContext("lesson", "minecraft:overworld", UUID.randomUUID(), -64, 320);
    static class World implements BlockService.WorldAccess {
        boolean loaded = true; int tickets; int loads;
        CompletableFuture<Boolean> loading = new CompletableFuture<>();
        @Override public String name() { return CONTEXT.name(); }
        @Override public UUID uuid() { return CONTEXT.uuid(); }
        @Override public int minY() { return -64; }
        @Override public int maxYExclusive() { return 320; }
        @Override public boolean insideBorder(double x, double z) { return Math.abs(x) < 100_000 && Math.abs(z) < 100_000; }
        @Override public boolean isChunkLoaded(int x, int z) { return loaded; }
        @Override public BlockService.BlockAccess blockAt(int x, int y, int z) { throw new AssertionError(); }
        @Override public CompletionStage<Boolean> loadChunk(int x, int z) { loads++; return loading; }
        @Override public void addChunkTicket(int x, int z) { tickets++; }
        @Override public void removeChunkTicket(int x, int z) { tickets--; }
    }
    static class Person implements PlayerService.Player {
        final UUID uuid = UUID.randomUUID(); final String name;
        UUID world = CONTEXT.uuid(); boolean online = true; int teleports;
        double x = 0, y = 70, z = 0;
        CompletableFuture<Boolean> pending = CompletableFuture.completedFuture(true);
        Person(String name) { this.name = name; }
        @Override public UUID uuid() { return uuid; }
        @Override public String name() { return name; }
        @Override public int entityId() { return 5; }
        @Override public boolean online() { return online; }
        @Override public PlayerService.Position position() { return new PlayerService.Position("lesson", world, x, y, z, 32, -10); }
        @Override public CompletionStage<Boolean> teleport(BlockService.WorldAccess world, double x, double y, double z, float yaw, float pitch) {
            teleports++; this.x = x; this.y = y; this.z = z; assertEquals(32, yaw); assertEquals(-10, pitch); return pending;
        }
    }
    static class Harness implements PlayerService.Backend, BlockService.Backend {
        final World world = new World(); final Person a = new Person("Alpha"), b = new Person("Beta");
        final BlockService blocks = new BlockService(this, () -> {});
        final PlayerService service = new PlayerService(this, blocks, () -> {});
        int selections; PlayerService.Player lastExecutor; String chat;
        List<PlayerService.Target> selected = new ArrayList<>(List.of(a, b));
        final UUID mobUuid = UUID.randomUUID();
        @Override public PlayerService.Player findPlayer(String value) {
            for (Person player : List.of(a, b)) if (player.uuid.toString().equalsIgnoreCase(value) || player.name.equalsIgnoreCase(value)) return player;
            return null;
        }
        @Override public List<PlayerService.Target> select(String selector, PlayerService.Player executor) {
            selections++; lastExecutor = executor;
            if (selector.contains("broken")) throw new IllegalArgumentException("private data");
            return selector.equals("@s") ? List.of(executor) : selected;
        }
        @Override public PlayerService.Target findTarget(UUID uuid) { return uuid.equals(mobUuid) ? () -> mobUuid : findPlayer(uuid.toString()); }
        @Override public BlockService.WorldAccess findWorld(String name) { return name.equals("lesson") || name.equals("minecraft:overworld") ? world : null; }
        @Override public BlockService.WorldAccess findWorld(UUID uuid) { return world.uuid().equals(uuid) ? world : null; }
        @Override public BlockService.BlockMaterial resolveBlock(String key) { return null; }
        @Override public void broadcast(String message) { chat = message; }
        PlayerService.Selection resolve(Object targets, String executor) throws Exception { return service.select(CONTEXT, "lesson", executor, targets); }
    }
    @Test void exactLookupAndExplicitUuidListsDeduplicateWithoutBindingContext() throws Exception {
        Harness h = new Harness(); assertSame(h.a, h.service.get("Alpha"));
        assertEquals(List.of(h.a, h.b), h.resolve(List.of(h.a.uuid.toString(), h.a.uuid.toString(), h.b.uuid.toString()), null).players());
        assertEquals(0, h.selections);
        assertEquals("MISSING_CONTEXT", assertThrows(PlayerFailure.class, () -> h.resolve("@s", null)).code());
    }
    @Test void noTargetAndEmptyExplicitListAreValidButPositionRequiresExactlyOne() throws Exception {
        Harness h = new Harness(); h.selected.clear();
        assertTrue(h.resolve("@a", null).players().isEmpty());
        assertTrue(h.resolve(List.of(), null).players().isEmpty());
        assertEquals("INVALID_TARGET", assertThrows(PlayerFailure.class, () -> h.service.getPosition(h.resolve("@a", null))).code());
        assertEquals("PLAYER_NOT_FOUND", assertThrows(PlayerFailure.class, () -> h.resolve("Nobody", null)).code());
    }
    @Test void selectionsUseVanillaOnceAndValidateWholeTypeSet() throws Exception {
        Harness h = new Harness(); assertEquals(2, h.resolve("@a", null).players().size()); assertEquals(1, h.selections);
        h.selected.add(UUID::randomUUID);
        assertEquals("INVALID_TARGET", assertThrows(PlayerFailure.class, () -> h.resolve("@e", null)).code());
        assertEquals(0, h.a.teleports);
        assertEquals("INVALID_SELECTOR", assertThrows(PlayerFailure.class, () -> h.resolve("@a[broken]", null)).code());
    }
    @Test void selfIsIndependentUuidAndMayBeInAnotherWorldButSpatialSelectionCannot() throws Exception {
        Harness h = new Harness();
        assertSame(h.a, h.resolve("@s", h.a.uuid.toString()).players().getFirst());
        assertSame(h.b, h.resolve("@s", h.b.uuid.toString()).players().getFirst());
        h.a.world = UUID.randomUUID(); assertSame(h.a, h.resolve("@s", h.a.uuid.toString()).players().getFirst());
        assertEquals("CONTEXT_WORLD_MISMATCH", assertThrows(PlayerFailure.class, () -> h.resolve("@p", h.a.uuid.toString())).code());
        h.a.online = false;
        assertEquals("PLAYER_NOT_FOUND", assertThrows(PlayerFailure.class, () -> h.resolve("@s", h.a.uuid.toString())).code());
    }
    @Test void originClassifierHonoursQuotedAndNestedValues() {
        for (String selector : List.of("@p", "@n", "@a[distance=..5]", "@a[x=1]", "@e[sort=nearest]", "@a[dx=5]", "@s[distance=2]", "@a[\"distance\"=..5]", "@e['sort'=nearest]")) {
            assertTrue(PlayerService.contextNeeded(selector).origin(), selector);
        }
        for (String selector : List.of("@a", "@r", "@e", "@s", "@a[name=\"distance=2,x=3\"]", "@e[nbt={CustomName:'x=3'}]", "@a[sort=random]")) {
            assertFalse(PlayerService.contextNeeded(selector).origin(), selector);
        }
        assertTrue(PlayerService.contextNeeded("@s").executor());
    }
    @Test void destinationPreservesFractionsAndChecksHeightBorderAndWorld() throws Exception {
        Harness h = new Harness(); assertSame(h.world, h.service.destination(CONTEXT, "lesson", null, .125, 72.5, -3.75));
        assertEquals("WORLD_NOT_FOUND", assertThrows(PlayerFailure.class, () -> h.service.destination(CONTEXT, "lesson", "none", 0, 70, 0)).code());
        assertEquals("COORDINATE_OUT_OF_BOUNDS", assertThrows(PlayerFailure.class, () -> h.service.destination(CONTEXT, "lesson", null, 0, 320, 0)).code());
        assertEquals("COORDINATE_OUT_OF_BOUNDS", assertThrows(PlayerFailure.class, () -> h.service.destination(CONTEXT, "lesson", null, 100_001, 70, 0)).code());
    }
    @Test void chatIsLiteralUnicode() { Harness h = new Harness(); h.service.broadcast("<red>Привет</red> /say hi\nline"); assertEquals("<red>Привет</red> /say hi\nline", h.chat); }
    @Test void nonplayerUuidAndExplicitMixedListRejectTypeBeforeMutation() {
        Harness h = new Harness();
        assertEquals("INVALID_TARGET", assertThrows(PlayerFailure.class, () -> h.resolve(h.mobUuid.toString(), null)).code());
        assertEquals("INVALID_TARGET", assertThrows(PlayerFailure.class, () -> h.resolve(List.of(h.a.uuid.toString(), h.mobUuid.toString()), null)).code());
        assertEquals(0, h.a.teleports);
    }
}
