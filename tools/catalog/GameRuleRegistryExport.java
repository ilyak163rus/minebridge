package dev.minebridge.catalog;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import org.bukkit.Bukkit;
import org.bukkit.GameRule;
import org.bukkit.GameRules;
import org.bukkit.Registry;
import org.bukkit.plugin.java.JavaPlugin;

/** Disposable read-only exporter; runs inside the root's single acceptance server. */
@SuppressWarnings({"deprecation", "removal"})
public final class GameRuleRegistryExport extends JavaPlugin {
    @Override public void onEnable() {
        Bukkit.getScheduler().runTask(this, () -> {
            try { export(); }
            catch (ReflectiveOperationException | java.io.IOException | RuntimeException failure) {
                getLogger().severe("Pinned gamerule export failed: " + failure.getClass().getSimpleName());
            }
        });
    }

    private void export() throws ReflectiveOperationException, java.io.IOException {
        JsonObject root = new JsonObject();
        root.addProperty("formatVersion", 1);
        root.addProperty("minecraftVersion", Bukkit.getMinecraftVersion());
        root.addProperty("serverVersion", Bukkit.getVersion());
        root.addProperty("bukkitVersion", Bukkit.getBukkitVersion());
        root.addProperty("paperBuild", 133);
        try (var resource = getResource("provenance.json")) {
            if (resource == null) throw new IllegalStateException("Missing provenance");
            root.add("source", com.google.gson.JsonParser.parseString(new String(resource.readAllBytes(), StandardCharsets.UTF_8)));
        }
        Map<GameRule<?>, String> names = new IdentityHashMap<>();
        for (Field field : GameRules.class.getFields()) {
            if (Modifier.isStatic(field.getModifiers()) && field.getType() == GameRule.class) {
                names.put((GameRule<?>) field.get(null), field.getName());
            }
        }
        Map<GameRule<?>, List<String>> aliases = new IdentityHashMap<>();
        JsonArray omitted = new JsonArray();
        List<Field> oldFields = java.util.Arrays.stream(GameRule.class.getFields())
                .filter(field -> Modifier.isStatic(field.getModifiers()) && field.getType() == GameRule.class)
                .sorted(Comparator.comparing(Field::getName)).toList();
        for (Field field : oldFields) {
            GameRule<?> rule = (GameRule<?>) field.get(null);
            if (names.containsKey(rule)) {
                if (!field.getName().equals(names.get(rule))) aliases.computeIfAbsent(rule, ignored -> new ArrayList<>()).add(field.getName());
            } else {
                JsonObject row = new JsonObject();
                row.addProperty("constant", field.getName());
                row.addProperty("modernKey", rule.getKey().toString());
                row.addProperty("legacyValueType", kind(rule));
                row.addProperty("reason", "Legacy conversion/inversion wrapper is not the canonical registry object; no silent alias.");
                omitted.add(row);
            }
        }
        JsonArray rules = new JsonArray();
        Registry.GAME_RULE.stream().sorted(Comparator.comparing(rule -> rule.getKey().toString())).forEach(rule -> {
            String name = names.get(rule);
            if (name == null) throw new IllegalStateException("Canonical rule has no GameRules field");
            JsonObject row = new JsonObject();
            row.addProperty("constant", name);
            row.addProperty("key", rule.getKey().toString());
            row.addProperty("valueType", kind(rule));
            Object value = rule.getDefaultValue();
            if (value instanceof Boolean bool) row.addProperty("defaultValue", bool);
            else if (value instanceof Integer integer) row.addProperty("defaultValue", integer);
            else throw new IllegalStateException("Unexpected rule value type");
            JsonArray oldNames = new JsonArray();
            aliases.getOrDefault(rule, List.of()).stream().sorted().forEach(oldNames::add);
            row.add("aliases", oldNames);
            rules.add(row);
        });
        root.add("rules", rules);
        root.add("unsupportedLegacyAliases", omitted);
        Files.createDirectories(getDataFolder().toPath());
        Files.writeString(getDataFolder().toPath().resolve("gamerules.json"),
                new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create().toJson(root) + "\n", StandardCharsets.UTF_8);
        getLogger().info("Pinned gamerule snapshot written; canonical rules=" + rules.size());
    }

    private static String kind(GameRule<?> rule) {
        if (rule.getType() == Boolean.class) return "bool";
        if (rule.getType() == Integer.class) return "int";
        throw new IllegalStateException("Unexpected gamerule type");
    }
}
