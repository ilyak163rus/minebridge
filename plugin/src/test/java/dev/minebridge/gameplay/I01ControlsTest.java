package dev.minebridge.gameplay;

import dev.minebridge.blocks.ChunkService;
import dev.minebridge.players.PlayerFailure;
import dev.minebridge.players.PlayerJobManager;
import dev.minebridge.players.PlayerService;
import dev.minebridge.protocol.JsonNumber;
import dev.minebridge.protocol.Request;
import dev.minebridge.protocol.Response;
import dev.minebridge.session.Session;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import static dev.minebridge.gameplay.GameplayJobManagerTest.*;
import static org.junit.jupiter.api.Assertions.*;

/** New controls retain full-set validation, readback and the shared bounded gameplay queue. */
class I01ControlsTest {
    static final class Person extends GameplayJobManagerTest.Person {
        String mode = "survival"; double health = 10, maxHealth = 20; int food = 12, mutations;
        boolean rejectMode, rejectHealth, rejectFood;
        Person(String name) { super(name); }
        @Override public String gameMode() { return mode; }
        @Override public void gameMode(String value) { mutations++; if (!rejectMode) mode = value; }
        @Override public double health() { return health; }
        @Override public double maxHealth() { return maxHealth; }
        @Override public void health(double value) { mutations++; if (!rejectHealth) health = value; }
        @Override public int foodLevel() { return food; }
        @Override public void foodLevel(int value) { mutations++; if (!rejectFood) food = value; }
    }
    static final class Controls extends GameplayJobManagerTest.Harness {
        final Person alpha = new Person("Alpha"), beta = new Person("Beta");
        final Set<UUID> activeEffects = new HashSet<>(); int removeCalls, clearCalls; UUID rejectRemoval;
        Controls() { selected = new ArrayList<>(List.of(alpha, beta)); }
        @Override public PlayerService.Player findPlayer(String value) {
            return List.of(alpha, beta).stream().filter(person -> person.name.equals(value) || person.uuid.toString().equals(value)).findFirst().orElse(null);
        }
        @Override public GameplayService.PreparedEffect prepareEffectRemoval(String key) throws GameplayFailure {
            if (!"minecraft:speed".equals(key)) throw new GameplayFailure("INVALID_EFFECT");
            return new GameplayService.PreparedEffect() {};
        }
        @Override public boolean removeEffect(PlayerService.Target target, GameplayService.PreparedEffect prepared) {
            removeCalls++; if (!target.uuid().equals(rejectRemoval)) activeEffects.remove(target.uuid());
            return !activeEffects.contains(target.uuid());
        }
        @Override public boolean clearEffects(PlayerService.Target target) {
            clearCalls++; if (!target.uuid().equals(rejectRemoval)) activeEffects.remove(target.uuid());
            return !activeEffects.contains(target.uuid());
        }
    }
    static Request control(long id, String method, Object value) {
        Map<String, Object> params = common("@a");
        params.put(method.equals("players.setGameMode") ? "mode" : "value", value);
        return request(id, method, params);
    }
    static Request remove(long id, String key) {
        Map<String, Object> params = common("@a"); params.put("effect", Map.of("key", key));
        return request(id, "effects.remove", params);
    }
    static List<?> outcomes(Response value) { return (List<?>) value.result().get("targets"); }

    @Test void healthValidatesActualMaximumForEveryTargetBeforeAnyMutation() {
        Controls h = new Controls(); h.alpha.maxHealth = 40; h.beta.maxHealth = 20;
        Session s = session(); h.jobs.submit(s, control(1, "players.setHealth", 25), CONTEXT);
        Response result = response(s, 1, "players.setHealth");
        assertEquals("INVALID_PLAYER_VALUE", result.error().code()); assertEquals("not-applied", result.error().outcome());
        assertEquals(0, h.alpha.mutations + h.beta.mutations); assertEquals(10, h.alpha.health);
        assertEquals(1, h.selections); assertFalse(s.hasActiveOperation());
    }

