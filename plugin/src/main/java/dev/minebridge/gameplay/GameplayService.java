package dev.minebridge.gameplay;

import dev.minebridge.blocks.BlockService;
import dev.minebridge.players.PlayerService;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Opaque prepared server values keep Paper out of scheduling and deterministic service tests. */
public final class GameplayService {
    public record Item(String key, int amount, String name, List<String> lore) {
        public Item { lore = lore == null ? null : List.copyOf(lore); }
        public Map<String, Object> toProtocol() {
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("key", key); result.put("amount", amount); result.put("name", name); result.put("lore", lore);
            return result;
        }
        public Item withAmount(int value) { return new Item(key, value, name, lore); }
    }
    public record Effect(String key, int durationTicks, int level, boolean particles) {}
    public record SpawnOptions(Item item, String blockKey, Map<String, String> blockStates, String face, String owner) {
        public SpawnOptions { blockStates = blockStates == null ? null : Map.copyOf(blockStates); }
    }
    public record Entity(UUID uuid, int entityId, String key, boolean living) {
        public Map<String, Object> toProtocol() {
            return Map.of("uuid", uuid.toString(), "entityId", entityId, "key", key, "living", living);
        }
    }
    public record GiveResult(boolean applied, String code, int requested, int given, List<Item> leftovers, int dropped) {
        public GiveResult { leftovers = List.copyOf(leftovers); }
        public Map<String, Object> toProtocol(UUID target) {
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("uuid", target.toString()); result.put("applied", applied); result.put("code", code);
            result.put("requested", requested); result.put("given", given);
            result.put("leftovers", leftovers.stream().map(Item::toProtocol).toList()); result.put("dropped", dropped);
            return result;
        }
    }
    public interface PreparedItem {}
    public interface PreparedEffect {}
    public interface PreparedSpawn {}
    public interface GiveOperation {
        /** Bounded stack pieces; called only on the game thread, never retries a completed mutation. */
        void step(int pieces);
        boolean done();
        GiveResult result();
    }
    public interface Backend {
        PreparedItem prepareItem(Item item) throws GameplayFailure;
        PreparedEffect prepareEffect(Effect effect) throws GameplayFailure;
        PreparedSpawn prepareSpawn(String key, SpawnOptions options, BlockService.WorldAccess world) throws GameplayFailure;
        default void validateSpawnLocation(BlockService.WorldAccess world, double x, double y, double z, PreparedSpawn spawn) throws GameplayFailure {}
        GiveOperation give(PlayerService.Player target, PreparedItem item, boolean drop);
        boolean addEffect(PlayerService.Target target, PreparedEffect effect) throws GameplayFailure;
        default PreparedEffect prepareEffectRemoval(String key) throws GameplayFailure {
            return prepareEffect(new Effect(key, 1, 1, false));
        }
        default boolean removeEffect(PlayerService.Target target, PreparedEffect effect) throws GameplayFailure { throw new UnsupportedOperationException(); }
        default boolean clearEffects(PlayerService.Target target) throws GameplayFailure { throw new UnsupportedOperationException(); }
        Entity spawn(BlockService.WorldAccess world, double x, double y, double z, PreparedSpawn spawn) throws GameplayFailure;
    }
    private final Backend backend;
    private final Runnable requireGameThread;
    public GameplayService(Backend backend, Runnable requireGameThread) { this.backend = backend; this.requireGameThread = requireGameThread; }
    public PreparedItem item(Item item) throws GameplayFailure { requireGameThread.run(); return backend.prepareItem(item); }
    public PreparedEffect effect(Effect effect) throws GameplayFailure { requireGameThread.run(); return backend.prepareEffect(effect); }
    public PreparedSpawn spawn(String key, SpawnOptions options, BlockService.WorldAccess world) throws GameplayFailure {
        requireGameThread.run(); return backend.prepareSpawn(key, options, world);
    }
    public GiveOperation give(PlayerService.Player target, PreparedItem item, boolean drop) {
        requireGameThread.run(); return backend.give(target, item, drop);
    }
    public boolean addEffect(PlayerService.Target target, PreparedEffect effect) throws GameplayFailure {
        requireGameThread.run(); return backend.addEffect(target, effect);
    }
    public PreparedEffect effectRemoval(String key) throws GameplayFailure { requireGameThread.run(); return backend.prepareEffectRemoval(key); }
    public boolean removeEffect(PlayerService.Target target, PreparedEffect effect) throws GameplayFailure {
        requireGameThread.run(); return backend.removeEffect(target, effect);
    }
    public boolean clearEffects(PlayerService.Target target) throws GameplayFailure { requireGameThread.run(); return backend.clearEffects(target); }
    public Entity spawn(BlockService.WorldAccess world, double x, double y, double z, PreparedSpawn spawn) throws GameplayFailure {
        requireGameThread.run(); return backend.spawn(world, x, y, z, spawn);
    }
    public void validateSpawnLocation(BlockService.WorldAccess world, double x, double y, double z, PreparedSpawn spawn) throws GameplayFailure {
        requireGameThread.run(); backend.validateSpawnLocation(world, x, y, z, spawn);
    }
}
