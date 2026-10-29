package dev.minebridge.events;

import static dev.minebridge.events.EventSnapshotCache.*;

import io.papermc.paper.event.player.PrePlayerAttackEntityEvent;

import org.bukkit.Location;
import org.bukkit.Server;
import org.bukkit.block.Block;
import org.bukkit.entity.*;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.block.*;
import org.bukkit.event.entity.*;
import org.bukkit.event.player.*;
import org.bukkit.projectiles.BlockProjectileSource;
import org.bukkit.projectiles.ProjectileSource;

import java.util.*;

/** Native adapters observe facts; no listener waits for Python or invokes a handler. */
public final class PaperGameListener implements Listener, AutoCloseable {
    private record BowContext(long tick, String weapon, String hand, double force) {}

    private static final int MAX_BOW_CONTEXTS = 2048;
    private final LinkedHashMap<UUID, BowContext> bows = new LinkedHashMap<>();
    private final Server server;
    private final EventsService events;
    private final LavaContactMonitor lava;

    public PaperGameListener(Server server, EventsService events) {
        this.server = server;
        this.events = events;
        lava = new LavaContactMonitor(events);
    }

    private void requireThread() {
        if (!server.isPrimaryThread()) throw new IllegalStateException("Game thread required");
    }

    private boolean interested(Entity entity) {
        return events.interestedWorlds().contains(entity.getWorld().getUID());
    }

