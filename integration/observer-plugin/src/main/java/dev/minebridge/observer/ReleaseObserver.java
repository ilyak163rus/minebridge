package dev.minebridge.observer;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.bukkit.Difficulty;
import org.bukkit.World;
import org.bukkit.block.data.BlockData;
import org.bukkit.entity.Entity;
import org.bukkit.entity.EntityType;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityDamageEvent;
import org.bukkit.scheduler.BukkitTask;

/** Bounded final-release load fixture. It invokes real native damage, never bridge capture. */
final class ReleaseObserver implements Listener {
    private final ObserverPlugin plugin;
    private BukkitTask task;
    private UUID victim;
    private String run;
    private int target, produced, observed, batch;
    private boolean active;
    private String error;

    ReleaseObserver(ObserverPlugin plugin) { this.plugin = plugin; }

    Map<String, Object> execute(String[] args) {
        if (!plugin.getServer().isPrimaryThread()) throw new IllegalStateException();
        if (args[2].equals("releaseDifficulty")) {
            if (args.length != 5) throw new IllegalArgumentException();
            World world = world(args[3]);
            if (!args[4].equals("read")) world.setDifficulty(Difficulty.valueOf(args[4].toUpperCase(Locale.ROOT)));
            return Map.of("world", world.getUID().toString(), "difficulty", world.getDifficulty().name());
        }
        if (args[2].equals("releaseEntities")) {
            if (args.length != 4) throw new IllegalArgumentException();
            World world = world(args[3]);
            List<Object> rows = new ArrayList<>();
            for (Entity entity : world.getEntities()) {
                if (entity.getType() == EntityType.GIANT || entity.getType() == EntityType.ZOMBIE
                        || entity.getType() == EntityType.SHULKER || entity.getType() == EntityType.COW) {
                    var location = entity.getLocation();
                    rows.add(Map.of("uuid", entity.getUniqueId().toString(), "type", entity.getType().name(),
                            "valid", entity.isValid(), "x", location.getX(), "y", location.getY(), "z", location.getZ()));
                }
            }
            return Map.of("world", world.getUID().toString(), "entities", rows);
        }
        if (args[2].equals("releaseRegion") || args[2].equals("releaseFill")) return region(args);
        if (args[2].equals("releaseBurstStatus")) return status();
        if (args[2].equals("releaseBurstCancel")) {
            cancel(); return status();
        }
        if (!args[2].equals("releaseBurst") || args.length != 8 || active) throw new IllegalArgumentException();
        run = args[3];
        if (!run.matches("[a-zA-Z0-9_-]{1,64}")) throw new IllegalArgumentException();
        Player player = plugin.getServer().getPlayerExact(args[4]);
        Player cause = plugin.getServer().getPlayerExact(args[5]);
        target = Integer.parseInt(args[6]); batch = Integer.parseInt(args[7]);
        if (player == null || cause == null || target < 1 || target > 5000 || batch < 1 || batch > 32)
            throw new IllegalArgumentException();
        victim = player.getUniqueId(); produced = observed = 0; error = null; active = true;
        task = plugin.getServer().getScheduler().runTaskTimer(plugin, () -> {
            try {
                if (!player.isOnline() || !cause.isOnline()) throw new IllegalStateException();
                for (int i = 0; i < batch && produced < target; i++) {
                    player.setNoDamageTicks(0);
                    player.setHealth(20);
                    // Native event processing, including health calculation and all listeners.
                    player.damage(1.0, cause);
                    produced++;
                }
                if (produced == target) cancel();
            } catch (RuntimeException invalidFixtureState) {
                error = "NATIVE_DAMAGE_FAILED"; cancel();
            }
        }, 1L, 1L);
        return status();
    }

    private World world(String value) {
        World world = plugin.getServer().getWorld(UUID.fromString(value));
        if (world == null) throw new IllegalArgumentException();
        return world;
    }

    /** Independent native command/readback. The caller must hold all involved chunks. */
    private Map<String, Object> region(String[] args) {
        if (args.length != 11) throw new IllegalArgumentException();
        World world = world(args[3]);
        int x1 = Integer.parseInt(args[4]), y1 = Integer.parseInt(args[5]), z1 = Integer.parseInt(args[6]);
        int x2 = Integer.parseInt(args[7]), y2 = Integer.parseInt(args[8]), z2 = Integer.parseInt(args[9]);
        int minX = Math.min(x1, x2), maxX = Math.max(x1, x2);
        int minY = Math.min(y1, y2), maxY = Math.max(y1, y2);
        int minZ = Math.min(z1, z2), maxZ = Math.max(z1, z2);
        long volume = ((long) maxX - minX + 1) * ((long) maxY - minY + 1) * ((long) maxZ - minZ + 1);
        if (volume < 1 || volume > 262144 || minY < world.getMinHeight() || maxY >= world.getMaxHeight())
            throw new IllegalArgumentException();
        for (int cx = Math.floorDiv(minX, 16); cx <= Math.floorDiv(maxX, 16); cx++) {
            for (int cz = Math.floorDiv(minZ, 16); cz <= Math.floorDiv(maxZ, 16); cz++) {
                if (!world.isChunkLoaded(cx, cz)) throw new IllegalArgumentException();
            }
        }
        BlockData expected = plugin.getServer().createBlockData(args[10]);
        String canonical = expected.getAsString();
        long started = System.nanoTime();
        boolean dispatched = false;
        int tickBefore = plugin.getServer().getCurrentTick();
        if (args[2].equals("releaseFill")) {
            if (volume > 32768 || !args[10].matches("minecraft:(stone|cobblestone)")) throw new IllegalArgumentException();
            dispatched = plugin.getServer().dispatchCommand(plugin.getServer().getConsoleSender(),
                    "execute in " + world.getKey() + " run fill " + minX + " " + minY + " " + minZ + " "
                            + maxX + " " + maxY + " " + maxZ + " " + args[10]);
        }
        long completed = System.nanoTime();
        int matched = 0;
        List<Integer> firstMismatch = null;
        for (int x = minX; x <= maxX; x++) for (int y = minY; y <= maxY; y++) for (int z = minZ; z <= maxZ; z++) {
            if (world.getBlockAt(x, y, z).getBlockData().getAsString().equals(canonical)) matched++;
            else if (firstMismatch == null) firstMismatch = List.of(x, y, z);
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("world", world.getUID().toString()); result.put("volume", volume);
        result.put("matched", matched); result.put("firstMismatch", firstMismatch); result.put("blockData", canonical);
        result.put("nativeCommandDispatched", dispatched);
        result.put("seconds", (completed - started) / 1_000_000_000.0);
        result.put("tickBefore", tickBefore); result.put("tickAfter", plugin.getServer().getCurrentTick());
        return result;
    }

    private void cancel() {
        active = false;
        if (task != null) { task.cancel(); task = null; }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onDamage(EntityDamageEvent event) {
        if (active && event.getEntity().getUniqueId().equals(victim)) observed++;
    }

    private Map<String, Object> status() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("run", run); result.put("active", active); result.put("target", target);
        result.put("produced", produced); result.put("observedNative", observed);
        result.put("batch", batch); result.put("error", error);
        result.put("tick", plugin.getServer().getCurrentTick());
        return result;
    }
}
