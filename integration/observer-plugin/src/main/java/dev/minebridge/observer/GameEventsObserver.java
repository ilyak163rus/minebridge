package dev.minebridge.observer;

import io.papermc.paper.event.player.PrePlayerAttackEntityEvent;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.HashSet;
import java.util.UUID;
import org.bukkit.GameMode;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.entity.Entity;
import org.bukkit.entity.EntityType;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Mob;
import org.bukkit.entity.Player;
import org.bukkit.entity.Projectile;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.block.BlockBreakEvent;
import org.bukkit.event.block.BlockPlaceEvent;
import org.bukkit.event.block.BlockFromToEvent;
import org.bukkit.event.entity.EntityDamageEvent;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.entity.EntityShootBowEvent;
import org.bukkit.event.entity.PlayerDeathEvent;
import org.bukkit.event.entity.ProjectileLaunchEvent;
import org.bukkit.event.entity.ProjectileHitEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.player.PlayerRespawnEvent;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.CrossbowMeta;
import org.bukkit.potion.PotionEffect;
import org.bukkit.potion.PotionEffectType;
import org.bukkit.util.Vector;

/** Independent native-event oracle. Console setup changes real Paper objects;
 * it never fabricates events or reads the production event service. */
final class GameEventsObserver implements Listener {
    private final ObserverPlugin plugin;
    private final ArrayDeque<Map<String, Object>> audit = new ArrayDeque<>();
    private final Set<String> cancelled = new HashSet<>();
    private final Map<UUID, Location> respawnOverrides = new LinkedHashMap<>();
    private long sequence;

    GameEventsObserver(ObserverPlugin plugin) { this.plugin = plugin; }

    Map<String, Object> execute(String[] a) {
        if (!plugin.getServer().isPrimaryThread()) throw new IllegalStateException();
        return switch (a[2]) {
            case "i03State" -> map("events", new ArrayList<>(audit), "sequence", sequence,
                    "tick", plugin.getServer().getCurrentTick());
            case "i03Clear" -> { audit.clear(); yield map("cleared", true); }
            case "i03Cancel" -> {
                if (a.length != 5) throw new IllegalArgumentException();
                if (Boolean.parseBoolean(a[4])) cancelled.add(a[3]); else cancelled.remove(a[3]);
                yield map("types", new ArrayList<>(cancelled));
            }
            case "i03Player" -> {
                if (a.length != 12) throw new IllegalArgumentException();
                Player p = player(a[3]); World w = world(a[4]);
                p.setGameMode(GameMode.valueOf(a[10])); p.setGravity(false);
                p.setInvulnerable(Boolean.parseBoolean(a[11])); p.setFireTicks(0);
                p.setNoDamageTicks(0); p.setVelocity(new Vector());
                if (!p.teleport(new Location(w, num(a[5]), num(a[6]), num(a[7]),
                        Float.parseFloat(a[8]), Float.parseFloat(a[9])))) throw new IllegalStateException();
                yield playerState(p);
            }
            case "i03PlayerState" -> playerState(player(a[3]));
            case "i03Item" -> {
                Player p = player(a[3]); Material material = Material.valueOf(a[4]);
                ItemStack stack = material.isAir() ? null : new ItemStack(material, Integer.parseInt(a[5]));
                p.getInventory().setHeldItemSlot(0);
                if (a.length > 6 && a[6].equals("OFF_HAND")) p.getInventory().setItemInOffHand(stack);
                else p.getInventory().setItemInMainHand(stack);
                if (material == Material.BOW || material == Material.CROSSBOW)
                    p.getInventory().setItem(9, new ItemStack(Material.ARROW, 64));
                if (material == Material.CROSSBOW && a.length > 6 && a[6].equals("MULTISHOT")) {
                    stack.addUnsafeEnchantment(org.bukkit.enchantments.Enchantment.MULTISHOT, 1);
                    CrossbowMeta meta = (CrossbowMeta) stack.getItemMeta();
                    meta.setChargedProjectiles(List.of(new ItemStack(Material.ARROW),
                            new ItemStack(Material.ARROW), new ItemStack(Material.ARROW)));
                    stack.setItemMeta(meta); p.getInventory().setItemInMainHand(stack);
                }
                yield playerState(p);
            }
            case "i03Block" -> {
                World w = world(a[3]); Block b = w.getBlockAt(Integer.parseInt(a[4]), Integer.parseInt(a[5]), Integer.parseInt(a[6]));
                b.setType(Material.valueOf(a[7]), true);
                yield map("position", pos(b.getLocation()), "key", b.getType().getKey().toString());
            }
            case "i03Wall" -> {
                World w = world(a[3]); int z = Integer.parseInt(a[4]);
                for (int x = 120; x <= 136; x++) for (int y = 208; y <= 219; y++)
                    w.getBlockAt(x, y, z).setType(Material.STONE, false);
                yield map("built", true, "z", z);
            }
            case "i03Target" -> {
                World w = world(a[3]); Entity e = w.spawnEntity(new Location(w, num(a[4]), num(a[5]), num(a[6])), EntityType.valueOf(a[7]));
                e.setGravity(false); e.setInvulnerable(Boolean.parseBoolean(a[8]));
                if (e instanceof Mob mob) mob.setAI(false);
                yield ref(e);
            }
            case "i03Damage" -> {
                LivingEntity victim = (LivingEntity) entity(a[3]); victim.setNoDamageTicks(0); victim.setInvulnerable(false);
                if (a.length > 5) victim.damage(num(a[4]), entity(a[5])); else victim.damage(num(a[4]));
                yield map("victim", ref(victim), "health", (double) (float) victim.getHealth(), "dead", victim.isDead());
            }
            case "i03Death" -> {
                Player p = player(a[3]); p.setInvulnerable(false); p.setHealth(0);
                yield map("dead", p.isDead(), "player", ref(p));
            }
            case "i03RespawnAt" -> {
                Player p = player(a[3]);
                Location wanted = new Location(world(a[4]), num(a[5]), num(a[6]), num(a[7]));
                p.setRespawnLocation(wanted, true);
                // Vanilla's stored-spawn safety check can reject lava even for
                // force=true. Override the actual native event explicitly so
                // this fixture really tests a respawn into fluid, not worldspawn.
                if (respawnOverrides.size() >= 16 && !respawnOverrides.containsKey(p.getUniqueId()))
                    throw new IllegalArgumentException();
                respawnOverrides.put(p.getUniqueId(), wanted);
                yield map("set", true, "nativeEventOverride", true);
            }
            case "i03Resistance" -> {
                Player p = player(a[3]); p.setFireTicks(0);
                if (Boolean.parseBoolean(a[4])) p.addPotionEffect(new PotionEffect(PotionEffectType.FIRE_RESISTANCE, 24000, 0));
                else p.removePotionEffect(PotionEffectType.FIRE_RESISTANCE);
                yield playerState(p);
            }
            case "i03Remove" -> { entity(a[3]).remove(); yield map("removed", true); }
            case "i03SourceShot" -> {
                // Non-player source: a real dispenser projectile, not a player guess.
                World w = world(a[3]); Block b = w.getBlockAt(128, 212, 126);
                b.setType(Material.DISPENSER, false);
                org.bukkit.block.Dispenser dispenser = (org.bukkit.block.Dispenser) b.getState();
                Projectile shot = dispenser.getBlockProjectileSource().launchProjectile(org.bukkit.entity.Snowball.class,
                        new Vector(0, 0, 1.5));
                yield ref(shot);
            }
            default -> throw new IllegalArgumentException();
        };
    }