    @Test void cancelledVoidSetterIsNotReportedAsSuccessfulAndOtherTargetsStillComplete() {
        Controls h = new Controls(); h.beta.rejectMode = true; Session s = session();
        h.jobs.submit(s, control(1, "players.setGameMode", "creative"), CONTEXT); h.finish(s);
        Response result = response(s, 1, "players.setGameMode");
        assertEquals("1", ((JsonNumber) result.result().get("applied")).text());
        assertEquals("creative", h.alpha.mode); assertEquals("survival", h.beta.mode);
        assertEquals("GAME_MODE_REJECTED", ((Map<?, ?>) outcomes(result).get(1)).get("code"));
        assertEquals(1, h.selections);
    }

    @Test void playerGetterRequiresOneAndReadsActualHealthModeAndFood() {
        Controls h = new Controls(); PlayerJobManager getters = new PlayerJobManager(h.players, new ChunkService());
        h.alpha.mode = "adventure"; h.alpha.health = 17.5; h.alpha.food = 7;
        Session s = session();
        for (String method : List.of("players.getGameMode", "players.getHealth", "players.getFoodLevel")) {
            getters.submit(s, request(1, method, common("Alpha")), CONTEXT);
            Response result = response(s, 1, method);
            if (method.endsWith("GameMode")) assertEquals("adventure", result.result().get("mode"));
            else assertEquals(method.endsWith("Health") ? 17.5 : 7.0, Double.parseDouble(((JsonNumber) result.result().get("value")).text()));
        }
        getters.submit(s, request(2, "players.getHealth", common("@a")), CONTEXT);
        assertEquals("INVALID_TARGET", response(s, 2, "players.getHealth").error().code());
        assertEquals(0, h.alpha.mutations + h.beta.mutations);
    }

    @Test void healthZeroAndFoodRoundtripUseReadbackAndFoodRejectionIsPerTarget() {
        Controls h = new Controls(); Session s = session(); h.beta.rejectFood = true;
        h.jobs.submit(s, control(1, "players.setFoodLevel", 20), CONTEXT); h.finish(s);
        Response food = response(s, 1, "players.setFoodLevel");
        assertEquals("PLAYER_VALUE_REJECTED", ((Map<?, ?>) outcomes(food).get(1)).get("code"));
        h.jobs.submit(s, control(2, "players.setHealth", 0), CONTEXT); h.finish(s);
        assertEquals("2", ((JsonNumber) response(s, 2, "players.setHealth").result().get("applied")).text());
        assertEquals(0, h.alpha.health); assertEquals(0, h.beta.health);
    }

    @Test void healthUsesNativeFloatPrecisionAndDoesNotAccidentallyKillOnPositiveUnderflow() {
        Controls h = new Controls(); Session s = session();
        h.jobs.submit(s, control(1, "players.setHealth", 1.1), CONTEXT); h.finish(s);
        assertEquals("2", ((JsonNumber) response(s, 1, "players.setHealth").result().get("applied")).text());
        assertEquals((double) (float) 1.1, h.alpha.health);
        h.jobs.submit(s, control(2, "players.setHealth", 20.00000001), CONTEXT); h.finish(s);
        assertEquals("2", ((JsonNumber) response(s, 2, "players.setHealth").result().get("applied")).text());
        assertEquals(20, h.alpha.health);
        assertEquals("INVALID_PLAYER_VALUE", assertThrows(PlayerFailure.class,
                () -> h.players.validateControl(new PlayerService.Selection(List.of(h.alpha)), "players.setHealth", null, Double.MIN_VALUE)).code());
        assertEquals(2, h.alpha.mutations);
    }

    @Test void controlJobsAreBoundedKeepFifoAndDoNotStopAnotherSession() {
        Controls h = new Controls(); List<Person> targets = new ArrayList<>();
        for (int i = 0; i < 300; i++) targets.add(new Person("Target" + i));
        h.selected = new ArrayList<>(targets);
        Session a = session(); h.jobs.submit(a, control(1, "players.setFoodLevel", 18), CONTEXT);
        assertTrue(a.hasActiveOperation());
        assertTrue(targets.stream().mapToInt(person -> person.mutations).sum() <= 128);
        h.selected = new ArrayList<>(List.of(h.alpha));
        Session b = session(); h.jobs.submit(b, control(1, "players.setGameMode", "spectator"), CONTEXT);
        h.finish(b); assertNull(response(b, 1, "players.setGameMode").error());
        h.finish(a); assertNull(response(a, 1, "players.setFoodLevel").error());
        assertTrue(targets.stream().allMatch(person -> person.food == 18 && person.mutations == 1));
        assertEquals("spectator", h.alpha.mode); assertEquals(2, h.selections);
    }

