package dev.minebridge.observer;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.World;
import org.bukkit.entity.Entity;
import org.bukkit.entity.FallingBlock;
import org.bukkit.entity.Item;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Mob;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.entity.EntityDamageEvent;
import org.bukkit.event.entity.EntitySpawnEvent;
import org.bukkit.event.weather.LightningStrikeEvent;
import org.bukkit.inventory.ItemStack;

/** Console-only independent I04 oracle. Never reads bridge DTOs or service state. */
final class InteractionObserver implements Listener {
    private final ObserverPlugin plugin;
    private final List<Object> lightning = new ArrayList<>();
    private final List<Object> lightningDamage = new ArrayList<>();
    private final List<Object> farSpawns = new ArrayList<>();

    InteractionObserver(ObserverPlugin plugin) { this.plugin = plugin; }

    Map<String, Object> execute(String[] args) {
        return switch (args[2]) {
            case "inventoryFixture" -> inventoryFixture(args);
            case "inventory" -> inventory(args);
            case "entityState" -> entityState(args);
            case "entityHold" -> entityHold(args);
            case "livingFixture" -> livingFixture(args);
            case "hangingFixture" -> hangingFixture(args);
            case "nearbyDrops" -> nearbyDrops(args);
            case "lightningEvents" -> {
                length(args, 3);
                yield map("strikes", new ArrayList<>(lightning), "damage", new ArrayList<>(lightningDamage));
            }
            case "farSpawnEvents" -> {
                length(args, 3);
                yield map("spawns", new ArrayList<>(farSpawns));
            }
            default -> throw new IllegalArgumentException();
        };
    }

    private Map<String, Object> inventoryFixture(String[] args) {
        length(args, 5);
        Player player = player(args[3]);
        player.getInventory().clear();
        switch (args[4]) {
            case "empty" -> { }
            case "fishing-rod" -> player.getInventory().setItemInMainHand(new ItemStack(Material.FISHING_ROD));
            case "full", "partial" -> {
                for (int slot = 0; slot < 36; slot++)
                    player.getInventory().setItem(slot, new ItemStack(Material.STONE, 64));
                if (args[4].equals("partial"))
                    player.getInventory().setItem(0, new ItemStack(Material.DIAMOND, 60));
            }
            default -> throw new IllegalArgumentException();
        }
        return inventory(player);
    }

    private Map<String, Object> inventory(String[] args) {
        length(args, 4);
        return inventory(player(args[3]));
    }

    private Map<String, Object> inventory(Player player) {
        List<Object> slots = new ArrayList<>();
        for (int index = 0; index < 36; index++)
            slots.add(map("slot", index, "item", item(player.getInventory().getItem(index))));
        return map("uuid", player.getUniqueId().toString(), "slots", slots);
    }

    private Map<String, Object> entityState(String[] args) {
        length(args, 4);
        Entity entity = plugin.getServer().getEntity(UUID.fromString(args[3]));
        return entity == null ? map("exists", false, "uuid", args[3]) : snapshot(entity);
    }

    private Map<String, Object> entityHold(String[] args) {
        length(args, 4);
        Entity entity = entity(args[3]);
        entity.setGravity(false);
        entity.setPersistent(true);
        if (entity instanceof Mob mob) mob.setAI(false);
        return snapshot(entity);
    }

    private Map<String, Object> livingFixture(String[] args) {
        length(args, 7);
        World world = world(args[3]);
        Entity entity = world.spawnEntity(new Location(world, finite(args[4]), finite(args[5]), finite(args[6])),
                org.bukkit.entity.EntityType.COW);
        entity.setGravity(false);
        ((Mob) entity).setAI(false);
        return snapshot(entity);
    }

    private Map<String, Object> hangingFixture(String[] args) {
        length(args, 7);
        World world = world(args[3]);
        int x = Integer.parseInt(args[4]), y = Integer.parseInt(args[5]), z = Integer.parseInt(args[6]);
        // Retain the oracle's own wall chunks while checking the returned UUID.
        // The production lease is allowed to expire as soon as spawn completes;
        // an unloaded entity is not evidence that Minecraft destroyed it.
        for (int cx = Math.floorDiv(x - 4, 16); cx <= Math.floorDiv(x + 4, 16); cx++)
            for (int cz = Math.floorDiv(z - 1, 16); cz <= Math.floorDiv(z + 2, 16); cz++)
                world.addPluginChunkTicket(cx, cz, plugin);
        // A sufficiently large wall admits every painting size in the pinned
        // registry. This is a disposable fixture world, not a production API.
        for (int dx = -4; dx <= 4; dx++) for (int dy = -4; dy <= 4; dy++) {
            world.getBlockAt(x + dx, y + dy, z - 1).setType(Material.STONE, false);
            for (int dz = 0; dz <= 2; dz++)
                world.getBlockAt(x + dx, y + dy, z + dz).setType(Material.AIR, false);
        }
        return map("x", x, "y", y, "z", z, "face", "south",
                "backing", world.getBlockAt(x, y, z - 1).getType().getKey().toString());
    }

    private Map<String, Object> nearbyDrops(String[] args) {
        length(args, 8);
        World world = world(args[3]);
        Location center = new Location(world, finite(args[4]), finite(args[5]), finite(args[6]));
        double radius = finite(args[7]);
        if (radius < 0 || radius > 32) throw new IllegalArgumentException();
        List<Object> values = new ArrayList<>();
        for (Entity entity : world.getNearbyEntities(center, radius, radius, radius))
            if (entity instanceof Item) values.add(snapshot(entity));
        return map("items", values);
    }

