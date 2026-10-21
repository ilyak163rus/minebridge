package dev.minebridge.blocks;

import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.NamespacedKey;
import org.bukkit.Registry;
import org.bukkit.Server;
import org.bukkit.World;

import java.util.Objects;
import java.util.UUID;

/** Ordinary Paper implementation; every entry point is confined to the primary server thread. */
public final class PaperBlockBackend implements BlockService.Backend {
    private final Server server;

    public PaperBlockBackend(Server server) { this.server = Objects.requireNonNull(server); }

    @Override public BlockService.WorldAccess findWorld(UUID uuid) {
        requireGameThread();
        World world = server.getWorld(uuid);
        return world == null ? null : new PaperWorld(world);
    }

    @Override public BlockService.WorldAccess findWorld(String name) {
        requireGameThread();
        World world = server.getWorld(name);
        return world == null ? null : new PaperWorld(world);
    }

    @Override public BlockService.BlockMaterial resolveBlock(String key) {
        requireGameThread();
        NamespacedKey namespaced = NamespacedKey.fromString(key);
        if (namespaced == null || !key.equals(namespaced.toString())) return null;
        Material material = Registry.MATERIAL.get(namespaced);
        if (material == null || !material.isBlock() || material.isLegacy()
                || !key.equals(material.getKey().toString())) return null;
        return new PaperMaterial(material);
    }

    private void requireGameThread() {
        if (!server.isPrimaryThread()) throw new IllegalStateException("Game thread required");
    }

    private record PaperMaterial(Material material) implements BlockService.BlockMaterial {}

    private final class PaperWorld implements BlockService.WorldAccess {
        private final World world;
        private PaperWorld(World world) { this.world = world; }
        @Override public String name() { requireGameThread(); return world.getName(); }
        @Override public UUID uuid() { requireGameThread(); return world.getUID(); }
        @Override public int minY() { requireGameThread(); return world.getMinHeight(); }
        @Override public int maxYExclusive() { requireGameThread(); return world.getMaxHeight(); }
        @Override public boolean insideBorder(double centerX, double centerZ) {
            requireGameThread();
            org.bukkit.WorldBorder border = world.getWorldBorder();
            Location center = border.getCenter();
            // CraftWorldBorder.isInside(Location) floors through BlockPos in the pinned build.
            // The bridge contract uses the exact block center and current public border size.
            return WorldBorderBounds.contains(centerX, centerZ, center.getX(), center.getZ(),
                    border.getSize(), server.getMaxWorldSize());
        }
        @Override public boolean isChunkLoaded(int chunkX, int chunkZ) {
            requireGameThread();
            return world.isChunkLoaded(chunkX, chunkZ);
        }
        @Override public BlockService.BlockAccess blockAt(int x, int y, int z) {
            requireGameThread();
            org.bukkit.block.Block block = world.getBlockAt(x, y, z);
            return (material, applyPhysics) -> {
                requireGameThread();
                block.setType(((PaperMaterial) material).material(), applyPhysics);
            };
        }
    }
}
