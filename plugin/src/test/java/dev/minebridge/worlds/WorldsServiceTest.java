package dev.minebridge.worlds;

import dev.minebridge.protocol.JsonNumber;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.WorldContext;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class WorldsServiceTest {
    private static final UUID ID = UUID.fromString("11111111-1111-4111-8111-111111111111");
    private static final WorldContext CONTEXT = new WorldContext("lesson", "minecraft:overworld", ID, -64, 320);
    private static final FakeRule KEEP = new FakeRule("minecraft:keep_inventory", Boolean.class);
    private static final FakeRule RANDOM = new FakeRule("minecraft:random_tick_speed", Integer.class);

    @Test void readsAndMutationsUseActualValuesAndGameThreadBoundary() throws Exception {
        FakeBackend backend = new FakeBackend();
        AtomicInteger checks = new AtomicInteger();
        WorldsService service = new WorldsService(backend, checks::incrementAndGet);
        assertEquals(Map.of("time", 6000L), service.execute(request("getTime"), CONTEXT));
        assertEquals(Map.of("applied", true), service.execute(request("setTime", "time", number(18000)), CONTEXT));
        assertEquals(18000, backend.primary.time);
        assertEquals(Map.of("applied", true), service.execute(request("setWeather", "weather", "thunder"), CONTEXT));
        assertEquals(Map.of("weather", "thunder"), service.execute(request("getWeather"), CONTEXT));
        assertEquals(Map.of("rule", KEEP.key(), "value", false), service.execute(request("getGameRule", "rule", KEEP.key()), CONTEXT));
        assertEquals(Map.of("applied", true), service.execute(request("setGameRule", "rule", KEEP.key(), "value", true), CONTEXT));
        assertEquals(Map.of("applied", true), service.execute(request("setGameRule", "rule", RANDOM.key(), "value", number(8)), CONTEXT));
        assertEquals(8, backend.primary.rules.get(RANDOM.key()));
        assertEquals(7, checks.get());
    }

    @Test void selectedWorldNameOrKeyRemainPinnedToOriginalUuid() throws Exception {
        FakeBackend backend = new FakeBackend();
        WorldsService service = new WorldsService(backend, () -> {});
        backend.byUuid.clear();
        backend.byName.put("lesson", new FakeWorld(UUID.randomUUID(), "lesson", "minecraft:overworld"));
        assertFailure("WORLD_NOT_FOUND", "not-applied", () -> service.execute(request("setTime", "time", number(100)), CONTEXT));
        assertFailure("WORLD_NOT_FOUND", "not-applied", () -> service.execute(new Request(2L, "worlds.setTime",
                Map.of("world", "minecraft:overworld", "time", number(100))), CONTEXT));
        assertEquals(0, backend.primary.writes);
    }

    @Test void explicitDifferentLoadedWorldIsAllowedWithoutChangingSessionContext() throws Exception {
        FakeBackend backend = new FakeBackend();
        FakeWorld other = new FakeWorld(UUID.randomUUID(), "another", "example:another");
        backend.byName.put("example:another", other);
        WorldsService service = new WorldsService(backend, () -> {});
        service.execute(new Request(2L, "worlds.setTime", Map.of("world", "example:another", "time", number(12000))), CONTEXT);
        assertEquals(12000, other.time);
        assertEquals(6000, backend.primary.time);
        assertEquals(ID, CONTEXT.uuid());
    }

    @Test void wrongRuleTypesAndNonInt32NumbersAreRejectedBeforeWriting() throws Exception {
        FakeBackend backend = new FakeBackend();
        WorldsService service = new WorldsService(backend, () -> {});
        for (Object[] invalid : new Object[][] {
                {KEEP.key(), number(1)}, {RANDOM.key(), true},
                {RANDOM.key(), new JsonNumber("1.0")}, {RANDOM.key(), new JsonNumber("2147483648")},
                {RANDOM.key(), new JsonNumber("1e999999999")}}) {
            assertFailure("INVALID_RULE_VALUE", "not-applied", () -> service.execute(
                    request("setGameRule", "rule", invalid[0], "value", invalid[1]), CONTEXT));
        }
        assertEquals(0, backend.primary.writes);
        assertEquals(false, backend.primary.rules.get(KEEP.key()));
        assertEquals(3, backend.primary.rules.get(RANDOM.key()));
    }

    @Test void invalidRuleAndWeatherAndTimeNeverMutateWorld() throws Exception {
        FakeBackend backend = new FakeBackend();
        WorldsService service = new WorldsService(backend, () -> {});
        assertFailure("INVALID_GAME_RULE", "not-applied", () -> service.execute(
                request("setGameRule", "rule", "keepInventory", "value", true), CONTEXT));
        assertFailure("INVALID_WEATHER", "not-applied", () -> service.execute(request("setWeather", "weather", "sunny"), CONTEXT));
        for (int time : new int[] {-1, 24000}) {
            assertFailure("INVALID_PARAMS", "not-applied", () -> service.execute(request("setTime", "time", number(time)), CONTEXT));
        }
        assertEquals(0, backend.primary.writes);
    }

    @Test void setterRejectionOrReadbackMismatchNeverClaimsApplied() throws Exception {
        FakeBackend backend = new FakeBackend();
        WorldsService service = new WorldsService(backend, () -> {});
        backend.primary.rejectWrites = true;
        assertFailure("WORLD_CHANGE_REJECTED", "unknown", () -> service.execute(request("setTime", "time", number(1)), CONTEXT));
        assertFailure("WORLD_CHANGE_REJECTED", "unknown", () -> service.execute(request("setWeather", "weather", "rain"), CONTEXT));
        assertFailure("WORLD_CHANGE_REJECTED", "unknown", () -> service.execute(request("setGameRule", "rule", KEEP.key(), "value", true), CONTEXT));
        assertEquals(false, backend.primary.rules.get(KEEP.key()));
    }

    @Test void worldMissingRuleIsRejectedBeforeItsSetter() throws Exception {
        FakeBackend backend = new FakeBackend();
        backend.primary.rules.remove(KEEP.key());
        WorldsService service = new WorldsService(backend, () -> {});
        assertFailure("INVALID_GAME_RULE", "not-applied", () -> service.execute(request("getGameRule", "rule", KEEP.key()), CONTEXT));
        assertFailure("INVALID_GAME_RULE", "not-applied", () -> service.execute(request("setGameRule", "rule", KEEP.key(), "value", true), CONTEXT));
        assertEquals(0, backend.primary.writes);
    }

    @Test void nativeRangeFailureRemainsSafeAndNotApplied() throws Exception {
        FakeBackend backend = new FakeBackend();
        backend.primary.rejectNegative = true;
        WorldsService service = new WorldsService(backend, () -> {});
        assertFailure("INVALID_RULE_VALUE", "not-applied", () -> service.execute(request("setGameRule", "rule", RANDOM.key(), "value", number(-1)), CONTEXT));
        assertEquals(3, backend.primary.rules.get(RANDOM.key()));
        assertEquals(0, backend.primary.writes);
    }

    @Test void unexpectedFailureAfterEnteringMutatorNeverClaimsNotApplied() throws Exception {
        FakeBackend backend = new FakeBackend();
        backend.primary.failAfterMutation = true;
        WorldsService service = new WorldsService(backend, () -> {});
        assertFailure("INTERNAL_ERROR", "unknown", () -> service.execute(request("setTime", "time", number(100)), CONTEXT));
        assertEquals(100, backend.primary.time);
    }

    private static JsonNumber number(int value) { return new JsonNumber(Integer.toString(value)); }
    private static Request request(String method, Object... fields) {
        Map<String, Object> params = new HashMap<>(); params.put("world", "lesson");
        for (int i = 0; i < fields.length; i += 2) params.put((String) fields[i], fields[i + 1]);
        return new Request(2L, "worlds." + method, params);
    }
    @FunctionalInterface private interface Attempt { void run() throws Exception; }
    private static void assertFailure(String code, String outcome, Attempt attempt) {
        WorldFailure failure = assertThrows(WorldFailure.class, attempt::run);
        assertEquals(code, failure.code()); assertEquals(outcome, failure.outcome());
        assertFalse(failure.toString().contains("keepInventory"));
    }
    private record FakeRule(String key, Class<?> valueType) implements WorldsService.Rule {}
    private static final class FakeBackend implements WorldsService.Backend {
        final FakeWorld primary = new FakeWorld(ID, "lesson", "minecraft:overworld");
        final Map<UUID, FakeWorld> byUuid = new HashMap<>(Map.of(ID, primary));
        final Map<String, FakeWorld> byName = new HashMap<>(Map.of("lesson", primary, "minecraft:overworld", primary));
        @Override public WorldsService.WorldAccess findWorld(UUID uuid) { return byUuid.get(uuid); }
        @Override public WorldsService.WorldAccess findWorld(String nameOrKey) { return byName.get(nameOrKey); }
        @Override public WorldsService.Rule findRule(String key) { return Map.of(KEEP.key(), KEEP, RANDOM.key(), RANDOM).get(key); }
    }
    private static final class FakeWorld implements WorldsService.WorldAccess {
        final UUID uuid; final String name; final String key;
        long time = 6000; String weather = "clear"; boolean rejectWrites, rejectNegative, failAfterMutation; int writes;
        final Map<String, Object> rules = new HashMap<>(Map.of(KEEP.key(), false, RANDOM.key(), 3));
        FakeWorld(UUID uuid, String name, String key) { this.uuid = uuid; this.name = name; this.key = key; }
        @Override public UUID uuid() { return uuid; }
        @Override public String name() { return name; }
        @Override public String key() { return key; }
        @Override public long time() { return time; }
        @Override public void time(int value) {
            writes++; if (!rejectWrites) time = value;
            if (failAfterMutation) throw new IllegalStateException("Unsafe backend failure details");
        }
        @Override public String weather() { return weather; }
        @Override public void weather(String value) { writes++; if (!rejectWrites) weather = value; }
        @Override public Object rule(WorldsService.Rule rule) { return rules.get(rule.key()); }
        @Override public boolean rule(WorldsService.Rule rule, Object value) throws WorldFailure {
            if (rejectNegative && value instanceof Integer integer && integer < 0) throw new WorldFailure("INVALID_RULE_VALUE", "not-applied");
            writes++; if (rejectWrites) return false; rules.put(rule.key(), value); return true;
        }
    }
}
