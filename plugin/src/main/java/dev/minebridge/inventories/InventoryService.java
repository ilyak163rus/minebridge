package dev.minebridge.inventories;

import dev.minebridge.blocks.BlockFailure;
import dev.minebridge.blocks.BlockService;
import dev.minebridge.gameplay.GameplayService;
import dev.minebridge.players.PlayerFailure;
import dev.minebridge.players.PlayerService;
import dev.minebridge.protocol.JsonNumber;
import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.WorldContext;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/** Exact-slot semantics shared by block refs, player refs and bulk player writes. */
public final class InventoryService {
    public static final int PAGE_BYTES = 32768;
    public static final List<Object> PLAYER_SLOTS;

    static {
        ArrayList<Object> slots = new ArrayList<>();
        for (int slot = 0; slot < 36; slot++) slots.add(slot);
        slots.addAll(List.of("head", "chest", "legs", "feet", "off_hand"));
        PLAYER_SLOTS = List.copyOf(slots);
    }

    public record ItemView(
            String key,
            int amount,
            String name,
            List<String> lore,
            boolean hasAdditionalData,
            boolean truncated) {
        public ItemView {
            lore = lore == null ? null : List.copyOf(lore);
        }

        public Map<String, Object> toProtocol() {
            return map(
                    "key",
                    key,
                    "amount",
                    amount,
                    "name",
                    name,
                    "lore",
                    lore,
                    "hasAdditionalData",
                    hasAdditionalData,
                    "truncated",
                    truncated);
        }
    }

    public interface PreparedItem {
        int amount();

        int maxStackSize();
    }

    /** Transient native handle used only on the game thread, while its chunk leases are held. */
    public interface Handle {
        Map<String, Object> descriptor();

        List<Object> slots();

        int maxStackSize(Object slot);

        ItemView read(Object slot) throws InventoryFailure;

        void write(Object slot, PreparedItem item) throws InventoryFailure;

        void clear(Object slot) throws InventoryFailure;

        boolean matches(Object slot, PreparedItem item) throws InventoryFailure;

        boolean empty(Object slot) throws InventoryFailure;
    }

    public interface Backend {
        BlockService.WorldAccess world(UUID uuid);

        Handle player(UUID uuid) throws InventoryFailure;

        Handle chest(BlockService.WorldAccess world, int x, int y, int z, boolean combined)
                throws InventoryFailure;

        PreparedItem item(GameplayService.Item item) throws InventoryFailure;
    }

    public record BlockAddress(
            BlockService.WorldAccess world,
            int x,
            int y,
            int z,
            boolean combined,
            Map<String, Object> expected) {}

    private final Backend backend;
    private final BlockService blocks;
    private final PlayerService players;
    private final Runnable requireGameThread;

    public InventoryService(
            Backend backend,
            BlockService blocks,
            PlayerService players,
            Runnable requireGameThread) {
        this.backend = Objects.requireNonNull(backend);
        this.blocks = Objects.requireNonNull(blocks);
        this.players = Objects.requireNonNull(players);
        this.requireGameThread = Objects.requireNonNull(requireGameThread);
    }

    public BlockAddress address(Request request, WorldContext context)
            throws BlockFailure, InventoryFailure, PlayerFailure {
        requireGameThread.run();
        Map<String, Object> params = request.params();
        if (request.method().equals("inventories.ofBlock")) {
            List<?> at = (List<?>) params.get("position");
            int x = integer(at.get(0)), y = integer(at.get(1)), z = integer(at.get(2));
            BlockService.WorldAccess world =
                    players.destination(
                            context,
                            (String) params.get("world"),
                            (String) params.get("destinationWorld"),
                            x,
                            y,
                            z);
            blocks.checkPosition(world, x, y, z);
            return new BlockAddress(world, x, y, z, (Boolean) params.get("combined"), null);
        }
        Map<String, Object> descriptor = descriptor(params.get("inventory"));
        if (!descriptor.get("kind").equals("chest")) return null;
        UUID uuid = UUID.fromString((String) descriptor.get("world"));
        BlockService.WorldAccess world = backend.world(uuid);
        if (world == null || !world.uuid().equals(uuid))
            throw new InventoryFailure("WORLD_NOT_FOUND");
        List<?> at = (List<?>) descriptor.get("position");
        int x = integer(at.get(0)), y = integer(at.get(1)), z = integer(at.get(2));
        blocks.checkPosition(world, x, y, z);
        return new BlockAddress(world, x, y, z, (Boolean) descriptor.get("combined"), descriptor);
    }

