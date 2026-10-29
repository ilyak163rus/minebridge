package dev.minebridge.catalog;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.Registry;
import org.bukkit.World;
import org.bukkit.block.BlockFace;
import org.bukkit.entity.Entity;
import org.bukkit.entity.EntityType;
import org.bukkit.entity.Hanging;
import org.bukkit.inventory.ItemStack;
import org.bukkit.plugin.java.JavaPlugin;

/** Disposable pinned-registry and public spawn API probe, never a production plugin. */
@SuppressWarnings({"deprecation", "removal"})
public final class GameRegistryExport extends JavaPlugin {
    @Override public void onEnable() {
        Bukkit.getScheduler().runTask(this, () -> {
            try {
                JsonObject result = new JsonObject();
                result.addProperty("formatVersion", 1);
                result.addProperty("minecraftVersion", Bukkit.getMinecraftVersion());
                result.addProperty("serverVersion", Bukkit.getVersion());
                result.addProperty("bukkitVersion", Bukkit.getBukkitVersion());
                JsonArray items = new JsonArray();
                Registry.ITEM.stream().sorted(Comparator.comparing(t -> t.getKey().toString()))
                    .forEach(type -> {
                        JsonObject row = new JsonObject();
                        row.addProperty("key", type.getKey().toString());
                        row.addProperty("maxStackSize", type.getMaxStackSize());
                        items.add(row);
                    });
                result.add("items", items);
                JsonArray effects = new JsonArray();
                Registry.MOB_EFFECT.stream().sorted(Comparator.comparing(t -> t.getKey().toString()))
                    .forEach(type -> {
                        JsonObject row = new JsonObject();
                        row.addProperty("key", type.getKey().toString());
                        row.addProperty("instant", type.isInstant());
                        effects.add(row);
                    });
                result.add("effects", effects);
                World world = Bukkit.getWorlds().getFirst();
                world.getChunkAt(0, 0).load();
                Location location = new Location(world, 8.5, 100, 8.5);
                JsonArray entities = new JsonArray();
                Registry.ENTITY_TYPE.stream().sorted(Comparator.comparing(t -> t.getKey().toString()))
                    .forEach(type -> {
                        JsonObject row = new JsonObject();
                        row.addProperty("key", type.getKey().toString());
                        row.addProperty("bukkitName", type.name());
                        row.addProperty("entityClass", type.getEntityClass() == null ? null : type.getEntityClass().getName());
                        row.addProperty("spawnableFlag", type.isSpawnable());
                        row.addProperty("alive", type.isAlive());
                        row.add("genericProbe", probe(type, () -> world.spawnEntity(location, type)));
                        String category = "generic";
                        String adapter = "World.spawnEntity(Location, EntityType)";
                        JsonArray parameters = new JsonArray();
                        String reason = "Generic creation was tested in a loaded Overworld chunk; persistence and gameplay depend on the entity.";
                        if (type == EntityType.LIGHTNING_BOLT) {
                            category = "special"; adapter = "World.strikeLightning(Location)";
                            reason = "Real lightning strike, not visual-only lightning effect.";
                            row.add("adapterProbe", probe(type, () -> world.strikeLightning(location)));
                        } else if (type == EntityType.ITEM) {
                            category = "special"; adapter = "World.dropItem(Location, ItemStack)";
                            parameters.add("item");
                            reason = "The item payload is explicit instead of the generic API's default stone stack.";
                            row.add("adapterProbe", probe(type, () -> world.dropItem(location, new ItemStack(Material.DIAMOND, 2))));
                        } else if (type == EntityType.FALLING_BLOCK) {
                            category = "special"; adapter = "World.spawnFallingBlock(Location, BlockData)";
                            parameters.add("block");
                            reason = "The falling block's block data is explicit instead of reading a block at the spawn coordinates.";
                            row.add("adapterProbe", probe(type, () -> world.spawnFallingBlock(location, Material.SAND.createBlockData())));
                        } else if (type == EntityType.PAINTING || type == EntityType.ITEM_FRAME || type == EntityType.GLOW_ITEM_FRAME) {
                            category = "special"; adapter = "World.spawn(Location, type.getEntityClass(), Consumer<Hanging>)";
                            parameters.add("face");
                            reason = "A cardinal facing direction is explicit. Minecraft can later remove the entity if support is unsuitable.";
                            row.add("adapterProbe", probe(type, () -> world.spawn(location, type.getEntityClass(), entity -> ((Hanging) entity).setFacingDirection(BlockFace.NORTH, true))));
                        } else if (type == EntityType.FISHING_BOBBER) {
                            category = "special"; adapter = "Player.launchProjectile(FishHook.class, Vector, Consumer) then same-world teleport";
                            parameters.add("owner");
                            reason = "Public projectile launch API requires an online player owner. The owner must remain online and hold a fishing rod for persistence.";
                            JsonObject ownerProbe = new JsonObject();
                            ownerProbe.addProperty("status", "requires-online-player");
                            ownerProbe.addProperty("evidence", "Pinned CraftLivingEntity.launchProjectile bytecode has an explicit FishHook branch restricted to Player; integration tests supply actual players.");
                            row.add("adapterProbe", ownerProbe);
                        } else if (type == EntityType.PLAYER) {
                            category = "unsupported"; adapter = null;
                            reason = "Player entities are created by Minecraft login; the public Paper entity spawn API has no player spawn function.";
                        } else if (!row.getAsJsonObject("genericProbe").get("status").getAsString().equals("created")) {
                            throw new IllegalStateException("Unclassified public spawn failure: " + row);
                        }
                        row.addProperty("spawnCategory", category);
                        row.addProperty("adapter", adapter);
                        row.add("requiredParameters", parameters);
                        row.addProperty("reason", reason);
                        entities.add(row);
                    });
                result.add("entities", entities);
                Files.writeString(Path.of("game-registry-export.json"), new GsonBuilder().serializeNulls()
                    .setPrettyPrinting().create().toJson(result) + "\n", StandardCharsets.UTF_8);
                getLogger().info("GAME_CATALOG_EXPORT_COMPLETE items=" + items.size()
                    + " effects=" + effects.size() + " entities=" + entities.size());
            } catch (Exception failure) {
                getLogger().log(java.util.logging.Level.SEVERE, "Game catalog export failed", failure);
            } finally {
                Bukkit.shutdown();
            }
        });
    }

    private JsonObject probe(EntityType type, java.util.function.Supplier<Entity> spawn) {
        JsonObject result = new JsonObject();
        Entity entity = null;
        try {
            entity = spawn.get();
            if (entity == null) throw new IllegalStateException("Spawn returned null");
            result.addProperty("status", "created");
            result.addProperty("actualType", entity.getType().getKey().toString());
            result.addProperty("validAtReturn", entity.isValid());
            if (entity.getType() != type) throw new IllegalStateException("Wrong actual type " + entity.getType());
        } catch (Exception failure) {
            result.addProperty("status", "rejected");
            result.addProperty("exception", failure.getClass().getName());
            result.addProperty("message", failure.getMessage());
        } finally {
            if (entity != null) entity.remove();
        }
        return result;
    }
}
