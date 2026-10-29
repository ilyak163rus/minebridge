package dev.minebridge.events;

import dev.minebridge.session.WorldContext;

import org.bukkit.Location;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.block.data.BlockData;
import org.bukkit.entity.Entity;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Player;
import org.bukkit.inventory.ItemStack;

import java.util.*;

/** Main-thread immutable primitive snapshots. No live Bukkit reference is retained. */
public final class EventSnapshotCache {
    private EventSnapshotCache() {}

    public static Map<String, Object> map(Object... pairs) {
        LinkedHashMap<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
        return Collections.unmodifiableMap(result);
    }

    public static WorldContext world(World world) {
        return new WorldContext(
                world.getName(),
                world.getKey().toString(),
                world.getUID(),
                world.getMinHeight(),
                world.getMaxHeight());
    }

    public static Map<String, Object> compactWorld(World world) {
        return Map.of(
                "uuid",
                world.getUID().toString(),
                "name",
                world.getName(),
                "key",
                world.getKey().toString());
    }

    public static Map<String, Object> entity(Entity entity) {
        return entity == null
                ? null
                : map(
                        "uuid",
                        entity.getUniqueId().toString(),
                        "entityId",
                        entity.getEntityId(),
                        "key",
                        entity.getType().getKey().toString(),
                        "living",
                        entity instanceof LivingEntity,
                        "name",
                        entity instanceof Player player ? player.getName() : null);
    }

    public static List<Double> position(Location at) {
        return List.of(at.getX(), at.getY(), at.getZ());
    }

    public static List<Integer> position(Block block) {
        return List.of(block.getX(), block.getY(), block.getZ());
    }

    public static List<Double> filterPosition(Block block) {
        return List.of((double) block.getX(), (double) block.getY(), (double) block.getZ());
    }

    public static Map<String, Object> block(BlockData data) {
        String raw = data.getAsString();
        int start = raw.indexOf('[');
        TreeMap<String, String> states = new TreeMap<>();
        if (start >= 0)
            for (String part : raw.substring(start + 1, raw.length() - 1).split(",")) {
                String[] pair = part.split("=", 2);
                if (pair.length == 2) states.put(pair[0], pair[1]);
            }
        return Map.of(
                "key",
                data.getMaterial().getKey().toString(),
                "states",
                Collections.unmodifiableMap(states));
    }

    public static Map<String, Object> blockAt(Block block) {
        return block == null
                ? null
                : Map.of("position", position(block), "block", block(block.getBlockData()));
    }

    public static String item(ItemStack stack) {
        return stack == null || stack.getType().isAir()
                ? null
                : stack.getType().getKey().toString();
    }
}
