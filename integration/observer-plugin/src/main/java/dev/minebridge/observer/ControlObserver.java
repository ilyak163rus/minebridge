package dev.minebridge.observer;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import org.bukkit.GameRule;
import org.bukkit.World;
import org.bukkit.attribute.Attribute;
import org.bukkit.attribute.AttributeInstance;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityPotionEffectEvent;
import org.bukkit.event.player.PlayerGameModeChangeEvent;
import org.bukkit.event.weather.ThunderChangeEvent;
import org.bukkit.event.weather.WeatherChangeEvent;

/** Independent console-only I01 oracle and deterministic cancellation fixture. */
final class ControlObserver implements Listener {
    private final ObserverPlugin plugin;
    private UUID modeTarget, effectTarget, weatherWorld;
    private int modeCancelled, effectCancelled, weatherCancelled, thunderCancelled;
    private final List<Object> cancellationEvents = new ArrayList<>();

    ControlObserver(ObserverPlugin plugin) { this.plugin = plugin; }

    Map<String, Object> execute(String[] args) {
        requireGameThread();
        return switch (args[2]) {
            case "controlPlayer" -> { length(args, 4); yield playerState(player(args[3])); }
            case "controlWorld" -> { length(args, 4); yield worldState(world(args[3])); }
            case "controlRule" -> rule(args);
            case "controlHealthFixture" -> healthFixture(args);
            case "controlCancel" -> cancel(args);
            case "controlState" -> { length(args, 3); yield state(); }
            default -> throw new IllegalArgumentException();
        };
    }

    private Map<String, Object> playerState(Player player) {
        AttributeInstance maximum = player.getAttribute(Attribute.MAX_HEALTH);
        if (maximum == null) throw new IllegalStateException();
        List<Object> effects = player.getActivePotionEffects().stream().map(effect -> (Object) map(
                "key", effect.getType().getKey().toString(), "durationTicks", effect.getDuration(),
                "amplifier", effect.getAmplifier(), "level", effect.getAmplifier() + 1,
                "ambient", effect.isAmbient(), "particles", effect.hasParticles(), "icon", effect.hasIcon())).toList();
        return map("uuid", player.getUniqueId().toString(), "name", player.getName(),
                "entityId", player.getEntityId(), "world", player.getWorld().getName(),
                "worldUuid", player.getWorld().getUID().toString(),
                "gameMode", player.getGameMode().name().toLowerCase(Locale.ROOT),
                "health", player.getHealth(), "maxHealth", player.getMaxHealth(),
                "maxHealthBase", maximum.getBaseValue(), "foodLevel", player.getFoodLevel(),
                "saturation", (double) player.getSaturation(), "absorption", player.getAbsorptionAmount(),
                "dead", player.isDead(), "online", player.isOnline(), "effects", effects);
    }

    private Map<String, Object> worldState(World world) {
        return map("uuid", world.getUID().toString(), "name", world.getName(),
                "time", world.getTime(), "fullTime", world.getFullTime(), "gameTime", world.getGameTime(),
                "storm", world.hasStorm(), "thundering", world.isThundering(),
                "weatherDuration", world.getWeatherDuration(), "thunderDuration", world.getThunderDuration(),
                "clearWeatherDuration", world.getClearWeatherDuration());
    }

    private Map<String, Object> rule(String[] args) {
        length(args, 5); World world = world(args[3]);
        for (GameRule<?> rule : GameRule.values()) {
            if (rule.getKey().toString().equals(args[4]) || rule.getName().equals(args[4])) return map("uuid", world.getUID().toString(),
                    "rule", rule.getKey().toString(), "value", world.getGameRuleValue(rule),
                    "valueType", rule.getType() == Boolean.class ? "bool" : "int");
        }
        throw new IllegalArgumentException();
    }

    private Map<String, Object> healthFixture(String[] args) {
        length(args, 6); Player player = player(args[3]);
        double maximum = finite(args[4]), health = finite(args[5]);
        if (maximum <= 0 || maximum > 1024 || health < 0 || health > maximum
                || !Float.isFinite((float) maximum) || !Float.isFinite((float) health)
                || health > 0 && (float) health == 0) throw new IllegalArgumentException();
        AttributeInstance attribute = player.getAttribute(Attribute.MAX_HEALTH);
        if (attribute == null) throw new IllegalStateException();
        attribute.setBaseValue(maximum);
        double actualMaximum = player.getMaxHealth();
        if ((double) (float) health > actualMaximum) throw new IllegalArgumentException();
        player.setHealth((double) (float) health);
        return playerState(player);
    }