    private Map<String, Object> snapshot(Entity entity) {
        Location at = entity.getLocation();
        Map<String, Object> value = map("exists", true, "uuid", entity.getUniqueId().toString(),
                "entityId", entity.getEntityId(), "type", entity.getType().getKey().toString(),
                "world", entity.getWorld().getName(), "x", at.getX(), "y", at.getY(), "z", at.getZ(),
                "valid", entity.isValid(), "dead", entity.isDead(),
                "ticksLived", entity.getTicksLived(), "fireTicks", entity.getFireTicks(),
                "ticking", entity.isTicking(), "invulnerable", entity.isInvulnerable());
        int cx = Math.floorDiv(at.getBlockX(), 16), cz = Math.floorDiv(at.getBlockZ(), 16);
        boolean loaded = entity.getWorld().isChunkLoaded(cx, cz);
        value.put("chunkLoaded", loaded);
        value.put("chunkLoadLevel", loaded ? entity.getWorld().getChunkAt(cx, cz).getLoadLevel().name() : null);
        if (entity instanceof Item dropped) value.put("item", item(dropped.getItemStack()));
        if (entity instanceof FallingBlock falling) value.put("block", falling.getBlockData().getAsString());
        if (entity instanceof org.bukkit.entity.Hanging hanging)
            value.put("face", hanging.getFacing().name().toLowerCase(java.util.Locale.ROOT));
        if (entity instanceof org.bukkit.entity.Projectile projectile)
            value.put("owner", projectile.getShooter() instanceof Entity owner ? owner.getUniqueId().toString() : null);
        if (entity instanceof LivingEntity living) {
            value.put("health", living.getHealth());
            List<Object> effects = new ArrayList<>();
            for (var effect : living.getActivePotionEffects())
                effects.add(map("key", effect.getType().getKey().toString(), "duration", effect.getDuration(),
                        "amplifier", effect.getAmplifier(), "particles", effect.hasParticles(),
                        "ambient", effect.isAmbient()));
            value.put("effects", effects);
        }
        return value;
    }

    private static Object item(ItemStack stack) {
        if (stack == null || stack.getType().isAir()) return null;
        var metadata = stack.getItemMeta();
        return map("key", stack.getType().getKey().toString(), "amount", stack.getAmount(),
                "name", metadata != null && metadata.hasDisplayName()
                        ? PlainTextComponentSerializer.plainText().serialize(metadata.displayName()) : null,
                "lore", metadata != null && metadata.hasLore()
                        ? metadata.lore().stream().map(PlainTextComponentSerializer.plainText()::serialize).toList() : null);
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void strike(LightningStrikeEvent event) {
        if (lightning.size() == 128) return;
        var strike = event.getLightning();
        var at = strike.getLocation();
        lightning.add(map("uuid", strike.getUniqueId().toString(), "effect", strike.isEffect(),
                "cancelled", event.isCancelled(), "cause", event.getCause().name(),
                "world", at.getWorld().getName(), "x", at.getX(), "y", at.getY(), "z", at.getZ(),
                "tick", plugin.getServer().getCurrentTick()));
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void damage(EntityDamageEvent event) {
        if (event.getCause() != EntityDamageEvent.DamageCause.LIGHTNING || lightningDamage.size() == 128) return;
        Entity direct = event.getDamageSource().getDirectEntity();
        Entity causing = event.getDamageSource().getCausingEntity();
        Entity damager = event instanceof EntityDamageByEntityEvent byEntity ? byEntity.getDamager() : direct;
        lightningDamage.add(map("lightning", damager == null ? null : damager.getUniqueId().toString(),
                "entity", event.getEntity().getUniqueId().toString(), "damage", event.getFinalDamage(),
                "cancelled", event.isCancelled(), "tick", plugin.getServer().getCurrentTick(),
                "cause", event.getCause().name(), "eventClass", event.getClass().getName(),
                "damageType", event.getDamageSource().getDamageType().getKey().toString(),
                "directEntity", direct == null ? null : direct.getUniqueId().toString(),
                "causingEntity", causing == null ? null : causing.getUniqueId().toString()));
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void farSpawn(EntitySpawnEvent event) {
        Location at = event.getLocation();
        if (Math.abs(at.getX()) < 19_000 || farSpawns.size() == 128) return;
        farSpawns.add(map("uuid", event.getEntity().getUniqueId().toString(),
                "type", event.getEntityType().getKey().toString(), "world", at.getWorld().getName(),
                "x", at.getX(), "y", at.getY(), "z", at.getZ(), "cancelled", event.isCancelled(),
                "tick", plugin.getServer().getCurrentTick()));
    }

    private Entity entity(String uuid) {
        Entity entity = plugin.getServer().getEntity(UUID.fromString(uuid));
        if (entity == null) throw new IllegalArgumentException();
        return entity;
    }
    private Player player(String name) {
        Player player = plugin.getServer().getPlayerExact(name);
        if (player == null) throw new IllegalArgumentException();
        return player;
    }
    private World world(String uuid) {
        World world = plugin.getServer().getWorld(UUID.fromString(uuid));
        if (world == null) throw new IllegalArgumentException();
        return world;
    }
    private static double finite(String text) {
        double value = Double.parseDouble(text);
        if (!Double.isFinite(value)) throw new IllegalArgumentException();
        return value;
    }
    private static void length(String[] args, int expected) {
        if (args.length != expected) throw new IllegalArgumentException();
    }
    private static Map<String, Object> map(Object... pairs) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
        return result;
    }
}
