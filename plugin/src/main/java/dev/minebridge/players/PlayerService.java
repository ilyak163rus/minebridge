package dev.minebridge.players;

import dev.minebridge.blocks.BlockFailure;
import dev.minebridge.blocks.BlockService;
import dev.minebridge.session.WorldContext;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletionStage;

/** Game-thread player boundary. The vanilla backend owns selector syntax and selection. */
public final class PlayerService {
    public interface Target {
        UUID uuid();
        default boolean living() { return false; }
        default boolean valid() { return true; }
    }
    public interface Player extends Target {
        String name();
        int entityId();
        boolean online();
        @Override default boolean living() { return true; }
        @Override default boolean valid() { return online(); }
        Position position();
        CompletionStage<Boolean> teleport(BlockService.WorldAccess world, double x, double y, double z,
                                           float yaw, float pitch);
        default String gameMode() { throw new UnsupportedOperationException(); }
        default void gameMode(String mode) { throw new UnsupportedOperationException(); }
        default double health() { throw new UnsupportedOperationException(); }
        default double maxHealth() { throw new UnsupportedOperationException(); }
        default void health(double value) { throw new UnsupportedOperationException(); }
        default int foodLevel() { throw new UnsupportedOperationException(); }
        default void foodLevel(int value) { throw new UnsupportedOperationException(); }
    }
    public interface Backend {
        Player findPlayer(String nameOrUuid);
        default Target findTarget(UUID uuid) { return findPlayer(uuid.toString()); }
        List<Target> select(String selector, Player executor) throws IllegalArgumentException;
        BlockService.WorldAccess findWorld(String nameOrKey);
        void broadcast(String message);
    }
    public record Position(String world, UUID worldUuid, double x, double y, double z, float yaw, float pitch) {
        public Map<String, Object> toProtocol() {
            return Map.of("world", world, "x", x, "y", y, "z", z, "yaw", yaw, "pitch", pitch);
        }
    }
    public record Selection(List<Player> players) {
        public Selection { players = List.copyOf(players); }
    }
    private final Backend backend;
    private final BlockService blocks;
    private final Runnable requireGameThread;
    private final TargetResolver resolver;

    public PlayerService(Backend backend, BlockService blocks, Runnable requireGameThread) {
        this.backend = backend; this.blocks = blocks; this.requireGameThread = requireGameThread;
        this.resolver = new TargetResolver(backend, blocks, requireGameThread);
    }
    public TargetResolver resolver() { return resolver; }
    public void validateWorld(WorldContext context, String world) throws BlockFailure {
        requireGameThread.run(); blocks.world(context, world);
    }
    public Player get(String nameOrUuid) throws PlayerFailure {
        requireGameThread.run();
        Player player = backend.findPlayer(nameOrUuid);
        if (player == null || !player.online()) throw new PlayerFailure("PLAYER_NOT_FOUND");
        return player;
    }
    public Map<String, Object> dto(Player player) {
        return Map.of("uuid", player.uuid().toString(), "name", player.name(), "entityId", player.entityId());
    }
    public Selection select(WorldContext context, String requestedWorld, String executor, Object targets)
            throws PlayerFailure, BlockFailure {
        return new Selection(resolver.select(context, requestedWorld, executor, targets, TargetResolver.Kind.PLAYERS)
                .stream().map(target -> (Player) target).toList());
    }
    public Position getPosition(Selection selected) throws PlayerFailure {
        requireGameThread.run();
        return single(selected).position();
    }
    private Player single(Selection selected) throws PlayerFailure {
        requireGameThread.run();
        if (selected.players.size() != 1) throw new PlayerFailure("INVALID_TARGET");
        return selected.players.getFirst();
    }
    public String getGameMode(Selection selected) throws PlayerFailure { return single(selected).gameMode(); }
    public double getHealth(Selection selected) throws PlayerFailure { return single(selected).health(); }
    public int getFoodLevel(Selection selected) throws PlayerFailure { return single(selected).foodLevel(); }

