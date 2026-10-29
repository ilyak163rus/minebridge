package dev.minebridge.blocks;

import dev.minebridge.session.WorldContext;

import java.util.Objects;
import java.util.UUID;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.regex.Pattern;

/** One synchronous check-and-write operation. The executor owns scheduling and response publication. */
public final class BlockService {
    private static final Pattern BLOCK_KEY = Pattern.compile("[a-z0-9_.-]+:[a-z0-9_./-]+");

    /** Narrow live-server boundary, also usable without Paper in deterministic tests. */
    public interface Backend {
        WorldAccess findWorld(UUID uuid);
        WorldAccess findWorld(String name);
        /** Return an exact, registered block material, or null. No alias or fallback resolution. */
        BlockMaterial resolveBlock(String key);
        default BlockMaterial resolveBlock(String key, Map<String, String> states) {
            return states.isEmpty() ? resolveBlock(key) : null;
        }
    }

    public interface WorldAccess {
        String name();
        UUID uuid();
        int minY();
        int maxYExclusive();
        boolean insideBorder(double centerX, double centerZ);
        boolean isChunkLoaded(int chunkX, int chunkZ);
        BlockAccess blockAt(int x, int y, int z);
        default CompletionStage<Boolean> loadChunk(int x, int z) {
            return CompletableFuture.completedFuture(isChunkLoaded(x, z));
        }
        default void addChunkTicket(int x, int z) {}
        default void removeChunkTicket(int x, int z) {}
        default BlockValue readBlock(int x, int y, int z) { throw new UnsupportedOperationException(); }
    }

    public record BlockValue(String key, Map<String, String> states) {
        public BlockValue { states = Map.copyOf(states); }
        public Map<String, Object> toProtocol() { return Map.of("key", key, "states", states); }
    }

    /** Opaque handle: only the matching backend interprets a validated material. */
    public interface BlockMaterial {}

    @FunctionalInterface public interface BlockAccess {
        void setType(BlockMaterial material, boolean applyPhysics);
    }

    public interface SetterObserver {
        SetterObserver NONE = new SetterObserver() {
            @Override public void beforeSetter() {}
            @Override public void afterSetter() {}
        };
        void beforeSetter();
        void afterSetter();
    }

    private final Backend backend;
    private final Runnable requireGameThread;

    public BlockService(Backend backend, Runnable requireGameThread) {
        this.backend = Objects.requireNonNull(backend);
        this.requireGameThread = Objects.requireNonNull(requireGameThread);
    }

    public WorldAccess world(WorldContext context, String requestedWorld) throws BlockFailure {
        requireGameThread.run();
        if (!context.name().equals(requestedWorld)) {
            throw rejected(backend.findWorld(requestedWorld) == null ? "WORLD_NOT_FOUND" : "PERMISSION_DENIED");
        }
        WorldAccess world = backend.findWorld(context.uuid());
        if (world == null || !context.uuid().equals(world.uuid()) || !context.name().equals(world.name())) {
            throw rejected("WORLD_NOT_FOUND");
        }
        return world;
    }

    public void checkPosition(WorldAccess world, int x, int y, int z) throws BlockFailure {
        requireGameThread.run();
        if (y < world.minY() || y >= world.maxYExclusive()
                || !world.insideBorder((double) x + 0.5d, (double) z + 0.5d)) {
            throw rejected("COORDINATE_OUT_OF_BOUNDS");
        }
    }

    public BlockMaterial material(String key, Map<String, String> states) throws BlockFailure {
        requireGameThread.run();
        if (key == null || !BLOCK_KEY.matcher(key).matches()) throw rejected("INVALID_BLOCK");
        BlockMaterial material = backend.resolveBlock(key, states);
        if (material == null) throw rejected("INVALID_BLOCK");
        return material;
    }

    /** Parameters have already passed the strict wire schema; coordinates are exact int32 values. */
    public void set(WorldContext sessionWorld, String requestedWorld, int x, int y, int z,
                    String key, SetterObserver observer) throws BlockFailure {
        requireGameThread.run();
        Objects.requireNonNull(sessionWorld);
        Objects.requireNonNull(requestedWorld);
        Objects.requireNonNull(observer);
        boolean setterEntered = false;
        try {
            if (!sessionWorld.name().equals(requestedWorld)) {
                throw rejected(backend.findWorld(requestedWorld) == null
                        ? "WORLD_NOT_FOUND" : "PERMISSION_DENIED");
            }
            // Resolve by the hello UUID each time: a newly created world with the old name
            // must never silently become the target of this connection.
            WorldAccess world = backend.findWorld(sessionWorld.uuid());
            if (world == null || !sessionWorld.uuid().equals(world.uuid())
                    || !sessionWorld.name().equals(world.name())) {
                throw rejected("WORLD_NOT_FOUND");
            }
            if (y < world.minY() || y >= world.maxYExclusive()
                    || !world.insideBorder((double) x + 0.5d, (double) z + 0.5d)) {
                throw rejected("COORDINATE_OUT_OF_BOUNDS");
            }
            if (key == null || !BLOCK_KEY.matcher(key).matches()) throw rejected("INVALID_BLOCK");
            BlockMaterial material = backend.resolveBlock(key);
            if (material == null) throw rejected("INVALID_BLOCK");
            if (!world.isChunkLoaded(Math.floorDiv(x, 16), Math.floorDiv(z, 16))) {
                throw rejected("CHUNK_NOT_LOADED");
            }
            // No getBlockAt (which can load a chunk) is allowed until the loaded-only check.
            BlockAccess block = Objects.requireNonNull(world.blockAt(x, y, z));
            observer.beforeSetter();
            setterEntered = true;
            block.setType(material, true);
            observer.afterSetter();
        } catch (BlockFailure failure) {
            throw failure;
        } catch (RuntimeException failure) {
            // A setter may have partially changed the world before throwing. Never imply rollback.
            throw new BlockFailure("INTERNAL_ERROR", setterEntered ? "unknown" : "not-applied");
        }
    }

    private static BlockFailure rejected(String code) { return new BlockFailure(code, "not-applied"); }
}
