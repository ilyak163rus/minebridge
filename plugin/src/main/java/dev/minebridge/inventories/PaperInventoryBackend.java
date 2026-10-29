package dev.minebridge.inventories;

import static dev.minebridge.inventories.InventoryService.map;

import dev.minebridge.blocks.BlockService;
import dev.minebridge.blocks.PaperBlockBackend;
import dev.minebridge.gameplay.GameplayService;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer;

import org.bukkit.NamespacedKey;
import org.bukkit.Registry;
import org.bukkit.Server;
import org.bukkit.World;
import org.bukkit.block.Chest;
import org.bukkit.entity.Player;
import org.bukkit.inventory.DoubleChestInventory;
import org.bukkit.inventory.EquipmentSlot;
import org.bukkit.inventory.Inventory;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.ItemType;
import org.bukkit.inventory.PlayerInventory;
import org.bukkit.inventory.meta.ItemMeta;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/** Public Paper API implementation; no commands, NBT transport or synthetic inventory events. */
public final class PaperInventoryBackend implements InventoryService.Backend {
    private final Server server;
    private final PaperBlockBackend blocks;
    private static final PlainTextComponentSerializer PLAIN =
            PlainTextComponentSerializer.plainText();

    public PaperInventoryBackend(Server server, PaperBlockBackend blocks) {
        this.server = Objects.requireNonNull(server);
        this.blocks = Objects.requireNonNull(blocks);
    }

    private void requireThread() {
        if (!server.isPrimaryThread()) throw new IllegalStateException("Game thread required");
    }

    @Override
    public BlockService.WorldAccess world(UUID uuid) {
        requireThread();
        return blocks.findWorld(uuid);
    }

    @Override
    public InventoryService.Handle player(UUID uuid) throws InventoryFailure {
        requireThread();
        Player player = server.getPlayer(uuid);
        if (player == null || !player.isOnline()) throw new InventoryFailure("PLAYER_NOT_FOUND");
        return new PlayerHandle(player);
    }

    @Override
    public InventoryService.Handle chest(
            BlockService.WorldAccess access, int x, int y, int z, boolean combined)
            throws InventoryFailure {
        requireThread();
        World world = server.getWorld(access.uuid());
        if (world == null) throw new InventoryFailure("WORLD_NOT_FOUND");
        // Chunk leases were acquired before any BlockState/DoubleChest lookup.
        if (!(world.getBlockAt(x, y, z).getState() instanceof Chest chest))
            throw new InventoryFailure("INVENTORY_NOT_FOUND");
        Inventory inventory = combined ? chest.getInventory() : chest.getBlockInventory();
        List<Map<String, Object>> parts = new ArrayList<>();
        if (inventory instanceof DoubleChestInventory joined) {
            parts.add(part(joined.getLeftSide(), 0));
            parts.add(part(joined.getRightSide(), 27));
        } else parts.add(part(chest.getBlockInventory(), 0));
        List<Object> slots = new ArrayList<>();
        for (int i = 0; i < inventory.getSize(); i++) slots.add(i);
        Map<String, Object> descriptor =
                map(
                        "kind",
                        "chest",
                        "world",
                        world.getUID().toString(),
                        "position",
                        List.of(x, y, z),
                        "combined",
                        combined,
                        "size",
                        inventory.getSize(),
                        "slots",
                        List.copyOf(slots),
                        "layout",
                        List.copyOf(parts));
        return new ChestHandle(inventory, descriptor, List.copyOf(slots));
    }

    private Map<String, Object> part(Inventory inventory, int offset) throws InventoryFailure {
        if (!(inventory.getHolder(false) instanceof Chest chest) || inventory.getSize() != 27)
            throw new InventoryFailure("INVENTORY_CHANGED");
        return map(
                "position",
                List.of(chest.getX(), chest.getY(), chest.getZ()),
                "offset",
                offset,
                "size",
                27,
                "key",
                chest.getType().getKey().toString());
    }

    private record Prepared(ItemStack template) implements InventoryService.PreparedItem {
        @Override
        public int amount() {
            return template.getAmount();
        }

        @Override
        public int maxStackSize() {
            return template.getMaxStackSize();
        }
    }

    @Override
    public InventoryService.PreparedItem item(GameplayService.Item specification)
            throws InventoryFailure {
        requireThread();
        NamespacedKey key = NamespacedKey.fromString(specification.key());
        ItemType type = key == null ? null : Registry.ITEM.get(key);
        if (type == null
                || type == ItemType.AIR
                || !type.getKey().toString().equals(specification.key()))
            throw new InventoryFailure("INVALID_ITEM");
        if (specification.amount() < 1) throw new InventoryFailure("INVALID_ITEM_AMOUNT");
        ItemStack item = type.createItemStack(1);
        if (specification.amount() > item.getMaxStackSize())
            throw new InventoryFailure("INVALID_ITEM_AMOUNT");
        ItemMeta meta = item.getItemMeta();
        if (specification.name() != null) meta.displayName(Component.text(specification.name()));
        if (specification.lore() != null)
            meta.lore(specification.lore().stream().map(Component::text).toList());
        item.setItemMeta(meta);
        item.setAmount(specification.amount());
        return new Prepared(item);
    }

    private abstract class BaseHandle implements InventoryService.Handle {
        abstract ItemStack get(Object slot) throws InventoryFailure;

        abstract void set(Object slot, ItemStack item) throws InventoryFailure;

        @Override
        public InventoryService.ItemView read(Object slot) throws InventoryFailure {
            requireThread();
            return itemView(get(slot));
        }

