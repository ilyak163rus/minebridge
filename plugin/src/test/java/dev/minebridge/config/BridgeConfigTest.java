package dev.minebridge.config;

import static org.junit.jupiter.api.Assertions.*;

import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;

class BridgeConfigTest {
    private static final String SAMPLE_TOKEN = "EXAMPLE-NOT-A-SECRET";

    private static Map<String, Object> validValues() {
        return new HashMap<>(Map.of("listenAddress", "127.0.0.1", "port", 4711));
    }

    @Test void ordinaryClassroomNeedsNeitherWorldNorToken() {
        BridgeConfig config = BridgeConfig.from(validValues());
        assertEquals("127.0.0.1", config.listenAddress());
        assertEquals(4711, config.port());
        assertFalse(config.authEnabled());
        assertEquals("", config.token());
        Map<String, Object> values = validValues();
        values.put("authEnabled", false);
        values.put("token", "");
        assertEquals(config, BridgeConfig.from(values));
    }

    @Test void oldWorldIsIgnoredAndOldTokenDoesNotEnableAuthentication() {
        Map<String, Object> values = validValues();
        values.put("defaultWorld", "a-deleted-world");
        values.put("token", SAMPLE_TOKEN);
        BridgeConfig config = BridgeConfig.from(values);
        assertFalse(config.authEnabled());
        assertEquals(SAMPLE_TOKEN, config.token());
        // A deprecated value cannot prevent startup or choose a different world.
        values.put("defaultWorld", null);
        assertEquals(config, BridgeConfig.from(values));
    }

    @Test void explicitAuthenticationRequiresNonblankTokenAndPreservesItExactly() {
        Map<String, Object> values = validValues();
        values.put("authEnabled", true);
        for (Object invalid : new Object[] {"", " ", "\t\n", true, 4711, null}) {
            values.put("token", invalid);
            assertSafeFailure(values);
        }
        values.remove("token");
        assertSafeFailure(values);
        values.put("token", "  " + SAMPLE_TOKEN + "  ");
        BridgeConfig config = BridgeConfig.from(values);
        assertTrue(config.authEnabled());
        assertEquals("  " + SAMPLE_TOKEN + "  ", config.token());
    }

    @Test void acceptsBothPortBoundaries() {
        for (int port : new int[] {1, 65535}) {
            Map<String, Object> values = validValues();
            values.put("port", port);
            assertEquals(port, BridgeConfig.from(values).port());
        }
    }

    @Test void listenerRequiresNumericAddressWithoutSensitiveDiagnostics() {
        for (String address : new String[] {"127.0.0.1", "0.0.0.0", "::1", "::"}) {
            Map<String, Object> values = validValues();
            values.put("listenAddress", address);
            assertEquals(address, BridgeConfig.from(values).listenAddress());
        }
        for (Object address : new Object[] {"", " ", "localhost", SAMPLE_TOKEN, "127.0.0.999", 4711, true}) {
            Map<String, Object> values = validValues();
            values.put("listenAddress", address);
            assertSafeFailure(values);
        }
    }

    @Test void rejectsMissingAndNullRequiredSettings() {
        for (String key : validValues().keySet()) {
            Map<String, Object> values = validValues();
            values.remove(key);
            assertSafeFailure(values);
            values.put(key, null);
            assertSafeFailure(values);
        }
        assertThrows(IllegalArgumentException.class, () -> BridgeConfig.from(null));
    }

    @Test void rejectsInvalidOptionalSettingTypes() {
        for (Object invalid : new Object[] {"false", "", 0, null}) {
            Map<String, Object> values = validValues();
            values.put("authEnabled", invalid);
            assertSafeFailure(values);
        }
        for (Object invalid : new Object[] {true, 4711, Map.of(), null}) {
            Map<String, Object> values = validValues();
            values.put("token", invalid);
            assertSafeFailure(values);
        }
    }

    @Test void rejectsInvalidPortTypesAndRanges() {
        for (Object invalid : new Object[] {0, -1, 65536, Integer.MAX_VALUE, "4711", true, 4711.0, 4711L}) {
            Map<String, Object> values = validValues();
            values.put("port", invalid);
            assertSafeFailure(values);
        }
    }

    @Test void rejectsUnknownSettingWithoutPrintingItsNameOrValue() {
        Map<String, Object> values = validValues();
        values.put(SAMPLE_TOKEN, SAMPLE_TOKEN);
        assertSafeFailure(values);
    }

    @Test void directConstructionChecksInvariantsAndRedactsToken() {
        assertThrows(IllegalArgumentException.class, () -> new BridgeConfig("127.0.0.1", 0, false, ""));
        assertThrows(IllegalArgumentException.class, () -> new BridgeConfig("127.0.0.1", 4711, true, ""));
        assertThrows(IllegalArgumentException.class, () -> new BridgeConfig("127.0.0.1", 4711, false, null));
        assertThrows(IllegalArgumentException.class, () -> new BridgeConfig(null, 4711, false, ""));
        BridgeConfig config = new BridgeConfig("127.0.0.1", 4711, false, SAMPLE_TOKEN);
        assertTrue(config.toString().contains("token=<redacted>"));
        assertFalse(config.toString().contains(SAMPLE_TOKEN));
    }

    private static void assertSafeFailure(Map<String, Object> values) {
        IllegalArgumentException error = assertThrows(IllegalArgumentException.class, () -> BridgeConfig.from(values));
        assertFalse(error.getMessage().contains(SAMPLE_TOKEN));
    }
}
