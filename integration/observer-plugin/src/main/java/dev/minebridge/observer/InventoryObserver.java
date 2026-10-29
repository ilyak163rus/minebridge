package dev.minebridge.observer;

import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer;
import org.bukkit.Material;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.block.Chest;
import org.bukkit.block.ShulkerBox;
import org.bukkit.block.data.BlockData;
import org.bukkit.enchantments.Enchantment;
import org.bukkit.entity.Player;
import org.bukkit.inventory.DoubleChestInventory;
import org.bukkit.inventory.EquipmentSlot;
import org.bukkit.inventory.Inventory;
import org.bukkit.inventory.InventoryHolder;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.PlayerInventory;
import org.bukkit.inventory.meta.BlockStateMeta;
import org.bukkit.inventory.meta.ItemMeta;

/** Test-only console oracle: reads real inventories, never bridge descriptors or service state. */
final class InventoryObserver {
    private final ObserverPlugin plugin;

    InventoryObserver(ObserverPlugin plugin) { this.plugin = plugin; }

    Map<String, Object> execute(String[] a) {
        if (!plugin.getServer().isPrimaryThread()) throw new IllegalStateException();
        return switch (a[2]) {
            case "i04Chest" -> {
                World w = world(a[3]); int x = integer(a[4]), y = integer(a[5]), z = integer(a[6]);
                String material = Material.valueOf(a[7]).getKey().toString();
                if (!List.of("minecraft:chest", "minecraft:trapped_chest").contains(material)) throw new IllegalArgumentException();
                boolean combined = Boolean.parseBoolean(a[8]);
                for (int dx = -1; dx <= 2; dx++) w.getBlockAt(x + dx, y, z).setType(Material.AIR, false);
                w.getBlockAt(x, y, z).setBlockData(plugin.getServer().createBlockData(material + "[facing=north,type=" + (combined ? "left" : "single") + ",waterlogged=false]"), false);
                if (combined) w.getBlockAt(x + 1, y, z).setBlockData(plugin.getServer().createBlockData(material + "[facing=north,type=right,waterlogged=false]"), false);
                yield chest(w, x, y, z, combined);
            }
            case "i04ReadChest" -> chest(world(a[3]), integer(a[4]), integer(a[5]), integer(a[6]), Boolean.parseBoolean(a[7]));
            case "i04Split" -> {
                World w = world(a[3]); int x = integer(a[4]), y = integer(a[5]), z = integer(a[6]);
                Block anchor = w.getBlockAt(x, y, z); String material = anchor.getType().getKey().toString();
                w.getBlockAt(x + 1, y, z).setType(Material.AIR, false);
                anchor.setBlockData(plugin.getServer().createBlockData(material + "[facing=north,type=single,waterlogged=false]"), false);
                yield chest(w, x, y, z, false);
            }
            case "i04Merge" -> {
                World w = world(a[3]); int x = integer(a[4]), y = integer(a[5]), z = integer(a[6]);
                Block anchor = w.getBlockAt(x, y, z); String material = anchor.getType().getKey().toString();
                w.getBlockAt(x + 1, y, z).setBlockData(plugin.getServer().createBlockData(material + "[facing=north,type=right,waterlogged=false]"), false);
                anchor.setBlockData(plugin.getServer().createBlockData(material + "[facing=north,type=left,waterlogged=false]"), false);
                yield chest(w, x, y, z, true);
            }
            case "i04Player" -> player(player(a[3]));
            case "i04EmptyPlayer" -> {
                Player p = player(a[3]); p.getInventory().clear();
                yield player(p);
            }
            case "i04Hidden" -> {
                Player p = player(a[3]); Map<String, Object> supported = new LinkedHashMap<>();
                for (EquipmentSlot slot : List.of(EquipmentSlot.BODY, EquipmentSlot.SADDLE)) {
                    try {
                        p.getInventory().setItem(slot, new ItemStack(slot == EquipmentSlot.BODY ? Material.LEATHER_HORSE_ARMOR : Material.SADDLE));
                        supported.put(slot.name().toLowerCase(), map("supported", true, "item", item(p.getInventory().getItem(slot))));
                    } catch (IllegalArgumentException | UnsupportedOperationException unavailable) {
                        supported.put(slot.name().toLowerCase(), map("supported", false));
                    }
                }
                yield supported;
            }
            case "i04Fixture" -> {
                Inventory inv = inventory(a[3]); Object slot = slot(a[4]); String type = a[5];
                ItemStack value = fixture(type); set(inv, slot, value);
                yield map("slot", slot, "item", item(get(inv, slot)));
            }
            case "i04FillLong" -> {
                Inventory inv = inventory(a[3]); ItemStack value = fixture("long");
                for (int i = 0; i < inv.getSize(); i++) inv.setItem(i, value.clone());
                yield map("size", inv.getSize(), "first", item(inv.getItem(0)));
            }
            case "i04Chunk" -> {
                World w = world(a[3]); int x = integer(a[4]), z = integer(a[5]);
                yield map("loaded", w.isChunkLoaded(x, z), "x", x, "z", z);
            }
            case "i04Unload" -> {
                World w = world(a[3]); int x = integer(a[4]), z = integer(a[5]);
                boolean requested = !w.isChunkLoaded(x, z) || w.unloadChunk(x, z, true);
                yield map("requested", requested, "loaded", w.isChunkLoaded(x, z), "x", x, "z", z);
            }
            default -> throw new IllegalArgumentException();
        };
    }

