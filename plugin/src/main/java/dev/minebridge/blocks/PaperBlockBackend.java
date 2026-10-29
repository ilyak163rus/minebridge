package dev.minebridge.blocks;

import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.NamespacedKey;
import org.bukkit.Registry;
import org.bukkit.Server;
import org.bukkit.World;
import org.bukkit.block.data.BlockData;
import org.bukkit.plugin.Plugin;

import java.util.Objects;
import java.util.UUID;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.CompletionStage;

/** Ordinary Paper implementation; every entry point is confined to the primary server thread. */
public final class PaperBlockBackend implements BlockService.Backend {
    private final Server server;
    private final Plugin plugin;

    public PaperBlockBackend(Server server) { this(server, null); }
    public PaperBlockBackend(Server server, Plugin plugin) {
        this.server = Objects.requireNonNull(server);
        this.plugin = plugin;
    }

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
        return new PaperMaterial(material.createBlockData());
    }

    @Override public BlockService.BlockMaterial resolveBlock(String key, Map<String, String> states) {
        requireGameThread();
        if (resolveBlock(key) == null) return null;
        StringBuilder specification = new StringBuilder(key);
        if (!states.isEmpty()) {
            specification.append('[');
            states.entrySet().stream().sorted(Map.Entry.comparingByKey()).forEach(entry ->
                    specification.append(entry.getKey()).append('=').append(entry.getValue()).append(','));
            specification.setCharAt(specification.length() - 1, ']');
        }
        try { return new PaperMaterial(server.createBlockData(specification.toString())); }
        catch (IllegalArgumentException invalid) { return null; }
    }

    private void requireGameThread() {
        if (!server.isPrimaryThread()) throw new IllegalStateException("Game thread required");
    }

    private record PaperMaterial(BlockData data) implements BlockService.BlockMaterial {}

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
        @Override public CompletionStage<Boolean> loadChunk(int x, int z) {
            requireGameThread();
            return world.getChunkAtAsync(x, z, true).thenApply(Objects::nonNull);
        }
        @Override public void addChunkTicket(int x, int z) {
            requireGameThread();
            if (plugin != null) world.addPluginChunkTicket(x, z, plugin);
        }
        @Override public void removeChunkTicket(int x, int z) {
            requireGameThread();
            if (plugin != null) world.removePluginChunkTicket(x, z, plugin);
        }
        @Override public BlockService.BlockValue readBlock(int x, int y, int z) {
            requireGameThread();
            BlockData data = world.getBlockAt(x, y, z).getBlockData();
            String text = data.getAsString();
            Map<String, String> states = new TreeMap<>();
            int start = text.indexOf('[');
            if (start >= 0) {
                for (String field : text.substring(start + 1, text.length() - 1).split(",")) {
                    String[] pair = field.split("=", 2);
                    states.put(pair[0], pair[1]);
                }
            }
            return new BlockService.BlockValue(data.getMaterial().getKey().toString(), states);
        }
        @Override public BlockService.BlockAccess blockAt(int x, int y, int z) {
            requireGameThread();
            org.bukkit.block.Block block = world.getBlockAt(x, y, z);
            return (material, applyPhysics) -> {
                requireGameThread();
                block.setBlockData(((PaperMaterial) material).data(), applyPhysics);
            };
        }
    }
}
