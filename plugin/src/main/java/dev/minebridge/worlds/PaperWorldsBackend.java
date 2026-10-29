package dev.minebridge.worlds;

import java.util.Objects;
import java.util.UUID;
import org.bukkit.GameRule;
import org.bukkit.NamespacedKey;
import org.bukkit.Registry;
import org.bukkit.Server;
import org.bukkit.World;

/** Ordinary loaded-world Paper API adapter; no NMS, command strings, chunks or background state. */
public final class PaperWorldsBackend implements WorldsService.Backend {
    private final Server server;

    public PaperWorldsBackend(Server server) { this.server = Objects.requireNonNull(server); }

    private void primary() {
        if (!server.isPrimaryThread()) throw new IllegalStateException("Game thread required");
    }

    @Override public WorldsService.WorldAccess findWorld(UUID uuid) {
        primary();
        World world = server.getWorld(uuid);
        return world == null ? null : new PaperWorld(world);
    }

    @Override public WorldsService.WorldAccess findWorld(String nameOrKey) {
        primary();
        World world = server.getWorld(nameOrKey);
        if (world == null && nameOrKey.matches("[a-z0-9_.-]+:[a-z0-9_./-]+")) {
            world = server.getWorld(net.kyori.adventure.key.Key.key(nameOrKey));
        }
        return world == null ? null : new PaperWorld(world);
    }

    @Override public WorldsService.Rule findRule(String key) {
        primary();
        NamespacedKey namespaced = NamespacedKey.fromString(key);
        if (namespaced == null || !key.equals(namespaced.toString())) return null;
        GameRule<?> rule = Registry.GAME_RULE.get(namespaced);
        if (rule == null || !key.equals(rule.getKey().toString())) return null;
        return new PaperRule(rule);
    }

    private record PaperRule(GameRule<?> rule) implements WorldsService.Rule {
        @Override public String key() { return rule.getKey().toString(); }
        @Override public Class<?> valueType() { return rule.getType(); }
    }

    private final class PaperWorld implements WorldsService.WorldAccess {
        private final World world;
        private PaperWorld(World world) { this.world = world; }
        @Override public UUID uuid() { primary(); return world.getUID(); }
        @Override public String name() { primary(); return world.getName(); }
        @Override public String key() { primary(); return world.getKey().toString(); }
        @Override public long time() { primary(); return world.getTime(); }
        @Override public void time(int value) throws WorldFailure {
            primary();
            try { world.setTime(value); }
            catch (IllegalArgumentException unsupported) { throw new WorldFailure("UNSUPPORTED_FEATURE", "not-applied"); }
        }
        @Override public String weather() {
            primary();
            return !world.hasStorm() ? "clear" : world.isThundering() ? "thunder" : "rain";
        }
        @Override public void weather(String value) {
            primary();
            if (value.equals("clear")) {
                world.setThundering(false);
                world.setStorm(false);
            } else if (value.equals("rain")) {
                world.setThundering(false);
                world.setStorm(true);
            } else {
                world.setStorm(true);
                world.setThundering(true);
            }
        }
        @Override public boolean weatherMatches(String value) {
            primary();
            return switch (value) {
                case "clear" -> !world.hasStorm() && !world.isThundering();
                case "rain" -> world.hasStorm() && !world.isThundering();
                case "thunder" -> world.hasStorm() && world.isThundering();
                default -> false;
            };
        }
        @Override public Object rule(WorldsService.Rule rule) {
            primary();
            return world.getGameRuleValue(((PaperRule) rule).rule());
        }
        @Override public boolean rule(WorldsService.Rule rule, Object value) throws WorldFailure {
            primary();
            try { return setRule(((PaperRule) rule).rule(), value); }
            catch (IllegalArgumentException invalid) { throw new WorldFailure("INVALID_RULE_VALUE", "not-applied"); }
        }
        private <T> boolean setRule(GameRule<T> rule, Object value) {
            return world.setGameRule(rule, rule.getType().cast(value));
        }
    }
}