    private ItemStack fixture(String type) {
        ItemStack stack = new ItemStack(type.equals("shulker") ? Material.SHULKER_BOX : Material.DIAMOND, 1);
        ItemMeta meta = stack.getItemMeta();
        switch (type) {
            case "enchanted" -> stack.addUnsafeEnchantment(Enchantment.SHARPNESS, 5);
            case "rich" -> {
                meta.displayName(Component.text("Rich name", NamedTextColor.GOLD));
                meta.lore(List.of(Component.text("Rich lore", NamedTextColor.BLUE)));
                stack.setItemMeta(meta);
            }
            case "long" -> {
                meta.displayName(Component.text("N".repeat(300)));
                List<Component> lines = new ArrayList<>();
                for (int i = 0; i < 20; i++) lines.add(Component.text("\u0001".repeat(300)));
                meta.lore(lines); stack.setItemMeta(meta);
            }
            case "shulker" -> {
                BlockStateMeta blockMeta = (BlockStateMeta) meta;
                ShulkerBox box = (ShulkerBox) blockMeta.getBlockState();
                box.getInventory().setItem(0, new ItemStack(Material.EMERALD, 7));
                blockMeta.setBlockState(box); stack.setItemMeta(blockMeta);
            }
            case "plain" -> {
                meta.displayName(Component.text("Plain name")); meta.lore(List.of(Component.text("Plain lore")));
                stack.setItemMeta(meta);
            }
            default -> throw new IllegalArgumentException();
        }
        return stack;
    }

    private Inventory inventory(String token) {
        String[] parts = token.split(":");
        if (parts[0].equals("P") && parts.length == 2) return player(parts[1]).getInventory();
        if (parts[0].equals("C") && parts.length == 6) {
            World world = world(parts[1]); int x = integer(parts[2]), z = integer(parts[4]);
            loadChestNeighbors(world, x, z);
            Chest chest = (Chest) world.getBlockAt(x, integer(parts[3]), z).getState();
            return Boolean.parseBoolean(parts[5]) ? chest.getInventory() : chest.getBlockInventory();
        }
        throw new IllegalArgumentException();
    }

    private Map<String, Object> chest(World world, int x, int y, int z, boolean combined) {
        // This console oracle may explicitly load its fixture chunks. A
        // cross-chunk double chest otherwise looks like one half after the
        // bridge correctly releases its per-RPC tickets. Chunk-state probes
        // below never call this helper or load anything implicitly.
        loadChestNeighbors(world, x, z);
        Block block = world.getBlockAt(x, y, z);
        if (!(block.getState() instanceof Chest chest)) return map("exists", false, "key", block.getType().getKey().toString());
        Inventory inv = combined ? chest.getInventory() : chest.getBlockInventory();
        List<Object> layout = new ArrayList<>();
        if (inv instanceof DoubleChestInventory doubleChest) {
            layout.add(part(doubleChest.getLeftSide(), 0)); layout.add(part(doubleChest.getRightSide(), 27));
        } else layout.add(map("position", List.of(x, y, z), "offset", 0, "size", 27, "key", block.getType().getKey().toString()));
        List<Object> slots = new ArrayList<>();
        for (int i = 0; i < inv.getSize(); i++) slots.add(map("slot", i, "item", item(inv.getItem(i))));
        return map("exists", true, "size", inv.getSize(), "position", List.of(x, y, z), "layout", layout, "slots", slots);
    }

