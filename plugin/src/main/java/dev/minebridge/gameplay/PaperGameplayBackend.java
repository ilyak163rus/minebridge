package dev.minebridge.gameplay;

import dev.minebridge.blocks.BlockService;
import dev.minebridge.players.PlayerService;
import net.kyori.adventure.text.Component;
import org.bukkit.Difficulty;
import org.bukkit.Location;
import org.bukkit.NamespacedKey;
import org.bukkit.Registry;
import org.bukkit.Server;
import org.bukkit.World;
import org.bukkit.block.BlockFace;
import org.bukkit.block.data.BlockData;
import org.bukkit.entity.Entity;
import org.bukkit.entity.EntityType;
import org.bukkit.entity.FishHook;
import org.bukkit.entity.Hanging;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Player;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.ItemType;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.potion.PotionEffect;
import org.bukkit.potion.PotionEffectType;
import org.bukkit.util.Vector;

import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/** Public Paper registry, inventory, potion and entity APIs. No commands or NMS. */
public final class PaperGameplayBackend implements GameplayService.Backend {
    private final Server server;
    public PaperGameplayBackend(Server server) { this.server = Objects.requireNonNull(server); }
    private void requireGameThread() {
        if (!server.isPrimaryThread()) throw new IllegalStateException("Game thread required");
    }
    private record PreparedItem(GameplayService.Item specification, ItemStack template) implements GameplayService.PreparedItem {}
    private record PreparedEffect(PotionEffect effect) implements GameplayService.PreparedEffect {}
    private record PreparedSpawn(EntityType type, PreparedItem item, BlockData block, BlockFace face, UUID owner)
            implements GameplayService.PreparedSpawn {}