    private void capture(
            String type,
            Entity subject,
            Map<String, Object> data,
            UUID actor,
            List<Double> point,
            String blockKey) {
        requireThread();
        events.captureGame(type, world(subject.getWorld()), data, actor, point, blockKey);
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onBreak(BlockBreakEvent e) {
        if (!interested(e.getPlayer())) return;
        Block b = e.getBlock();
        capture(
                "block.break",
                e.getPlayer(),
                map(
                        "player",
                        entity(e.getPlayer()),
                        "position",
                        position(b),
                        "block",
                        block(b.getBlockData()),
                        "cancelled",
                        false),
                e.getPlayer().getUniqueId(),
                filterPosition(b),
                b.getType().getKey().toString());
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onPlace(BlockPlaceEvent e) {
        if (!interested(e.getPlayer()) || !e.canBuild()) return;
        Block b = e.getBlockPlaced();
        capture(
                "block.place",
                e.getPlayer(),
                map(
                        "player",
                        entity(e.getPlayer()),
                        "position",
                        position(b),
                        "block",
                        block(b.getBlockData()),
                        "replacedBlock",
                        block(e.getBlockReplacedState().getBlockData()),
                        "cancelled",
                        false),
                e.getPlayer().getUniqueId(),
                filterPosition(b),
                b.getType().getKey().toString());
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onInteract(PlayerInteractEvent e) {
        Block b = e.getClickedBlock();
        if (b == null
                || e.getHand() == null
                || !interested(e.getPlayer())
                || e.getAction() != Action.LEFT_CLICK_BLOCK
                        && e.getAction() != Action.RIGHT_CLICK_BLOCK) return;
        capture(
                "block.interact",
                e.getPlayer(),
                map(
                        "player",
                        entity(e.getPlayer()),
                        "position",
                        position(b),
                        "block",
                        block(b.getBlockData()),
                        "face",
                        e.getBlockFace().name(),
                        "action",
                        e.getAction().name(),
                        "hand",
                        e.getHand().name(),
                        "item",
                        item(e.getItem()),
                        "useInteractedBlock",
                        e.useInteractedBlock().name(),
                        "useItemInHand",
                        e.useItemInHand().name(),
                        "cancelled",
                        e.isCancelled()),
                e.getPlayer().getUniqueId(),
                filterPosition(b),
                b.getType().getKey().toString());
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onAttack(PrePlayerAttackEntityEvent e) {
        if (!interested(e.getPlayer())) return;
        capture(
                "entity.attack",
                e.getPlayer(),
                map(
                        "player",
                        entity(e.getPlayer()),
                        "target",
                        entity(e.getAttacked()),
                        "willAttack",
                        e.willAttack(),
                        "cancelled",
                        e.isCancelled()),
                e.getPlayer().getUniqueId(),
                position(e.getAttacked().getLocation()),
                null);
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onDamage(EntityDamageEvent e) {
        Entity victim = e.getEntity();
        if (!interested(victim)) return;
        capture(
                "entity.damage",
                victim,
                map(
                        "victim",
                        entity(victim),
                        "directSource",
                        entity(e.getDamageSource().getDirectEntity()),
                        "causingEntity",
                        entity(e.getDamageSource().getCausingEntity()),
                        "cause",
                        e.getCause().name(),
                        "rawDamage",
                        e.getDamage(),
                        "finalDamage",
                        e.getFinalDamage(),
                        "cancelled",
                        false),
                victim instanceof Player ? victim.getUniqueId() : null,
                position(victim.getLocation()),
                null);
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onJoin(PlayerJoinEvent e) {
        lava.join(e.getPlayer().getUniqueId());
        if (interested(e.getPlayer()))
            capture(
                    "player.join",
                    e.getPlayer(),
                    Map.of("player", entity(e.getPlayer())),
                    e.getPlayer().getUniqueId(),
                    null,
                    null);
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onQuit(PlayerQuitEvent e) {
        if (interested(e.getPlayer()))
            capture(
                    "player.quit",
                    e.getPlayer(),
                    Map.of("player", entity(e.getPlayer())),
                    e.getPlayer().getUniqueId(),
                    null,
                    null);
        lava.quit(e.getPlayer().getUniqueId());
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onDeath(PlayerDeathEvent e) {
        lava.died(e.getEntity().getUniqueId());
        if (!interested(e.getEntity())) return;
        List<Double> at = position(e.getEntity().getLocation());
        capture(
                "player.death",
                e.getEntity(),
                Map.of("player", entity(e.getEntity()), "position", at),
                e.getEntity().getUniqueId(),
                at,
                null);
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onRespawn(PlayerRespawnEvent e) {
        lava.respawn(e.getPlayer().getUniqueId());
        Location at = e.getRespawnLocation();
        if (!events.interestedWorlds().contains(at.getWorld().getUID())) return;
        events.captureGame(
                "player.respawn",
                world(at.getWorld()),
                map(
                        "player",
                        entity(e.getPlayer()),
                        "reason",
                        e.getRespawnReason().name(),
                        "respawnLocation",
                        map(
                                "world",
                                compactWorld(at.getWorld()),
                                "position",
                                position(at),
                                "yaw",
                                at.getYaw(),
                                "pitch",
                                at.getPitch())),
                e.getPlayer().getUniqueId(),
                position(at),
                null);
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onTeleport(PlayerTeleportEvent e) {
        if (e.getTo() != null && events.interestedWorlds().contains(e.getTo().getWorld().getUID()))
            lava.moved(e.getPlayer().getUniqueId());
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onWorld(PlayerChangedWorldEvent e) {
        if (interested(e.getPlayer())) lava.moved(e.getPlayer().getUniqueId());
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onBow(EntityShootBowEvent e) {
        UUID id = e.getProjectile().getUniqueId();
        if (e.isCancelled() || !interested(e.getEntity())) {
            bows.remove(id);
            return;
        }
        while (bows.size() >= MAX_BOW_CONTEXTS) bows.remove(bows.keySet().iterator().next());
        bows.put(
                id,
                new BowContext(
                        events.tickCounter(),
                        item(e.getBow()),
                        e.getHand() == null ? null : e.getHand().name(),
                        e.getForce()));
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onLaunch(ProjectileLaunchEvent e) {
        Projectile p = e.getEntity();
        BowContext bow = bows.remove(p.getUniqueId());
        if (e.isCancelled() || !interested(p)) return;
        ProjectileSource source = p.getShooter();
        Entity shooter = source instanceof Entity entity ? entity : null;
        capture(
                "projectile.shot",
                p,
                map(
                        "projectile",
                        entity(p),
                        "shooter",
                        entity(shooter),
                        "sourceBlock",
                        source instanceof BlockProjectileSource blockSource
                                ? blockAt(blockSource.getBlock())
                                : null,
                        "position",
                        position(p.getLocation()),
                        "velocity",
                        List.of(
                                p.getVelocity().getX(),
                                p.getVelocity().getY(),
                                p.getVelocity().getZ()),
                        "weapon",
                        bow == null ? null : bow.weapon(),
                        "hand",
                        bow == null ? null : bow.hand(),
                        "force",
                        bow == null ? null : bow.force(),
                        "cancelled",
                        false),
                shooter instanceof Player ? shooter.getUniqueId() : null,
                position(p.getLocation()),
                null);
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onHit(ProjectileHitEvent e) {
        Projectile p = e.getEntity();
        if (!interested(p)) return;
        ProjectileSource source = p.getShooter();
        Entity shooter = source instanceof Entity entity ? entity : null;
        capture(
                "projectile.hit",
                p,
                map(
                        "projectile",
                        entity(p),
                        "shooter",
                        entity(shooter),
                        "sourceBlock",
                        source instanceof BlockProjectileSource blockSource
                                ? blockAt(blockSource.getBlock())
                                : null,
                        "position",
                        position(p.getLocation()),
                        "hitEntity",
                        entity(e.getHitEntity()),
                        "hitBlock",
                        blockAt(e.getHitBlock()),
                        "hitFace",
                        e.getHitBlockFace() == null ? null : e.getHitBlockFace().name(),
                        "cancelled",
                        e.isCancelled()),
                shooter instanceof Player ? shooter.getUniqueId() : null,
                position(p.getLocation()),
                null);
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onRemove(EntityRemoveEvent e) {
        bows.remove(e.getEntity().getUniqueId());
    }

    public void tick() {
        requireThread();
        long now = events.tickCounter();
        bows.entrySet().removeIf(entry -> now - entry.getValue().tick() > 2);
        sampleLava();
    }

    public void sampleLava() {
        requireThread();
        Set<UUID> interested = events.interestedWorlds();
        List<LavaContactMonitor.Sample> samples = new ArrayList<>();
        for (Player player : server.getOnlinePlayers())
            if (interested.contains(player.getWorld().getUID()))
                samples.add(
                        new LavaContactMonitor.Sample(
                                player.getUniqueId(),
                                world(player.getWorld()),
                                player.isInLava(),
                                player.isDead(),
                                position(player.getLocation()),
                                entity(player)));
        lava.tick(samples, interested);
    }

    @Override
    public void close() {
        bows.clear();
        lava.close();
    }
}
