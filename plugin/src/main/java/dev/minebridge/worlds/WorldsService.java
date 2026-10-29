package dev.minebridge.worlds;

import dev.minebridge.protocol.JsonNumber;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.WorldContext;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/** Bounded main-thread world controls. Each request changes at most one loaded world/rule. */
public final class WorldsService {
    public interface Rule {
        String key();
        Class<?> valueType();
    }

    public interface WorldAccess {
        UUID uuid();
        String name();
        String key();
        long time();
        void time(int value) throws WorldFailure;
        String weather();
        void weather(String value) throws WorldFailure;
        default boolean weatherMatches(String value) { return value.equals(weather()); }
        Object rule(Rule rule) throws WorldFailure;
        boolean rule(Rule rule, Object value) throws WorldFailure;
    }

    public interface Backend {
        WorldAccess findWorld(UUID uuid);
        WorldAccess findWorld(String nameOrKey);
        Rule findRule(String key);
    }

    private static final Set<String> WEATHER = Set.of("clear", "rain", "thunder");
    private final Backend backend;
    private final Runnable requireGameThread;

    public WorldsService(Backend backend, Runnable requireGameThread) {
        this.backend = Objects.requireNonNull(backend);
        this.requireGameThread = Objects.requireNonNull(requireGameThread);
    }

    public Map<String, Object> execute(Request request, WorldContext context) throws WorldFailure {
        requireGameThread.run();
        boolean entered = false;
        try {
            WorldAccess world = world(context, (String) request.params().get("world"));
            return switch (request.method()) {
            case "worlds.getTime" -> Map.of("time", world.time());
            case "worlds.setTime" -> {
                int value = integer(request.params().get("time"), "INVALID_PARAMS");
                if (value < 0 || value > 23999) throw reject("INVALID_PARAMS");
                entered = true;
                world.time(value);
                if (world.time() != value) throw changed();
                yield Map.of("applied", true);
            }
            case "worlds.getWeather" -> Map.of("weather", world.weather());
            case "worlds.setWeather" -> {
                Object value = request.params().get("weather");
                if (!(value instanceof String weather) || !WEATHER.contains(weather)) throw reject("INVALID_WEATHER");
                entered = true;
                world.weather(weather);
                if (!world.weatherMatches(weather)) throw changed();
                yield Map.of("applied", true);
            }
            case "worlds.getGameRule" -> {
                Rule rule = rule(request.params().get("rule"));
                Object value = world.rule(rule);
                if (!rule.valueType().isInstance(value)) throw reject("INVALID_GAME_RULE");
                yield Map.of("rule", rule.key(), "value", value);
            }
            case "worlds.setGameRule" -> {
                Rule rule = rule(request.params().get("rule"));
                Object value = value(rule, request.params().get("value"));
                // A missing/disabled rule is rejected before entering its setter.
                if (!rule.valueType().isInstance(world.rule(rule))) throw reject("INVALID_GAME_RULE");
                entered = true;
                if (!world.rule(rule, value) || !value.equals(world.rule(rule))) throw changed();
                yield Map.of("applied", true);
            }
            default -> throw reject("METHOD_NOT_FOUND");
            };
        } catch (RuntimeException failure) {
            throw new WorldFailure("INTERNAL_ERROR", entered ? "unknown" : "not-applied");
        }
    }

    private WorldAccess world(WorldContext context, String selected) throws WorldFailure {
        if (selected == null || selected.isBlank()) throw reject("INVALID_PARAMS");
        WorldAccess world;
        if (selected.equals(context.name()) || selected.equals(context.key())) {
            world = backend.findWorld(context.uuid());
            if (world == null || !context.uuid().equals(world.uuid())
                    || !context.name().equals(world.name()) || !context.key().equals(world.key())) {
                throw reject("WORLD_NOT_FOUND");
            }
        } else world = backend.findWorld(selected);
        if (world == null) throw reject("WORLD_NOT_FOUND");
        return world;
    }

    private Rule rule(Object key) throws WorldFailure {
        Rule rule = key instanceof String text ? backend.findRule(text) : null;
        if (rule == null || !rule.key().equals(key)
                || rule.valueType() != Boolean.class && rule.valueType() != Integer.class) {
            throw reject("INVALID_GAME_RULE");
        }
        return rule;
    }

    private static Object value(Rule rule, Object value) throws WorldFailure {
        if (rule.valueType() == Boolean.class) {
            if (!(value instanceof Boolean)) throw reject("INVALID_RULE_VALUE");
            return value;
        }
        return integer(value, "INVALID_RULE_VALUE");
    }

    private static int integer(Object value, String code) throws WorldFailure {
        if (!(value instanceof JsonNumber number) || !number.text().matches("-?(0|[1-9][0-9]*)")
                || number.text().length() > 11) throw reject(code);
        try { return Integer.parseInt(number.text()); }
        catch (NumberFormatException invalid) { throw reject(code); }
    }

    private static WorldFailure reject(String code) { return new WorldFailure(code, "not-applied"); }
    private static WorldFailure changed() { return new WorldFailure("WORLD_CHANGE_REJECTED", "unknown"); }
}