    private static void loadChestNeighbors(World world, int x, int z) {
        for (int[] offset : new int[][]{{0,0},{-1,0},{1,0},{0,-1},{0,1}})
            world.getChunkAt(Math.floorDiv(x + offset[0], 16), Math.floorDiv(z + offset[1], 16));
    }

    private Map<String, Object> part(Inventory inv, int offset) {
        InventoryHolder holder = inv.getHolder();
        if (!(holder instanceof Chest chest)) throw new IllegalStateException();
        Block b = chest.getBlock();
        return map("position", List.of(b.getX(), b.getY(), b.getZ()), "offset", offset, "size", inv.getSize(), "key", b.getType().getKey().toString());
    }

    private Map<String, Object> player(Player player) {
        PlayerInventory inv = player.getInventory(); List<Object> slots = new ArrayList<>();
        for (int i = 0; i < 36; i++) slots.add(map("slot", i, "item", item(inv.getItem(i))));
        for (String name : List.of("head", "chest", "legs", "feet", "off_hand")) slots.add(map("slot", name, "item", item(inv.getItem(EquipmentSlot.valueOf(name.toUpperCase())))));
        Map<String, Object> hidden = new LinkedHashMap<>();
        for (EquipmentSlot slot : List.of(EquipmentSlot.BODY, EquipmentSlot.SADDLE)) {
            try { hidden.put(slot.name().toLowerCase(), map("supported", true, "item", item(inv.getItem(slot)))); }
            catch (IllegalArgumentException | UnsupportedOperationException unavailable) { hidden.put(slot.name().toLowerCase(), map("supported", false)); }
        }
        return map("uuid", player.getUniqueId().toString(), "size", inv.getSize(), "slots", slots, "hidden", hidden);
    }

    private static Object slot(String slot) {
        try { return Integer.valueOf(slot); }
        catch (NumberFormatException name) { return slot; }
    }
    private static ItemStack get(Inventory inventory, Object slot) {
        return slot instanceof Integer index ? inventory.getItem(index) : ((PlayerInventory) inventory).getItem(EquipmentSlot.valueOf(((String) slot).toUpperCase()));
    }
    private static void set(Inventory inventory, Object slot, ItemStack item) {
        if (slot instanceof Integer index) inventory.setItem(index, item);
        else ((PlayerInventory) inventory).setItem(EquipmentSlot.valueOf(((String) slot).toUpperCase()), item);
    }
    private static Map<String, Object> item(ItemStack stack) {
        if (stack == null || stack.isEmpty()) return null;
        ItemMeta meta = stack.getItemMeta();
        String name = meta.displayName() == null ? null : PlainTextComponentSerializer.plainText().serialize(meta.displayName());
        List<Component> lore = meta.lore(); List<Integer> lengths = new ArrayList<>();
        if (lore != null) for (Component line : lore) lengths.add(PlainTextComponentSerializer.plainText().serialize(line).codePointCount(0, PlainTextComponentSerializer.plainText().serialize(line).length()));
        try {
            return map("key", stack.getType().getKey().toString(), "amount", stack.getAmount(), "maxStack", stack.getMaxStackSize(),
                    "name", name == null ? null : name.substring(0, Math.min(name.length(), 40)), "nameLength", name == null ? 0 : name.codePointCount(0, name.length()),
                    "loreLines", lore == null ? 0 : lore.size(), "loreLengths", lengths, "enchantments", stack.getEnchantments().size(),
                    "blockState", meta instanceof BlockStateMeta b && b.hasBlockState(),
                    "sha256", HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(stack.serializeAsBytes())));
        } catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(); }
    }
    private Player player(String name) {
        Player player;
        try { player = plugin.getServer().getPlayer(UUID.fromString(name)); }
        catch (IllegalArgumentException notUuid) { player = plugin.getServer().getPlayerExact(name); }
        if (player == null) throw new IllegalArgumentException(); return player;
    }
    private World world(String uuid) { World world = plugin.getServer().getWorld(UUID.fromString(uuid)); if (world == null) throw new IllegalArgumentException(); return world; }
    private static int integer(String value) { return Integer.parseInt(value); }
    private static Map<String, Object> map(Object... pairs) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
        return result;
    }
}