    @Override public GameplayService.PreparedItem prepareItem(GameplayService.Item item) throws GameplayFailure {
        requireGameThread(); NamespacedKey key = NamespacedKey.fromString(item.key());
        ItemType type = key == null ? null : Registry.ITEM.get(key);
        if (type == null || !item.key().equals(type.getKey().toString()) || type == ItemType.AIR) throw new GameplayFailure("INVALID_ITEM");
        ItemStack stack = type.createItemStack(1);
        ItemMeta meta = stack.getItemMeta();
        if (item.name() != null) meta.displayName(Component.text(item.name()));
        if (item.lore() != null) meta.lore(item.lore().stream().map(Component::text).toList());
        stack.setItemMeta(meta);
        return new PreparedItem(item, stack);
    }
    @Override public GameplayService.PreparedEffect prepareEffect(GameplayService.Effect effect) throws GameplayFailure {
        requireGameThread(); NamespacedKey key = NamespacedKey.fromString(effect.key());
        PotionEffectType type = key == null ? null : Registry.MOB_EFFECT.get(key);
        if (type == null || !effect.key().equals(type.getKey().toString())) throw new GameplayFailure("INVALID_EFFECT");
        return new PreparedEffect(new PotionEffect(type, effect.durationTicks(), effect.level() - 1, false, effect.particles()));
    }
    @Override public GameplayService.PreparedSpawn prepareSpawn(String key, GameplayService.SpawnOptions options,
                                                                 BlockService.WorldAccess world) throws GameplayFailure {
        requireGameThread(); NamespacedKey namespaced = NamespacedKey.fromString(key);
        EntityType type = namespaced == null ? null : Registry.ENTITY_TYPE.get(namespaced);
        if (type == null || !key.equals(type.getKey().toString())) throw new GameplayFailure("INVALID_ENTITY_TYPE");
        if (type == EntityType.PLAYER || type.getEntityClass() == null) throw new GameplayFailure("UNSUPPORTED_ENTITY_TYPE");
        boolean item = type == EntityType.ITEM, falling = type == EntityType.FALLING_BLOCK;
        boolean hanging = type == EntityType.PAINTING || type == EntityType.ITEM_FRAME || type == EntityType.GLOW_ITEM_FRAME;
        boolean fishing = type == EntityType.FISHING_BOBBER;
        if (item != (options.item() != null) || falling != (options.blockKey() != null)
                || hanging != (options.face() != null) || fishing != (options.owner() != null)) throw new GameplayFailure("INVALID_ENTITY_TYPE");
        PreparedItem preparedItem = item ? (PreparedItem) prepareItem(options.item()) : null;
        if (preparedItem != null && options.item().amount() > preparedItem.template().getMaxStackSize()) throw new GameplayFailure("INVALID_ITEM");
        BlockData data = null;
        if (falling) {
            StringBuilder text = new StringBuilder(options.blockKey());
            if (!options.blockStates().isEmpty()) {
                text.append('['); options.blockStates().entrySet().stream().sorted(Map.Entry.comparingByKey()).forEach(e -> text.append(e.getKey()).append('=').append(e.getValue()).append(','));
                text.setCharAt(text.length() - 1, ']');
            }
            try { data = server.createBlockData(text.toString()); }
            catch (IllegalArgumentException invalid) { throw new GameplayFailure("INVALID_BLOCK"); }
            if (data.getMaterial().isAir()) throw new GameplayFailure("INVALID_BLOCK");
        }
        BlockFace face = hanging ? BlockFace.valueOf(options.face().toUpperCase(Locale.ROOT)) : null;
        if (type == EntityType.PAINTING && (face == BlockFace.UP || face == BlockFace.DOWN)) throw new GameplayFailure("INVALID_ENTITY_TYPE");
        UUID owner = null;
        if (fishing) {
            Player player = player(options.owner());
            if (player == null || !player.isOnline()) throw new GameplayFailure("PLAYER_NOT_FOUND");
            if (!player.getWorld().getUID().equals(world.uuid())) throw new GameplayFailure("CONTEXT_WORLD_MISMATCH");
            owner = player.getUniqueId();
        }
        return new PreparedSpawn(type, preparedItem, data, face, owner);
    }
    private Player player(String identifier) {
        try { return server.getPlayer(UUID.fromString(identifier)); }
        catch (IllegalArgumentException notUuid) { return server.getPlayerExact(identifier); }
    }
    @Override public GameplayService.GiveOperation give(PlayerService.Player target, GameplayService.PreparedItem prepared, boolean drop) {
        requireGameThread(); return new Give(target.uuid(), (PreparedItem) prepared, drop);
    }
    private final class Give implements GameplayService.GiveOperation {
        final UUID uuid; final PreparedItem item; final boolean drop;
        int remaining, given, dropped, leftovers; boolean done; String code;
        Give(UUID uuid, PreparedItem item, boolean drop) { this.uuid = uuid; this.item = item; this.drop = drop; remaining = item.specification().amount(); }
        @Override public void step(int pieces) {
            requireGameThread();
            while (!done && pieces-- > 0) {
                Player player = server.getPlayer(uuid);
                if (player == null || !player.isOnline()) { leftovers += remaining; remaining = 0; code = "PLAYER_NOT_FOUND"; done = true; break; }
                int amount = Math.min(remaining, item.template().getMaxStackSize());
                ItemStack stack = item.template().clone(); stack.setAmount(amount);
                Map<Integer, ItemStack> unused = player.getInventory().addItem(stack);
                int unusedAmount = unused.values().stream().mapToInt(ItemStack::getAmount).sum();
                given += amount - unusedAmount; remaining -= amount;
                for (ItemStack rest : unused.values()) {
                    if (drop) {
                        org.bukkit.entity.Item entity = player.getWorld().dropItemNaturally(player.getLocation(), rest);
                        // A cancelled ItemSpawnEvent returns an invalid item; return that quantity to the caller.
                        if (entity.isValid()) dropped += rest.getAmount(); else leftovers += rest.getAmount();
                    } else leftovers += rest.getAmount();
                }
                if (remaining == 0) done = true;
            }
        }
        @Override public boolean done() { return done; }
        @Override public GameplayService.GiveResult result() {
            if (!done) throw new IllegalStateException("Give operation is pending");
            return new GameplayService.GiveResult(code == null, code, item.specification().amount(), given,
                    leftovers == 0 ? List.of() : List.of(item.specification().withAmount(leftovers)), dropped);
        }
    }
    @Override public boolean addEffect(PlayerService.Target target, GameplayService.PreparedEffect prepared) throws GameplayFailure {
        return living(target).addPotionEffect(((PreparedEffect) prepared).effect());
    }
    @Override public boolean removeEffect(PlayerService.Target target, GameplayService.PreparedEffect prepared) throws GameplayFailure {
        LivingEntity living = living(target); PotionEffectType type = ((PreparedEffect) prepared).effect().getType();
        living.removePotionEffect(type);
        return !living.hasPotionEffect(type);
    }
    @Override public boolean clearEffects(PlayerService.Target target) throws GameplayFailure {
        LivingEntity living = living(target);
        living.clearActivePotionEffects();
        return living.getActivePotionEffects().isEmpty();
    }
    private LivingEntity living(PlayerService.Target target) throws GameplayFailure {
        requireGameThread(); Entity entity = server.getEntity(target.uuid());
        if (entity == null || !entity.isValid() || entity.isDead()) throw new GameplayFailure(target instanceof PlayerService.Player ? "PLAYER_NOT_FOUND" : "ENTITY_NOT_FOUND");
        if (!(entity instanceof LivingEntity living)) throw new GameplayFailure("INVALID_TARGET");
        return living;
    }
    @Override public void validateSpawnLocation(BlockService.WorldAccess access, double x, double y, double z,
                                                GameplayService.PreparedSpawn prepared) throws GameplayFailure {
        requireGameThread(); PreparedSpawn spawn = (PreparedSpawn) prepared;
        World world = server.getWorld(access.uuid());
        if (world == null) throw new GameplayFailure("WORLD_NOT_FOUND");
        // Recheck after asynchronous chunk loading and before the spawn mutation.
        PeacefulSpawnPolicy.requireAllowed(spawn.type().getKey().toString(), world.getDifficulty() == Difficulty.PEACEFUL);
        if (spawn.owner() != null) {
            Player owner = server.getPlayer(spawn.owner());
            if (owner == null || !owner.isOnline()) throw new GameplayFailure("PLAYER_NOT_FOUND");
            if (!owner.getWorld().equals(world)) throw new GameplayFailure("CONTEXT_WORLD_MISMATCH");
        }
        if (spawn.face() != null) {
            org.bukkit.block.Block at = world.getBlockAt((int) Math.floor(x), (int) Math.floor(y), (int) Math.floor(z));
            if (!at.getType().isAir() || !at.getRelative(spawn.face().getOppositeFace()).getType().isSolid()) throw new GameplayFailure("INVALID_ENTITY_TYPE");
        }
    }
    @Override public GameplayService.Entity spawn(BlockService.WorldAccess access, double x, double y, double z,
                                                   GameplayService.PreparedSpawn prepared) throws GameplayFailure {
        requireGameThread(); PreparedSpawn spawn = (PreparedSpawn) prepared;
        World world = Objects.requireNonNull(server.getWorld(access.uuid())); Location at = new Location(world, x, y, z);
        Entity entity;
        if (spawn.type() == EntityType.ITEM) {
            ItemStack stack = spawn.item().template().clone(); stack.setAmount(spawn.item().specification().amount());
            entity = world.dropItem(at, stack);
        } else if (spawn.type() == EntityType.FALLING_BLOCK) entity = world.spawnFallingBlock(at, spawn.block());
        else if (spawn.type() == EntityType.LIGHTNING_BOLT) entity = world.strikeLightning(at);
        else if (spawn.type() == EntityType.FISHING_BOBBER) {
            Player owner = Objects.requireNonNull(server.getPlayer(spawn.owner()));
            FishHook hook = owner.launchProjectile(FishHook.class, new Vector());
            if (!hook.teleport(at)) { hook.remove(); throw new GameplayFailure("INVALID_ENTITY_TYPE"); }
            entity = hook;
        } else if (spawn.face() != null) {
            entity = world.spawnEntity(at, spawn.type(), org.bukkit.event.entity.CreatureSpawnEvent.SpawnReason.CUSTOM,
                    value -> {
                        if (value instanceof org.bukkit.entity.Painting painting) painting.setArt(org.bukkit.Art.KEBAB, true);
                        ((Hanging) value).setFacingDirection(spawn.face(), true);
                    });
        } else entity = world.spawnEntity(at, spawn.type());
        if (!entity.isValid()) throw new GameplayFailure("INVALID_ENTITY_TYPE");
        return new GameplayService.Entity(entity.getUniqueId(), entity.getEntityId(), entity.getType().getKey().toString(), entity instanceof LivingEntity);
    }
}
