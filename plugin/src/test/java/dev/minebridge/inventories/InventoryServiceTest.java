package dev.minebridge.inventories;

import static org.junit.jupiter.api.Assertions.*;

import dev.minebridge.blocks.BlockService;
import dev.minebridge.blocks.ChunkService;
import dev.minebridge.gameplay.GameplayService;
import dev.minebridge.players.PlayerService;
import dev.minebridge.session.WorldContext;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;

class InventoryServiceTest {
    static final WorldContext CONTEXT =
            new WorldContext("lesson", "minecraft:overworld", UUID.randomUUID(), -64, 320);

    static final class Person implements PlayerService.Player {
        final UUID id = UUID.randomUUID();
        final String name;
        boolean online = true;

        Person(String name) {
            this.name = name;
        }

        @Override
        public UUID uuid() {
            return id;
        }

        @Override
        public String name() {
            return name;
        }

        @Override
        public int entityId() {
            return 1;
        }

        @Override
        public boolean online() {
            return online;
        }

        @Override
        public PlayerService.Position position() {
            return new PlayerService.Position("lesson", CONTEXT.uuid(), 0, 80, 0, 0, 0);
        }

        @Override
        public CompletionStage<Boolean> teleport(
                BlockService.WorldAccess world,
                double x,
                double y,
                double z,
                float yaw,
                float pitch) {
            throw new AssertionError();
        }
    }

    static final class World implements BlockService.WorldAccess {
        boolean loaded = true;
        int loads, tickets, adds, removes;
        boolean failFirstRemove;
        final CompletableFuture<Boolean> future = new CompletableFuture<>();

        @Override
        public String name() {
            return "lesson";
        }

        @Override
        public UUID uuid() {
            return CONTEXT.uuid();
        }

        @Override
        public int minY() {
            return -64;
        }

        @Override
        public int maxYExclusive() {
            return 320;
        }

        @Override
        public boolean insideBorder(double x, double z) {
            return true;
        }

        @Override
        public boolean isChunkLoaded(int x, int z) {
            return loaded;
        }

        @Override
        public BlockService.BlockAccess blockAt(int x, int y, int z) {
            throw new AssertionError();
        }

        @Override
        public CompletionStage<Boolean> loadChunk(int x, int z) {
            loads++;
            return future;
        }

        @Override
        public void addChunkTicket(int x, int z) {
            tickets++;
            adds++;
        }

        @Override
        public void removeChunkTicket(int x, int z) {
            tickets--;
            removes++;
            if (failFirstRemove && removes == 1)
                throw new IllegalStateException("native cleanup failure");
        }
    }

    record Prepared(String key, int amount, int maxStackSize, String name, List<String> lore)
            implements InventoryService.PreparedItem {
        InventoryService.ItemView view() {
            return new InventoryService.ItemView(key, amount, name, lore, false, false);
        }
    }

    static final class Store implements InventoryService.Handle {
        final Map<String, Object> descriptor;
        final List<Object> slots;
        final Map<Object, InventoryService.ItemView> contents = new HashMap<>();
        int writes, clears, maximum = 64;
        boolean reject, crash;
        Runnable afterWrite = () -> {};

        Store(UUID player) {
            descriptor = InventoryService.playerDescriptor(player);
            slots = InventoryService.PLAYER_SLOTS;
        }

        Store(boolean combined) {
            List<Object> keys = new ArrayList<>();
            for (int i = 0; i < (combined ? 54 : 27); i++) keys.add(i);
            slots = List.copyOf(keys);
            Map<String, Object> first =
                    InventoryService.map(
                            "position",
                            List.of(15, 80, 15),
                            "offset",
                            0,
                            "size",
                            27,
                            "key",
                            "minecraft:chest");
            Map<String, Object> second =
                    InventoryService.map(
                            "position",
                            List.of(16, 80, 15),
                            "offset",
                            27,
                            "size",
                            27,
                            "key",
                            "minecraft:chest");
            descriptor =
                    InventoryService.map(
                            "kind",
                            "chest",
                            "world",
                            CONTEXT.uuid().toString(),
                            "position",
                            List.of(15, 80, 15),
                            "combined",
                            combined,
                            "size",
                            slots.size(),
                            "slots",
                            slots,
                            "layout",
                            combined ? List.of(first, second) : List.of(first));
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
            return descriptor.get("kind").equals("player")
                            && slot instanceof String name
                            && !name.equals("off_hand")
                    ? 1
                    : maximum;
        }

