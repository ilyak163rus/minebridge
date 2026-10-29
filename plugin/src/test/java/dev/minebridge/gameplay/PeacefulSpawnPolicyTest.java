package dev.minebridge.gameplay;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class PeacefulSpawnPolicyTest {
    @Test void peacefulBlocksGiantAndHostilesOutsideTheMonsterInterface() {
        for (String type : new String[] {"giant", "zombie", "ghast", "phantom", "slime", "hoglin", "warden", "parched"}) {
            GameplayFailure failure = assertThrows(GameplayFailure.class,
                    () -> PeacefulSpawnPolicy.requireAllowed("minecraft:" + type, true), type);
            assertEquals("PEACEFUL_SPAWN_BLOCKED", failure.code());
        }
    }

    @Test void peacefulAllowsRegistryExceptionsAndOrdinaryEntities() {
        // Enemy/Monster classification would wrongly reject several of these.
        for (String type : new String[] {"shulker", "piglin", "ender_dragon", "wolf", "bee", "pig", "happy_ghast", "lightning_bolt"})
            assertDoesNotThrow(() -> PeacefulSpawnPolicy.requireAllowed("minecraft:" + type, true), type);
    }

    @Test void otherDifficultiesDoNotApplyThePeacefulRestriction() {
        for (String type : new String[] {"giant", "zombie", "wither", "slime"})
            assertDoesNotThrow(() -> PeacefulSpawnPolicy.requireAllowed("minecraft:" + type, false), type);
    }
}