        @Override
        public void write(Object slot, InventoryService.PreparedItem item) throws InventoryFailure {
            requireThread();
            set(slot, ((Prepared) item).template().clone());
        }

        @Override
        public void clear(Object slot) throws InventoryFailure {
            requireThread();
            set(slot, null);
        }

        @Override
        public boolean matches(Object slot, InventoryService.PreparedItem item)
                throws InventoryFailure {
            requireThread();
            return ((Prepared) item).template().equals(get(slot));
        }

        @Override
        public boolean empty(Object slot) throws InventoryFailure {
            requireThread();
            ItemStack item = get(slot);
            return item == null || item.isEmpty();
        }
    }

    private final class PlayerHandle extends BaseHandle {
        private final Player player;

        PlayerHandle(Player player) {
            this.player = player;
        }

        private PlayerInventory live() throws InventoryFailure {
            if (!player.isOnline() || server.getPlayer(player.getUniqueId()) != player)
                throw new InventoryFailure("PLAYER_NOT_FOUND");
            return player.getInventory();
        }

        @Override
        public Map<String, Object> descriptor() {
            return InventoryService.playerDescriptor(player.getUniqueId());
        }

        @Override
        public List<Object> slots() {
            return InventoryService.PLAYER_SLOTS;
        }

        @Override
        public int maxStackSize(Object slot) {
            return slot instanceof String name && !name.equals("off_hand")
                    ? 1
                    : player.getInventory().getMaxStackSize();
        }

        @Override
        ItemStack get(Object slot) throws InventoryFailure {
            PlayerInventory inventory = live();
            return slot instanceof Integer index
                    ? inventory.getItem(index)
                    : inventory.getItem(equipment((String) slot));
        }

        @Override
        void set(Object slot, ItemStack item) throws InventoryFailure {
            PlayerInventory inventory = live();
            if (slot instanceof Integer index) inventory.setItem(index, item);
            else inventory.setItem(equipment((String) slot), item);
        }
    }

    private final class ChestHandle extends BaseHandle {
        private final Inventory inventory;
        private final Map<String, Object> descriptor;
        private final List<Object> slots;

        ChestHandle(Inventory inventory, Map<String, Object> descriptor, List<Object> slots) {
            this.inventory = inventory;
            this.descriptor = descriptor;
            this.slots = slots;
        }

        @Override
        public Map<String, Object> descriptor() {
            return descriptor;
        }

        @Override
        public List<Object> slots() {
            return slots;
        }

        @Override
        public int maxStackSize(Object slot) {
            return inventory.getMaxStackSize();
        }

        @Override
        ItemStack get(Object slot) {
            return inventory.getItem((Integer) slot);
        }

        @Override
        void set(Object slot, ItemStack item) {
            inventory.setItem((Integer) slot, item);
        }
    }

    private static EquipmentSlot equipment(String slot) {
        return switch (slot) {
            case "head" -> EquipmentSlot.HEAD;
            case "chest" -> EquipmentSlot.CHEST;
            case "legs" -> EquipmentSlot.LEGS;
            case "feet" -> EquipmentSlot.FEET;
            case "off_hand" -> EquipmentSlot.OFF_HAND;
            default -> throw new IllegalArgumentException("Invalid public slot");
        };
    }

    static InventoryService.ItemView itemView(ItemStack original) {
        if (original == null || original.isEmpty()) return null;
        ItemStack item = original.clone();
        ItemMeta meta = item.getItemMeta();
        Component component = meta.hasDisplayName() ? meta.displayName() : null;
        String plainName = component == null ? null : PLAIN.serialize(component);
        Text name = plainName == null ? new Text(null, false) : bounded(plainName);
        boolean additional = component != null && !component.equals(Component.text(plainName));
        boolean truncated = name.truncated();
        List<Component> nativeLore = meta.hasLore() ? meta.lore() : null;
        List<String> lore = null;
        if (nativeLore != null) {
            lore = new ArrayList<>();
            truncated |= nativeLore.size() > 16;
            // Omitted lines cannot be represented by the public ItemStack setter.
            additional |= nativeLore.size() > 16;
            for (int i = 0; i < Math.min(16, nativeLore.size()); i++) {
                Component line = nativeLore.get(i);
                String plain = PLAIN.serialize(line);
                additional |= !line.equals(Component.text(plain));
                Text bounded = bounded(plain);
                lore.add(bounded.value());
                truncated |= bounded.truncated();
            }
        }
        // Compare untouched components against a fresh material after removing the supported plain
        // fields.
        ItemStack rest = item.clone();
        rest.setAmount(1);
        ItemMeta restMeta = rest.getItemMeta();
        restMeta.displayName(null);
        restMeta.lore(null);
        rest.setItemMeta(restMeta);
        additional |= !rest.isSimilar(item.getType().asItemType().createItemStack(1));
        return new InventoryService.ItemView(
                item.getType().getKey().toString(),
                item.getAmount(),
                name.value(),
                lore,
                additional,
                truncated);
    }

    private record Text(String value, boolean truncated) {}

    private static Text bounded(String input) {
        StringBuilder result = new StringBuilder();
        int offset = 0, count = 0;
        boolean changed = false;
        while (offset < input.length() && count++ < 256) {
            char value = input.charAt(offset++);
            if (Character.isHighSurrogate(value)
                    && offset < input.length()
                    && Character.isLowSurrogate(input.charAt(offset)))
                result.append(value).append(input.charAt(offset++));
            else if (Character.isSurrogate(value)) {
                result.append('\uFFFD');
                changed = true;
            } else result.append(value);
        }
        return new Text(result.toString(), changed || offset < input.length());
    }
}