        @Override
        public InventoryService.ItemView read(Object slot) {
            return contents.get(slot);
        }

        @Override
        public void write(Object slot, InventoryService.PreparedItem item) {
            writes++;
            if (crash) throw new IllegalStateException("do-not-forward-native-secret");
            if (!reject) contents.put(slot, ((Prepared) item).view());
            afterWrite.run();
        }

        @Override
        public void clear(Object slot) {
            clears++;
            if (!reject) contents.remove(slot);
        }

        @Override
        public boolean matches(Object slot, InventoryService.PreparedItem item) {
            return ((Prepared) item).view().equals(contents.get(slot));
        }

        @Override
        public boolean empty(Object slot) {
            return !contents.containsKey(slot);
        }
    }

    static final class Harness
            implements InventoryService.Backend, PlayerService.Backend, BlockService.Backend {
        final World world = new World();
        final Person a = new Person("Alpha"), b = new Person("Beta");
        final Store first = new Store(a.id), second = new Store(b.id);
        Store chest = new Store(false);
        boolean chestExists = true;
        int openedChests, selections;
        final List<PlayerService.Target> selection = new ArrayList<>(List.of(a, b));
        final BlockService blocks = new BlockService(this, () -> {});
        final PlayerService players = new PlayerService(this, blocks, () -> {});
        final InventoryService service = new InventoryService(this, blocks, players, () -> {});
        final ChunkService chunks = new ChunkService();
        final InventoryJobManager jobs = new InventoryJobManager(service, players, chunks);

        @Override
        public BlockService.WorldAccess world(UUID uuid) {
            return findWorld(uuid);
        }

        @Override
        public BlockService.WorldAccess findWorld(UUID uuid) {
            return world.uuid().equals(uuid) ? world : null;
        }

        @Override
        public BlockService.WorldAccess findWorld(String name) {
            return name.equals("lesson") || name.equals("minecraft:overworld") ? world : null;
        }

        @Override
        public BlockService.BlockMaterial resolveBlock(String key) {
            return null;
        }

        @Override
        public Person findPlayer(String identifier) {
            for (Person person : List.of(a, b))
                if (person.id.toString().equals(identifier) || person.name.equals(identifier))
                    return person;
            return null;
        }

        @Override
        public List<PlayerService.Target> select(String selector, PlayerService.Player executor) {
            selections++;
            return selector.equals("@s") ? List.of(executor) : selection;
        }

        @Override
        public void broadcast(String message) {
            throw new AssertionError();
        }

        @Override
        public InventoryService.Handle player(UUID uuid) throws InventoryFailure {
            if (uuid.equals(a.id) && a.online) return first;
            if (uuid.equals(b.id) && b.online) return second;
            throw new InventoryFailure("PLAYER_NOT_FOUND");
        }

        @Override
        public InventoryService.Handle chest(
                BlockService.WorldAccess world, int x, int y, int z, boolean combined)
                throws InventoryFailure {
            openedChests++;
            if (!chestExists) throw new InventoryFailure("INVENTORY_NOT_FOUND");
            return chest;
        }

        @Override
        public InventoryService.PreparedItem item(GameplayService.Item item) {
            return new Prepared(
                    item.key(),
                    item.amount(),
                    item.key().equals("minecraft:iron_sword") ? 1 : 64,
                    item.name(),
                    item.lore());
        }
    }

    static Map<String, Object> item(String key, int amount) {
        return InventoryService.map("key", key, "amount", amount, "name", null, "lore", null);
    }

    @Test
    void exactReplacementPreservesPreviousViewAndNeverMergesOrDrops() throws Exception {
        Harness h = new Harness();
        h.first.contents.put(0, new Prepared("minecraft:stone", 60, 64, null, null).view());
        Map<String, Object> result =
                h.service.replace(h.first, 0, h.service.item(item("minecraft:diamond", 16)));
        assertEquals(60, ((Map<?, ?>) result.get("previous")).get("amount"));
        assertEquals("minecraft:diamond", ((Map<?, ?>) result.get("current")).get("key"));
        assertEquals(16, h.first.contents.get(0).amount());
        assertEquals(1, h.first.writes);
        assertNull(h.first.contents.get(1));
    }

