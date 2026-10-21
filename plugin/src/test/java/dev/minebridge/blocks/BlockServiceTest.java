package dev.minebridge.blocks;

import dev.minebridge.session.WorldContext;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.*;

class BlockServiceTest {
    private static final UUID WORLD_ID = UUID.fromString("550e8400-e29b-41d4-a716-446655440000");
    private static final WorldContext CONTEXT = new WorldContext("lesson", WORLD_ID, -64, 320);
    private static final BlockService.BlockMaterial STONE = new BlockService.BlockMaterial() {};

    @Test void checksAndSetterAreOrderedWithSuccessTraceAfterActualSetter() throws Exception {
        Harness h = new Harness();
        h.set(-1, 80, -17);
        assertEquals(List.of("guard", "world.uuid", "identity.uuid", "identity.name", "minY", "maxY",
                "border", "material", "loaded", "blockAt", "beforeSetter", "setter", "afterSetter"), h.events);
        assertEquals(-1, h.world.chunkX);
        assertEquals(-2, h.world.chunkZ);
        assertSame(STONE, h.world.lastMaterial);
        assertTrue(h.world.physics);
        assertEquals(1, h.world.setterCalls);
    }

    @Test void negativeAndExtremeCoordinatesUseFloorDivisionRatherThanTruncation() throws Exception {
        for (int x : new int[] { Integer.MIN_VALUE, -17, -16, -15, -1, 0, 15, 16, Integer.MAX_VALUE }) {
            Harness h = new Harness();
            h.set(x, 80, x);
            assertEquals(Math.floorDiv(x, 16), h.world.chunkX, "chunkX for " + x);
            assertEquals(Math.floorDiv(x, 16), h.world.chunkZ, "chunkZ for " + x);
            assertEquals((double) x + 0.5d, h.world.centerX);
            assertEquals((double) x + 0.5d, h.world.centerZ);
        }
    }

    @Test void actualWorldBoundsAreUsedInsteadOfStaleHelloMetadata() throws Exception {
        Harness h = new Harness();
        h.world.min = 20;
        h.world.max = 30;
        h.set(0, 20, 0);
        h.set(0, 29, 0);
        assertEquals(2, h.world.setterCalls);
        for (int y : new int[] { 19, 30, -64, 319 }) {
            h.events.clear();
            assertFailure("COORDINATE_OUT_OF_BOUNDS", "not-applied", () -> h.set(0, y, 0));
            assertFalse(h.events.contains("loaded"));
            assertFalse(h.events.contains("blockAt"));
        }
        assertEquals(2, h.world.setterCalls);
    }

    @Test void borderUsesBlockCentersAndRejectsBeforeAnyBlockAccess() {
        Harness h = new Harness();
        h.world.inside = false;
        assertFailure("COORDINATE_OUT_OF_BOUNDS", "not-applied", () -> h.set(-1, 80, 5));
        assertEquals(-0.5d, h.world.centerX);
        assertEquals(5.5d, h.world.centerZ);
        assertFalse(h.events.contains("material"));
        assertFalse(h.events.contains("loaded"));
        assertFalse(h.events.contains("blockAt"));
    }

    @Test void unloadedChunkNeverReachesGetBlockAtOrSetter() {
        Harness h = new Harness();
        h.world.loaded = false;
        assertFailure("CHUNK_NOT_LOADED", "not-applied", () -> h.set(-1, 80, -17));
        assertTrue(h.events.contains("loaded"));
        assertFalse(h.events.contains("blockAt"));
        assertFalse(h.events.contains("beforeSetter"));
        assertEquals(0, h.world.setterCalls);
    }

    @Test void unknownRequestedWorldIsNotFoundWithoutResolvingSessionWorldOrBlock() {
        Harness h = new Harness();
        assertFailure("WORLD_NOT_FOUND", "not-applied", () -> h.set("missing", "minecraft:stone"));
        assertEquals(List.of("guard", "world.name"), h.events);
    }

    @Test void existingOtherRequestedWorldIsDeniedWithoutBlockAccess() {
        Harness h = new Harness();
        h.backend.byName.put("other", new FakeWorld(h.events));
        assertFailure("PERMISSION_DENIED", "not-applied", () -> h.set("other", "minecraft:stone"));
        assertEquals(List.of("guard", "world.name"), h.events);
    }

    @Test void unloadedSelectedWorldNeverRebindsToSameNameReplacement() {
        Harness h = new Harness();
        h.backend.byId.clear();
        FakeWorld replacement = new FakeWorld(h.events);
        replacement.id = UUID.randomUUID();
        h.backend.byName.put("lesson", replacement);
        assertFailure("WORLD_NOT_FOUND", "not-applied", () -> h.set(0, 80, 0));
        assertEquals(List.of("guard", "world.uuid"), h.events);
        assertEquals(0, replacement.setterCalls);
    }

