package dev.minebridge.players;

import dev.minebridge.blocks.BlockService;
import net.kyori.adventure.key.Key;
import net.kyori.adventure.text.Component;
import org.bukkit.Location;
import org.bukkit.Server;
import org.bukkit.World;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.entity.LivingEntity;
import org.bukkit.event.player.PlayerTeleportEvent;
import org.bukkit.GameMode;
import org.bukkit.attribute.Attribute;
import org.bukkit.attribute.AttributeInstance;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.CompletionStage;

/** Public Paper APIs only; selectors never become dispatched commands. */
public final class PaperPlayerBackend implements PlayerService.Backend {
    private final Server server;
    private final BlockService.Backend worlds;
    public PaperPlayerBackend(Server server, BlockService.Backend worlds) { this.server = server; this.worlds = worlds; }
    private void requireGameThread() {
        if (!server.isPrimaryThread()) throw new IllegalStateException("Game thread required");
    }
    @Override public PlayerService.Player findPlayer(String nameOrUuid) {
        requireGameThread();
        Player player;
        try { player = server.getPlayer(UUID.fromString(nameOrUuid)); }
        catch (IllegalArgumentException notUuid) { player = server.getPlayerExact(nameOrUuid); }
        return player == null || !player.isOnline() ? null : new PaperPlayer(player);
    }
    @Override public List<PlayerService.Target> select(String selector, PlayerService.Player executor) {
        requireGameThread();
        List<Entity> selected = server.selectEntities(executor == null ? server.getConsoleSender() : ((PaperPlayer) executor).player, selector);
        List<PlayerService.Target> result = new ArrayList<>(selected.size());
        for (Entity entity : selected) result.add(wrap(entity));
        return result;
    }
    @Override public PlayerService.Target findTarget(UUID uuid) {
        requireGameThread(); Entity entity = server.getEntity(uuid);
        return entity == null ? null : wrap(entity);
    }
    private PlayerService.Target wrap(Entity entity) {
        return entity instanceof Player player ? new PaperPlayer(player) : new PaperTarget(entity);
    }
    private final class PaperTarget implements PlayerService.Target {
        private final Entity entity;
        private PaperTarget(Entity entity) { this.entity = entity; }
        @Override public UUID uuid() { requireGameThread(); return entity.getUniqueId(); }
        @Override public boolean living() { requireGameThread(); return entity instanceof LivingEntity; }
        @Override public boolean valid() { requireGameThread(); return entity.isValid() && !entity.isDead(); }
    }
    @Override public BlockService.WorldAccess findWorld(String nameOrKey) {
        requireGameThread();
        World world = server.getWorld(nameOrKey);
        if (world == null && nameOrKey.matches("[a-z0-9_.-]+:[a-z0-9_./-]+")) world = server.getWorld(Key.key(nameOrKey));
        return world == null ? null : worlds.findWorld(world.getUID());
    }
    @Override public void broadcast(String message) {
        requireGameThread(); Component text = Component.text(message);
        for (Player player : server.getOnlinePlayers()) player.sendMessage(text);
        server.getConsoleSender().sendMessage(text);
    }
    private final class PaperPlayer implements PlayerService.Player {
        private final Player player;
        private PaperPlayer(Player player) { this.player = player; }
        @Override public UUID uuid() { requireGameThread(); return player.getUniqueId(); }
        @Override public String name() { requireGameThread(); return player.getName(); }
        @Override public int entityId() { requireGameThread(); return player.getEntityId(); }
        @Override public boolean online() { requireGameThread(); return player.isOnline(); }
        @Override public String gameMode() { requireGameThread(); return player.getGameMode().name().toLowerCase(Locale.ROOT); }
        @Override public void gameMode(String mode) { requireGameThread(); player.setGameMode(GameMode.valueOf(mode.toUpperCase(Locale.ROOT))); }
        @Override public double health() { requireGameThread(); return player.getHealth(); }
        @Override public double maxHealth() {
            requireGameThread(); AttributeInstance maximum = player.getAttribute(Attribute.MAX_HEALTH);
            if (maximum == null) throw new IllegalStateException("Player has no health attribute");
            // The native health and maximum-health accessor both use float precision.
            return (double) (float) maximum.getValue();
        }
        @Override public void health(double value) { requireGameThread(); player.setHealth(value); }
        @Override public int foodLevel() { requireGameThread(); return player.getFoodLevel(); }
        @Override public void foodLevel(int value) { requireGameThread(); player.setFoodLevel(value); }
        @Override public PlayerService.Position position() {
            requireGameThread(); Location at = player.getLocation(); World world = Objects.requireNonNull(at.getWorld());
            return new PlayerService.Position(world.getName(), world.getUID(), at.x(), at.y(), at.z(), at.getYaw(), at.getPitch());
        }
        @Override public CompletionStage<Boolean> teleport(BlockService.WorldAccess world, double x, double y, double z, float yaw, float pitch) {
            requireGameThread(); World destination = Objects.requireNonNull(server.getWorld(world.uuid()));
            return player.teleportAsync(new Location(destination, x, y, z, yaw, pitch), PlayerTeleportEvent.TeleportCause.PLUGIN);
        }
    }
}