    private Map<String, Object> playerState(Player p) {
        return map("player", ref(p), "world", p.getWorld().getUID().toString(), "position", pos(p.getLocation()),
                "lava", p.isInLava(), "dead", p.isDead(), "health", (double) (float) p.getHealth(),
                "mode", p.getGameMode().name(), "fireResistance", p.hasPotionEffect(PotionEffectType.FIRE_RESISTANCE),
                "usingTicks", p.getActiveItemUsedTime(), "usingRemainingTicks", p.getActiveItemRemainingTime(),
                "using", p.isHandRaised(), "tick", plugin.getServer().getCurrentTick());
    }
    private Entity entity(String name) {
        Player p = plugin.getServer().getPlayerExact(name); if (p != null) return p;
        Entity e = plugin.getServer().getEntity(UUID.fromString(name)); if (e == null) throw new IllegalArgumentException(); return e;
    }
    private Player player(String name) { return (Player) entity(name); }
    private World world(String id) { World w = plugin.getServer().getWorld(UUID.fromString(id)); if (w == null) throw new IllegalArgumentException(); return w; }
    private static double num(String v) { double n = Double.parseDouble(v); if (!Double.isFinite(n)) throw new IllegalArgumentException(); return n; }
    private static List<Object> pos(Location p) { return List.of(p.getX(), p.getY(), p.getZ()); }
    private static Map<String, Object> ref(Entity e) {
        return map("uuid", e.getUniqueId().toString(), "entityId", e.getEntityId(), "key", e.getType().getKey().toString(),
                "name", e instanceof Player p ? p.getName() : null);
    }
    private void record(String type, Map<String, Object> fields) {
        if (audit.size() == 1024) audit.removeFirst();
        LinkedHashMap<String, Object> value = new LinkedHashMap<>(fields);
        value.put("type", type); value.put("sequence", ++sequence); value.put("tick", plugin.getServer().getCurrentTick());
        value.put("primaryThread", plugin.getServer().isPrimaryThread()); audit.addLast(value);
    }
    private static Map<String, Object> map(Object... values) {
        Map<String, Object> r = new LinkedHashMap<>(); for (int i = 0; i < values.length; i += 2) r.put((String) values[i], values[i + 1]); return r;
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=false) public void cancelBreak(BlockBreakEvent e) { if(cancelled.contains("block.break"))e.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=false) public void cancelPlace(BlockPlaceEvent e) { if(cancelled.contains("block.place"))e.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=false) public void cancelInteract(PlayerInteractEvent e) { if(cancelled.contains("block.interact"))e.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=false) public void cancelAttack(PrePlayerAttackEntityEvent e) { if(cancelled.contains("entity.attack"))e.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=false) public void cancelDamage(EntityDamageEvent e) { if(cancelled.contains("entity.damage"))e.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=false) public void cancelLaunch(ProjectileLaunchEvent e) { if(cancelled.contains("projectile.shot"))e.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=false) public void cancelHit(ProjectileHitEvent e) { if(cancelled.contains("projectile.hit"))e.setCancelled(true); }
    @EventHandler(priority=EventPriority.HIGHEST) public void placeRespawn(PlayerRespawnEvent e) {
        Location wanted = respawnOverrides.remove(e.getPlayer().getUniqueId());
        if (wanted != null) e.setRespawnLocation(wanted.clone());
    }