    public Handle openBlock(BlockAddress address) throws InventoryFailure, BlockFailure {
        requireGameThread.run();
        Handle handle;
        try {
            handle =
                    backend.chest(
                            address.world(),
                            address.x(),
                            address.y(),
                            address.z(),
                            address.combined());
        } catch (InventoryFailure failure) {
            if (address.expected() != null && failure.code().equals("INVENTORY_NOT_FOUND"))
                throw new InventoryFailure("INVENTORY_CHANGED");
            throw failure;
        }
        if (address.expected() != null && !address.expected().equals(handle.descriptor()))
            throw new InventoryFailure("INVENTORY_CHANGED");
        for (Object raw : (List<?>) handle.descriptor().get("layout")) {
            List<?> at = (List<?>) ((Map<?, ?>) raw).get("position");
            blocks.checkPosition(
                    address.world(), integer(at.get(0)), integer(at.get(1)), integer(at.get(2)));
        }
        return handle;
    }

    public Handle openPlayer(UUID uuid) throws InventoryFailure {
        requireGameThread.run();
        return backend.player(uuid);
    }

    public Handle playerReference(Request request, WorldContext context)
            throws InventoryFailure, PlayerFailure, BlockFailure {
        requireGameThread.run();
        if (request.method().equals("inventories.ofPlayer")) {
            Map<String, Object> p = request.params();
            PlayerService.Selection selected =
                    players.select(
                            context,
                            (String) p.get("world"),
                            (String) p.get("executor"),
                            p.get("targets"));
            if (selected.players().size() != 1) throw new InventoryFailure("INVALID_TARGET");
            return openPlayer(selected.players().getFirst().uuid());
        }
        Map<String, Object> descriptor = descriptor(request.params().get("inventory"));
        Handle handle = openPlayer(UUID.fromString((String) descriptor.get("player")));
        if (!descriptor.equals(handle.descriptor()))
            throw new InventoryFailure("INVENTORY_CHANGED");
        return handle;
    }

    public PreparedItem item(Object raw) throws InventoryFailure {
        requireGameThread.run();
        Map<String, Object> item = descriptor(raw);
        @SuppressWarnings("unchecked")
        List<String> lore = (List<String>) item.get("lore");
        PreparedItem prepared =
                backend.item(
                        new GameplayService.Item(
                                (String) item.get("key"),
                                integer(item.get("amount")),
                                (String) item.get("name"),
                                lore));
        if (prepared.amount() < 1 || prepared.amount() > prepared.maxStackSize())
            throw new InventoryFailure("INVALID_ITEM_AMOUNT");
        return prepared;
    }

    public Object slot(Handle handle, Object raw) throws InventoryFailure {
        requireGameThread.run();
        Object slot = raw instanceof JsonNumber ? integer(raw) : raw;
        if (!handle.slots().contains(slot)) throw new InventoryFailure("INVALID_SLOT");
        return slot;
    }

    public Object playerSlot(Object raw) throws InventoryFailure {
        Object slot = raw instanceof JsonNumber ? integer(raw) : raw;
        if (!PLAYER_SLOTS.contains(slot)) throw new InventoryFailure("INVALID_SLOT");
        return slot;
    }

    public void validate(Handle handle, Object slot, PreparedItem item) throws InventoryFailure {
        requireGameThread.run();
        slot(handle, slot);
        int maximum = Math.min(item.maxStackSize(), handle.maxStackSize(slot));
        if (item.amount() < 1 || item.amount() > maximum)
            throw new InventoryFailure("INVALID_ITEM_AMOUNT");
    }

    public Map<String, Object> execute(Handle handle, Request request) throws InventoryFailure {
        requireGameThread.run();
        Map<String, Object> p = request.params();
        return switch (request.method()) {
            case "inventories.ofBlock", "inventories.ofPlayer" ->
                    Map.of("inventory", handle.descriptor());
            case "inventories.getItem" -> {
                Object slot = slot(handle, p.get("slot"));
                yield map("slot", slot, "item", view(handle.read(slot)));
            }
            case "inventories.getContents" ->
                    contents(handle, integer(p.get("offset")), integer(p.get("limit")));
            case "inventories.setItem" ->
                    replace(handle, slot(handle, p.get("slot")), item(p.get("item")));
            case "inventories.clear" -> clear(handle, p.get("slot"));
            default -> throw new InventoryFailure("METHOD_NOT_FOUND");
        };
    }