    @Test void selectedWorldIdentityIsRecheckedEvenIfBackendReturnsWrongWorld() {
        Harness h = new Harness();
        h.world.id = UUID.randomUUID();
        assertFailure("WORLD_NOT_FOUND", "not-applied", () -> h.set(0, 80, 0));
        assertFalse(h.events.contains("minY"));
        assertFalse(h.events.contains("blockAt"));
    }

    @Test void renamedSelectedWorldIsRejectedRatherThanFollowingItsUuid() {
        Harness h = new Harness();
        h.world.name = "renamed";
        assertFailure("WORLD_NOT_FOUND", "not-applied", () -> h.set(0, 80, 0));
        assertFalse(h.events.contains("minY"));
    }

    @Test void noncanonicalBlockKeysNeverReachRegistryOrChunk() {
        for (String key : new String[] { "stone", "MINECRAFT:STONE", "minecraft:stone[axis=x]", "minecraft:stone!", " minecraft:stone", "minecraft:" }) {
            Harness h = new Harness();
            assertFailure("INVALID_BLOCK", "not-applied", () -> h.set("lesson", key));
            assertFalse(h.events.contains("material"));
            assertFalse(h.events.contains("loaded"));
            assertEquals(0, h.world.setterCalls);
        }
    }

    @Test void MissingOrNonBlockMaterialNeverFallsBackToAir() {
        for (String key : new String[] { "minecraft:not_a_registered_block", "minecraft:iron_sword", "other:stone" }) {
            Harness h = new Harness();
            assertFailure("INVALID_BLOCK", "not-applied", () -> h.set("lesson", key));
            assertTrue(h.events.contains("material"));
            assertFalse(h.events.contains("loaded"));
            assertEquals(0, h.world.setterCalls);
        }
    }

    @Test void sameMaterialNoOpStillInvokesSetterAndSucceedsEachTime() throws Exception {
        Harness h = new Harness();
        h.set(0, 80, 0);
        h.set(0, 80, 0);
        assertEquals(2, h.world.setterCalls);
        assertEquals(2, h.events.stream().filter("afterSetter"::equals).count());
    }

    @Test void setterExceptionHasUnknownOutcomeEvenIfWorldChangedBeforeThrowing() {
        Harness h = new Harness();
        h.world.setterThrows = true;
        BlockFailure failure = assertFailure("INTERNAL_ERROR", "unknown", () -> h.set(0, 80, 0));
        assertEquals(1, h.world.setterCalls);
        assertSame(STONE, h.world.lastMaterial);
        assertFalse(h.events.contains("afterSetter"));
        assertNull(failure.getCause());
        assertFalse(failure.toString().contains("backend-secret"));
        assertFalse(failure.getMessage().contains("backend-secret"));
    }

    @Test void backendFailuresBeforeSetterAreNotAppliedAndSanitized() {
        for (String failing : new String[] { "world.uuid", "identity.uuid", "identity.name", "minY", "maxY", "border", "material", "loaded", "blockAt" }) {
            Harness h = new Harness();
            h.backend.failingEvent = failing;
            BlockFailure failure = assertFailure("INTERNAL_ERROR", "not-applied", () -> h.set(0, 80, 0));
            assertEquals(0, h.world.setterCalls, failing);
            assertNull(failure.getCause());
            assertFalse(failure.toString().contains("backend-secret"));
        }
    }

    @Test void beforeSetterObserverFailureDoesNotPretendSetterStarted() {
        Harness h = new Harness();
        BlockService.SetterObserver broken = new BlockService.SetterObserver() {
            @Override public void beforeSetter() { throw new IllegalStateException("backend-secret"); }
            @Override public void afterSetter() { fail("Setter must not finish"); }
        };
        assertFailure("INTERNAL_ERROR", "not-applied", () ->
                h.service.set(CONTEXT, "lesson", 0, 80, 0, "minecraft:stone", broken));
        assertEquals(0, h.world.setterCalls);
    }

    @Test void afterSetterObserverFailureCannotPromiseRollback() {
        Harness h = new Harness();
        BlockService.SetterObserver broken = new BlockService.SetterObserver() {
            @Override public void beforeSetter() {}
            @Override public void afterSetter() { throw new IllegalStateException("backend-secret"); }
        };
        assertFailure("INTERNAL_ERROR", "unknown", () ->
                h.service.set(CONTEXT, "lesson", 0, 80, 0, "minecraft:stone", broken));
        assertEquals(1, h.world.setterCalls);
    }

