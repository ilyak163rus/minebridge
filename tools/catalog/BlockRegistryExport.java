package dev.minebridge.catalog;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import org.bukkit.Bukkit;
import org.bukkit.Material;
import org.bukkit.Registry;
import org.bukkit.block.data.BlockData;
import org.bukkit.plugin.java.JavaPlugin;

/** Disposable local catalog exporter. No production plugin, RPC or listener. */
@SuppressWarnings({"deprecation", "removal"})
public final class BlockRegistryExport extends JavaPlugin {
    @Override public void onEnable() {
        Bukkit.getScheduler().runTask(this, () -> {
            try {
                JsonObject result = new JsonObject();
                result.addProperty("formatVersion", 1);
                result.addProperty("minecraftVersion", Bukkit.getMinecraftVersion());
                result.addProperty("serverVersion", Bukkit.getVersion());
                result.addProperty("bukkitVersion", Bukkit.getBukkitVersion());
                JsonArray blocks = new JsonArray();
                Registry.BLOCK.stream().sorted(Comparator.comparing(b -> b.getKey().toString()))
                    .forEach(type -> {
                        JsonObject row = new JsonObject();
                        row.addProperty("key", type.getKey().toString());
                        row.addProperty("defaultBlockData", type.createBlockData().getAsString());
                        blocks.add(row);
                    });
                result.add("blocks", blocks);
                JsonArray legacy = new JsonArray();
                JsonArray requested = JsonParser.parseString(Files.readString(
                    Path.of("legacy-pairs.json"), StandardCharsets.UTF_8)).getAsJsonArray();
                for (var requestedValue : requested) {
                    JsonObject pair = requestedValue.getAsJsonObject();
                    int id = pair.get("id").getAsInt(), data = pair.get("data").getAsInt();
                    Material material = null;
                    // Modern-plugin bytecode rewrites Material.values() to hide legacy values.
                    // Reflection deliberately inspects the historical constants for this offline export.
                    for (var field : Material.class.getFields()) {
                        if (!field.getName().startsWith("LEGACY_")) continue;
                        Material candidate = (Material) field.get(null);
                        if (candidate.getId() == id) {
                            material = candidate;
                            break;
                        }
                    }
                    if (material == null) throw new IllegalStateException("Missing legacy ID " + id);
                    BlockData converted = Bukkit.getUnsafe().fromLegacy(material, (byte) data);
                    JsonObject row = new JsonObject();
                    row.addProperty("id", id);
                    row.addProperty("data", data);
                    row.addProperty("legacyMaterial", material.name());
                    row.addProperty("blockData", converted.getAsString());
                    legacy.add(row);
                }
                result.add("legacyConversions", legacy);
                Files.writeString(Path.of("block-registry-export.json"),
                    new GsonBuilder().setPrettyPrinting().create().toJson(result) + "\n", StandardCharsets.UTF_8);
                getLogger().info("CATALOG_EXPORT_COMPLETE blocks=" + blocks.size()
                    + " legacyPairs=" + legacy.size());
            } catch (Exception failure) {
                getLogger().log(java.util.logging.Level.SEVERE, "Catalog export failed", failure);
            } finally {
                Bukkit.shutdown();
            }
        });
    }
}