    public Map<String, Object> replace(Handle handle, Object slot, PreparedItem item)
            throws InventoryFailure {
        validate(handle, slot, item);
        ItemView previous = handle.read(slot);
        write(handle, slot, item);
        try {
            return map(
                    "applied",
                    true,
                    "slot",
                    slot,
                    "previous",
                    view(previous),
                    "current",
                    view(handle.read(slot)));
        } catch (InventoryFailure failure) {
            throw new InventoryFailure(failure.code(), "unknown");
        } catch (RuntimeException failure) {
            throw new InventoryFailure("INTERNAL_ERROR", "unknown");
        }
    }

    /**
     * Compact bulk path uses the same setter/postcondition without materializing previous/current
     * views.
     */
    public void write(Handle handle, Object slot, PreparedItem item) throws InventoryFailure {
        validate(handle, slot, item);
        try {
            handle.write(slot, item);
            if (!handle.matches(slot, item))
                throw new InventoryFailure("INVENTORY_WRITE_REJECTED", "unknown");
        } catch (InventoryFailure failure) {
            throw new InventoryFailure(failure.code(), "unknown");
        } catch (RuntimeException failure) {
            throw new InventoryFailure("INTERNAL_ERROR", "unknown");
        }
    }

    private Map<String, Object> clear(Handle handle, Object rawSlot) throws InventoryFailure {
        List<Object> slots = rawSlot == null ? handle.slots() : List.of(slot(handle, rawSlot));
        try {
            for (Object slot : slots) handle.clear(slot);
            for (Object slot : slots)
                if (!handle.empty(slot))
                    throw new InventoryFailure("INVENTORY_WRITE_REJECTED", "unknown");
            return Map.of("applied", true, "slots", slots);
        } catch (InventoryFailure failure) {
            throw new InventoryFailure(failure.code(), "unknown");
        } catch (RuntimeException failure) {
            throw new InventoryFailure("INTERNAL_ERROR", "unknown");
        }
    }

    private Map<String, Object> contents(Handle handle, int offset, int limit)
            throws InventoryFailure {
        if (offset < 0 || offset >= handle.slots().size() || limit < 1 || limit > 54)
            throw new InventoryFailure("INVALID_PARAMS");
        List<Map<String, Object>> items = new ArrayList<>();
        int used = 0, next = offset;
        while (next < handle.slots().size() && items.size() < limit) {
            Object slot = handle.slots().get(next);
            Map<String, Object> entry = map("slot", slot, "item", view(handle.read(slot)));
            int bytes = JsonRpcCodec.encodeFrame(entry).length;
            if (used + bytes > PAGE_BYTES && !items.isEmpty()) break;
            if (bytes > PAGE_BYTES) throw new InventoryFailure("LIMIT_EXCEEDED");
            items.add(entry);
            used += bytes;
            next++;
        }
        return map(
                "items",
                items,
                "nextOffset",
                next == handle.slots().size() ? null : next,
                "total",
                handle.slots().size());
    }

    public static Map<String, Object> playerDescriptor(UUID uuid) {
        return Map.of(
                "kind", "player", "player", uuid.toString(), "size", 41, "slots", PLAYER_SLOTS);
    }

    public static Object view(ItemView view) {
        return view == null ? null : view.toProtocol();
    }

    public static int integer(Object value) {
        return value instanceof JsonNumber number
                ? Integer.parseInt(number.text())
                : ((Number) value).intValue();
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> descriptor(Object value) {
        Map<String, Object> result = new LinkedHashMap<>();
        ((Map<String, Object>) value).forEach((key, item) -> result.put(key, normalize(item)));
        return Collections.unmodifiableMap(result);
    }

    private static Object normalize(Object value) {
        if (value instanceof JsonNumber number) return Integer.parseInt(number.text());
        if (value instanceof Map<?, ?>) return descriptor(value);
        if (value instanceof List<?> list)
            return list.stream().map(InventoryService::normalize).toList();
        return value;
    }

    public static Map<String, Object> map(Object... pairs) {
        Map<String, Object> map = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) map.put((String) pairs[i], pairs[i + 1]);
        return Collections.unmodifiableMap(map);
    }
}