    @Test void oversizedControlResponseRejectsBeforeMutatingAndShutdownCancelsRemainingWork() {
        Controls h = new Controls(); List<Person> targets = new ArrayList<>();
        for (int i = 0; i < 1000; i++) targets.add(new Person("Target" + i));
        h.selected = new ArrayList<>(targets); Session s = session();
        h.jobs.submit(s, control(1, "players.setFoodLevel", 20), CONTEXT);
        assertEquals("LIMIT_EXCEEDED", response(s, 1, "players.setFoodLevel").error().code());
        assertEquals(0, targets.stream().mapToInt(person -> person.mutations).sum());
        h.selected = new ArrayList<>(targets.subList(0, 300));
        h.jobs.submit(s, control(2, "players.setFoodLevel", 20), CONTEXT);
        int atClose = targets.stream().mapToInt(person -> person.mutations).sum();
        h.jobs.close(); h.jobs.tick();
        assertEquals(atClose, targets.stream().mapToInt(person -> person.mutations).sum());
        assertFalse(s.hasActiveOperation()); assertEquals(0, h.jobs.activeJobs());
    }

    @Test void removingAbsentEffectIsIdempotentAndCancelledRemovalIsVisible() {
        Controls h = new Controls(); Session s = session();
        h.jobs.submit(s, remove(1, "minecraft:speed"), CONTEXT); h.finish(s);
        assertEquals("2", ((JsonNumber) response(s, 1, "effects.remove").result().get("applied")).text());
        h.activeEffects.add(h.alpha.uuid); h.activeEffects.add(h.beta.uuid); h.rejectRemoval = h.beta.uuid;
        h.jobs.submit(s, remove(2, "minecraft:speed"), CONTEXT); h.finish(s);
        Response result = response(s, 2, "effects.remove");
        assertEquals("EFFECT_REJECTED", ((Map<?, ?>) outcomes(result).get(1)).get("code"));
        assertFalse(h.activeEffects.contains(h.alpha.uuid)); assertTrue(h.activeEffects.contains(h.beta.uuid));
        h.rejectRemoval = null;
        h.jobs.submit(s, request(3, "effects.clear", common("@a")), CONTEXT); h.finish(s);
        assertEquals("2", ((JsonNumber) response(s, 3, "effects.clear").result().get("applied")).text());
        assertTrue(h.activeEffects.isEmpty()); assertEquals(2, h.clearCalls);
    }

    @Test void mixedNonlivingSelectionAndUnknownEffectCannotPartiallyRemove() {
        Controls h = new Controls(); Session s = session(); h.mob.living = false;
        h.selected = new ArrayList<>(List.of(h.alpha, h.mob));
        h.jobs.submit(s, remove(1, "minecraft:speed"), CONTEXT);
        assertEquals("INVALID_TARGET", response(s, 1, "effects.remove").error().code());
        h.jobs.submit(s, remove(2, "minecraft:missing_effect"), CONTEXT);
        assertEquals("INVALID_EFFECT", response(s, 2, "effects.remove").error().code());
        assertEquals(0, h.removeCalls); assertEquals(1, h.selections);
    }

    @Test void serviceValidatesModeAndNumericDomainWithoutPaperExceptions() {
        Controls h = new Controls(); PlayerService.Selection selection = new PlayerService.Selection(List.of(h.alpha));
        assertEquals("INVALID_GAME_MODE", assertThrows(PlayerFailure.class,
                () -> h.players.validateControl(selection, "players.setGameMode", "CREATIVE", 0)).code());
        for (double value : new double[] {-1, Double.NaN, Double.POSITIVE_INFINITY}) {
            assertEquals("INVALID_PLAYER_VALUE", assertThrows(PlayerFailure.class,
                    () -> h.players.validateControl(selection, "players.setHealth", null, value)).code());
        }
        assertEquals("INVALID_PLAYER_VALUE", assertThrows(PlayerFailure.class,
                () -> h.players.validateControl(selection, "players.setFoodLevel", null, 1.5)).code());
        assertEquals(0, h.alpha.mutations);
    }
}