    /** Validate the complete selection before the first player is modified. */
    public void validateControl(Selection selected, String method, String mode, double value) throws PlayerFailure {
        requireGameThread.run();
        if (method.equals("players.setGameMode")) {
            if (mode == null || !List.of("survival", "creative", "adventure", "spectator").contains(mode))
                throw new PlayerFailure("INVALID_GAME_MODE");
        } else if (method.equals("players.setHealth")) {
            double effective = effectiveHealth(value);
            if (!Double.isFinite(value) || value < 0 || !Double.isFinite(effective)
                    || value > 0 && effective == 0) throw new PlayerFailure("INVALID_PLAYER_VALUE");
            for (Player player : selected.players) {
                double maximum = player.maxHealth();
                if (!Double.isFinite(maximum) || maximum <= 0 || effective > maximum)
                    throw new PlayerFailure("INVALID_PLAYER_VALUE");
            }
        } else if (method.equals("players.setFoodLevel")) {
            if (!Double.isFinite(value) || value < 0 || value > 20 || value != Math.floor(value))
                throw new PlayerFailure("INVALID_PLAYER_VALUE");
        } else throw new IllegalArgumentException("Unknown player control");
    }

    /** Readback handles cancelled/clamped void setters without pretending they succeeded. */
    public boolean applyControl(Player target, String method, String mode, double value) {
        requireGameThread.run();
        return switch (method) {
            case "players.setGameMode" -> { target.gameMode(mode); yield mode.equals(target.gameMode()); }
            case "players.setHealth" -> {
                // Attributes or game state may have changed since whole-group prevalidation.
                double effective = effectiveHealth(value);
                if (effective > target.maxHealth()) yield false;
                target.health(effective); yield Double.compare(target.health(), effective) == 0;
            }
            case "players.setFoodLevel" -> { target.foodLevel((int) value); yield target.foodLevel() == (int) value; }
            default -> throw new IllegalArgumentException("Unknown player control");
        };
    }
    private static double effectiveHealth(double value) { return value == 0 ? 0 : (double) (float) value; }
    public BlockService.WorldAccess destination(WorldContext context, String requestedWorld, String destination,
                                               double x, double y, double z) throws PlayerFailure, BlockFailure {
        validateWorld(context, requestedWorld);
        BlockService.WorldAccess world = destination == null ? blocks.world(context, requestedWorld) : backend.findWorld(destination);
        if (world == null) throw new PlayerFailure("WORLD_NOT_FOUND");
        if (y < world.minY() || y >= world.maxYExclusive() || !world.insideBorder(x, z)) {
            throw new PlayerFailure("COORDINATE_OUT_OF_BOUNDS");
        }
        return world;
    }
    public void broadcast(String message) { requireGameThread.run(); backend.broadcast(message); }

    record SelectorContext(boolean executor, boolean origin) {}
    /** Only classifies context requirements; Paper still parses every selector and argument value.
     * Quoted text and nested NBT/components cannot introduce spurious top-level spatial keys.
     */
    static SelectorContext contextNeeded(String selector) {
        boolean self = selector.startsWith("@s");
        boolean origin = selector.startsWith("@p") || selector.startsWith("@n");
        int open = selector.indexOf('[');
        if (open >= 0) {
            int depth = 0, start = open + 1;
            char quote = 0; boolean escape = false;
            for (int i = start; i <= selector.length(); i++) {
                char c = i == selector.length() ? ',' : selector.charAt(i);
                if (quote != 0) {
                    if (escape) escape = false;
                    else if (c == '\\') escape = true;
                    else if (c == quote) quote = 0;
                } else if (c == '\'' || c == '"') quote = c;
                else if (c == '[' || c == '{' || c == '(') depth++;
                else if (c == ']' && depth == 0 || c == ',' && depth == 0) {
                    String field = selector.substring(start, i).trim();
                    int equals = field.indexOf('=');
                    if (equals >= 0) {
                        String key = field.substring(0, equals).trim();
                        // Brigadier accepts quoted argument names as well as ordinary identifiers.
                        if (key.length() >= 2 && (key.charAt(0) == '"' || key.charAt(0) == '\'')
                                && key.charAt(key.length() - 1) == key.charAt(0)) key = key.substring(1, key.length() - 1);
                        String value = field.substring(equals + 1).trim();
                        if (List.of("x", "y", "z", "dx", "dy", "dz", "distance").contains(key)
                                || key.equals("sort") && (value.equals("nearest") || value.equals("furthest"))) origin = true;
                    }
                    start = i + 1;
                    if (c == ']') break;
                } else if (c == ']' || c == '}' || c == ')') depth--;
            }
        }
        return new SelectorContext(self || origin, origin);
    }
}