    private Map<String, Object> cancel(String[] args) {
        length(args, 5);
        switch (args[3]) {
            case "gameMode" -> modeTarget = player(args[4]).getUniqueId();
            case "effectRemove" -> {
                try { effectTarget = UUID.fromString(args[4]); }
                catch (IllegalArgumentException notUuid) { effectTarget = player(args[4]).getUniqueId(); }
            }
            case "weather" -> weatherWorld = world(args[4]).getUID();
            case "reset" -> {
                if (!args[4].equals("all")) throw new IllegalArgumentException();
                close();
            }
            default -> throw new IllegalArgumentException();
        }
        return state();
    }

    private Map<String, Object> state() {
        return map("gameModeTarget", modeTarget == null ? null : modeTarget.toString(),
                "effectRemoveTarget", effectTarget == null ? null : effectTarget.toString(),
                "weatherWorld", weatherWorld == null ? null : weatherWorld.toString(),
                "modeCancelled", modeCancelled, "effectCancelled", effectCancelled,
                "weatherCancelled", weatherCancelled, "thunderCancelled", thunderCancelled,
                "events", new ArrayList<>(cancellationEvents));
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void mode(PlayerGameModeChangeEvent event) {
        requireGameThread();
        if (event.getPlayer().getUniqueId().equals(modeTarget)) {
            event.setCancelled(true); modeCancelled++;
            record(map("kind", "gameMode", "uuid", modeTarget.toString(),
                    "requested", event.getNewGameMode().name().toLowerCase(Locale.ROOT), "cancelled", true));
        }
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void effect(EntityPotionEffectEvent event) {
        requireGameThread();
        if (event.getEntity().getUniqueId().equals(effectTarget)
                && (event.getAction() == EntityPotionEffectEvent.Action.REMOVED
                    || event.getAction() == EntityPotionEffectEvent.Action.CLEARED)) {
            event.setCancelled(true); effectCancelled++;
            record(map("kind", "effectRemove", "uuid", effectTarget.toString(),
                    "action", event.getAction().name(), "cause", event.getCause().name(),
                    "key", event.getOldEffect() == null ? null : event.getOldEffect().getType().getKey().toString(),
                    "cancelled", true));
        }
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void weather(WeatherChangeEvent event) {
        requireGameThread();
        if (event.getWorld().getUID().equals(weatherWorld)) {
            event.setCancelled(true); weatherCancelled++;
            record(map("kind", "weather", "uuid", weatherWorld.toString(),
                    "requested", event.toWeatherState(), "cancelled", true));
        }
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void thunder(ThunderChangeEvent event) {
        requireGameThread();
        if (event.getWorld().getUID().equals(weatherWorld)) {
            event.setCancelled(true); thunderCancelled++;
            record(map("kind", "thunder", "uuid", weatherWorld.toString(),
                    "requested", event.toThunderState(), "cancelled", true));
        }
    }

    private void record(Map<String, Object> event) {
        if (cancellationEvents.size() < 32) cancellationEvents.add(event);
    }
    void close() {
        modeTarget = effectTarget = weatherWorld = null;
        modeCancelled = effectCancelled = weatherCancelled = thunderCancelled = 0;
        cancellationEvents.clear();
    }
    private Player player(String value) {
        Player player;
        try { player = plugin.getServer().getPlayer(UUID.fromString(value)); }
        catch (IllegalArgumentException notUuid) { player = plugin.getServer().getPlayerExact(value); }
        if (player == null || !player.isOnline()) throw new IllegalArgumentException();
        return player;
    }
    private World world(String value) {
        World world = plugin.getServer().getWorld(UUID.fromString(value));
        if (world == null) throw new IllegalArgumentException();
        return world;
    }
    private void requireGameThread() {
        if (!plugin.getServer().isPrimaryThread()) throw new IllegalStateException("Game thread required");
    }
    private static void length(String[] args, int length) { if (args.length != length) throw new IllegalArgumentException(); }
    private static double finite(String value) {
        double result = Double.parseDouble(value);
        if (!Double.isFinite(result)) throw new IllegalArgumentException();
        return result;
    }
    private static Map<String, Object> map(Object... values) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < values.length; i += 2) result.put((String) values[i], values[i + 1]);
        return result;
    }
}