    @Test void offThreadInvocationFailsBeforeEvenLookingUpWorld() {
        Harness h = new Harness();
        AtomicBoolean guardCalled = new AtomicBoolean();
        BlockService offThread = new BlockService(h.backend, () -> {
            guardCalled.set(true);
            throw new IllegalStateException("Game thread required");
        });
        assertThrows(IllegalStateException.class, () -> offThread.set(CONTEXT, "lesson", 0, 80, 0,
                "minecraft:stone", BlockService.SetterObserver.NONE));
        assertTrue(guardCalled.get());
        assertTrue(h.events.isEmpty());
    }

    @Test void optionalNoOpObserverDoesNotChangeMutation() throws Exception {
        Harness h = new Harness();
        h.service.set(CONTEXT, "lesson", 0, 80, 0, "minecraft:stone", BlockService.SetterObserver.NONE);
        assertEquals(1, h.world.setterCalls);
        assertTrue(h.world.physics);
    }

    @FunctionalInterface private interface Operation { void run() throws BlockFailure; }

    private static BlockFailure assertFailure(String code, String outcome, Operation operation) {
        BlockFailure failure = assertThrows(BlockFailure.class, operation::run);
        assertEquals(code, failure.code());
        assertEquals(outcome, failure.outcome());
        return failure;
    }

    private static final class Harness {
        final List<String> events = new ArrayList<>();
        final FakeWorld world = new FakeWorld(events);
        final FakeBackend backend = new FakeBackend(events, world);
        final BlockService service = new BlockService(backend, () -> events.add("guard"));
        final BlockService.SetterObserver observer = new BlockService.SetterObserver() {
            @Override public void beforeSetter() { events.add("beforeSetter"); }
            @Override public void afterSetter() { events.add("afterSetter"); }
        };
        Harness() { world.backend = backend; }
        void set(int x, int y, int z) throws BlockFailure {
            service.set(CONTEXT, "lesson", x, y, z, "minecraft:stone", observer);
        }
        void set(String requestedWorld, String key) throws BlockFailure {
            service.set(CONTEXT, requestedWorld, 0, 80, 0, key, observer);
        }
    }

    private static final class FakeBackend implements BlockService.Backend {
        final List<String> events;
        final Map<UUID, FakeWorld> byId = new HashMap<>();
        final Map<String, FakeWorld> byName = new HashMap<>();
        String failingEvent;
        FakeBackend(List<String> events, FakeWorld world) {
            this.events = events;
            byId.put(WORLD_ID, world);
            byName.put("lesson", world);
        }
        void event(String event) {
            events.add(event);
            if (event.equals(failingEvent)) throw new IllegalStateException("backend-secret");
        }
        @Override public BlockService.WorldAccess findWorld(UUID id) { event("world.uuid"); return byId.get(id); }
        @Override public BlockService.WorldAccess findWorld(String name) { event("world.name"); return byName.get(name); }
        @Override public BlockService.BlockMaterial resolveBlock(String key) {
            event("material");
            return "minecraft:stone".equals(key) ? STONE : null;
        }
    }

    private static final class FakeWorld implements BlockService.WorldAccess {
        final List<String> events;
        FakeBackend backend;
        UUID id = WORLD_ID;
        String name = "lesson";
        int min = -64, max = 320;
        boolean inside = true, loaded = true, setterThrows, physics;
        int setterCalls, chunkX, chunkZ;
        double centerX, centerZ;
        BlockService.BlockMaterial lastMaterial;
        FakeWorld(List<String> events) { this.events = events; }
        void event(String event) {
            if (backend == null) events.add(event);
            else backend.event(event);
        }
        @Override public String name() { event("identity.name"); return name; }
        @Override public UUID uuid() { event("identity.uuid"); return id; }
        @Override public int minY() { event("minY"); return min; }
        @Override public int maxYExclusive() { event("maxY"); return max; }
        @Override public boolean insideBorder(double x, double z) {
            event("border"); centerX = x; centerZ = z; return inside;
        }
        @Override public boolean isChunkLoaded(int x, int z) {
            event("loaded"); chunkX = x; chunkZ = z; return loaded;
        }
        @Override public BlockService.BlockAccess blockAt(int x, int y, int z) {
            event("blockAt");
            return (material, applyPhysics) -> {
                event("setter");
                setterCalls++;
                lastMaterial = material;
                physics = applyPhysics;
                if (setterThrows) throw new IllegalStateException("backend-secret");
            };
        }
    }
}