    @Test
    void limitsAndPublicEquipmentAreValidatedBeforeAnyWrite() throws Exception {
        Harness h = new Harness();
        assertCode("INVALID_ITEM_AMOUNT", () -> h.service.item(item("minecraft:iron_sword", 2)));
        var diamonds = h.service.item(item("minecraft:diamond", 2));
        assertCode("INVALID_ITEM_AMOUNT", () -> h.service.replace(h.first, "head", diamonds));
        assertCode("INVALID_SLOT", () -> h.service.replace(h.first, 36, diamonds));
        assertEquals(0, h.first.writes);
        h.service.replace(h.first, "off_hand", diamonds);
        assertEquals(2, h.first.contents.get("off_hand").amount());
    }

    @Test
    void voidSetterNeedsReadbackAndNativeFailureNeverPretendsNotApplied() throws Exception {
        Harness h = new Harness();
        h.first.reject = true;
        InventoryFailure rejected =
                assertThrows(
                        InventoryFailure.class,
                        () ->
                                h.service.replace(
                                        h.first, 0, h.service.item(item("minecraft:stone", 1))));
        assertEquals("INVENTORY_WRITE_REJECTED", rejected.code());
        assertEquals("unknown", rejected.outcome());
        h.first.reject = false;
        h.first.crash = true;
        InventoryFailure crashed =
                assertThrows(
                        InventoryFailure.class,
                        () ->
                                h.service.replace(
                                        h.first, 0, h.service.item(item("minecraft:stone", 1))));
        assertEquals("INTERNAL_ERROR", crashed.code());
        assertEquals("unknown", crashed.outcome());
        assertFalse(crashed.getMessage().contains("secret"));
    }

    @Test
    void clearOnlyTouchesPublicKeysAndReturnsTheVerifiedScope() throws Exception {
        Harness h = new Harness();
        var view = new Prepared("minecraft:stone", 1, 64, null, null).view();
        for (Object slot : h.first.slots) h.first.contents.put(slot, view);
        h.first.contents.put("body", view);
        h.first.contents.put("saddle", view);
        var request =
                InventoryJobManagerTest.request(
                        1,
                        "inventories.clear",
                        InventoryService.map("inventory", h.first.descriptor, "slot", null));
        var result = h.service.execute(h.first, request);
        assertEquals(41, ((List<?>) result.get("slots")).size());
        assertEquals(41, h.first.clears);
        assertEquals(Map.of("body", view, "saddle", view), h.first.contents);
    }

    @Test
    void readPagesRespectBytesAndIncludeEmptySlotsWithoutShiftingKeys() throws Exception {
        Harness h = new Harness();
        List<String> lore = java.util.Collections.nCopies(16, "\u0000".repeat(256));
        h.first.contents.put(
                0,
                new InventoryService.ItemView(
                        "minecraft:stone", 1, "\u0000".repeat(256), lore, true, true));
        h.first.contents.put(
                1,
                new InventoryService.ItemView(
                        "minecraft:stone", 1, "\u0000".repeat(256), lore, true, true));
        var first =
                h.service.execute(
                        h.first,
                        InventoryJobManagerTest.request(
                                1,
                                "inventories.getContents",
                                Map.of("inventory", h.first.descriptor, "offset", 0, "limit", 54)));
        assertEquals(1, ((List<?>) first.get("items")).size());
        assertEquals(1, first.get("nextOffset"));
        var second =
                h.service.execute(
                        h.first,
                        InventoryJobManagerTest.request(
                                2,
                                "inventories.getContents",
                                Map.of("inventory", h.first.descriptor, "offset", 1, "limit", 54)));
        assertEquals(41, second.get("total"));
        assertNull(second.get("nextOffset"));
        var rows = (List<?>) second.get("items");
        assertEquals(40, rows.size());
        assertNull(((Map<?, ?>) rows.get(1)).get("item"));
        assertEquals(2, ((Map<?, ?>) rows.get(1)).get("slot"));
    }

    @Test
    void staleCombinedDescriptorFailsBeforeAnyMutation() throws Exception {
        Harness h = new Harness();
        h.chest = new Store(true);
        var request =
                InventoryJobManagerTest.request(
                        1,
                        "inventories.clear",
                        InventoryService.map("inventory", h.chest.descriptor, "slot", 0));
        var address = h.service.address(request, CONTEXT);
        h.chest = new Store(false);
        assertCode("INVENTORY_CHANGED", () -> h.service.openBlock(address));
        assertEquals(0, h.chest.clears);
    }

    @FunctionalInterface
    interface Checked {
        Object run() throws Exception;
    }

    static void assertCode(String code, Checked operation) {
        assertEquals(code, assertThrows(InventoryFailure.class, operation::run).code());
    }
}