    @EventHandler(priority=EventPriority.MONITOR, ignoreCancelled=false) public void onBreak(BlockBreakEvent e) {
        record("block.break", map("player", ref(e.getPlayer()), "position", pos(e.getBlock().getLocation()), "key", e.getBlock().getType().getKey().toString(), "cancelled", e.isCancelled()));
    }
    @EventHandler(priority=EventPriority.MONITOR, ignoreCancelled=false) public void onPlace(BlockPlaceEvent e) {
        record("block.place", map("player", ref(e.getPlayer()), "position", pos(e.getBlock().getLocation()), "key", e.getBlock().getType().getKey().toString(), "cancelled", e.isCancelled()));
    }
    @EventHandler(priority=EventPriority.MONITOR, ignoreCancelled=false) public void onInteract(PlayerInteractEvent e) {
        if(e.getClickedBlock()!=null) record("block.interact", map("player",ref(e.getPlayer()), "position",pos(e.getClickedBlock().getLocation()),
                "action",e.getAction().name(),"hand",e.getHand()==null?null:e.getHand().name(),"cancelled",e.isCancelled()));
    }
    @EventHandler(priority=EventPriority.MONITOR, ignoreCancelled=false) public void onAttack(PrePlayerAttackEntityEvent e) {
        record("entity.attack", map("player",ref(e.getPlayer()),"target",ref(e.getAttacked()),"willAttack",e.willAttack(),"cancelled",e.isCancelled()));
    }
    @EventHandler(priority=EventPriority.MONITOR, ignoreCancelled=false) public void onDamage(EntityDamageEvent e) {
        record("entity.damage",map("victim",ref(e.getEntity()),"directSource",e instanceof EntityDamageByEntityEvent d?ref(d.getDamager()):null,
                "cause",e.getCause().name(),"rawDamage",e.getDamage(),"finalDamage",e.getFinalDamage(),"cancelled",e.isCancelled()));
    }
    @EventHandler(priority=EventPriority.MONITOR, ignoreCancelled=false) public void onBow(EntityShootBowEvent e) {
        record("bow.context",map("projectile",ref(e.getProjectile()),"shooter",ref(e.getEntity()),"weapon",e.getBow()==null?null:e.getBow().getType().getKey().toString(),
                "force",(double)e.getForce(),"hand",e.getHand()==null?null:e.getHand().name(),"cancelled",e.isCancelled()));
    }
    @EventHandler(priority=EventPriority.MONITOR, ignoreCancelled=false) public void onLaunch(ProjectileLaunchEvent e) {
        record("projectile.shot",map("projectile",ref(e.getEntity()),"shooter",e.getEntity().getShooter() instanceof Entity s?ref(s):null,
                "position",pos(e.getEntity().getLocation()),"cancelled",e.isCancelled()));
    }
    @EventHandler(priority=EventPriority.MONITOR, ignoreCancelled=false) public void onHit(ProjectileHitEvent e) {
        record("projectile.hit",map("projectile",ref(e.getEntity()),"hitEntity",e.getHitEntity()==null?null:ref(e.getHitEntity()),
                "hitBlock",e.getHitBlock()==null?null:pos(e.getHitBlock().getLocation()),"cancelled",e.isCancelled()));
    }
    @EventHandler(priority=EventPriority.MONITOR) public void onJoin(PlayerJoinEvent e) { record("player.join",map("player",ref(e.getPlayer()))); }
    @EventHandler(priority=EventPriority.MONITOR) public void onQuit(PlayerQuitEvent e) { record("player.quit",map("player",ref(e.getPlayer()))); }
    @EventHandler(priority=EventPriority.MONITOR) public void onDeath(PlayerDeathEvent e) { record("player.death",map("player",ref(e.getPlayer()),"position",pos(e.getPlayer().getLocation()))); }
    @EventHandler(priority=EventPriority.MONITOR) public void onRespawn(PlayerRespawnEvent e) { record("player.respawn",map("player",ref(e.getPlayer()),"reason",e.getRespawnReason().name(),"position",pos(e.getRespawnLocation()))); }
    @EventHandler(priority=EventPriority.MONITOR) public void onFlow(BlockFromToEvent e) {
        if(e.getBlock().getType()==Material.LAVA) record("lava.flow",map("from",pos(e.getBlock().getLocation()),"to",pos(e.getToBlock().getLocation()),"cancelled",e.isCancelled()));
    }
}
