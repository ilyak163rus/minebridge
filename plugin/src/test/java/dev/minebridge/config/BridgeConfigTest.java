package dev.minebridge.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;

class BridgeConfigTest {
    private static final String SAMPLE_TOKEN = "EXAMPLE-NOT-A-SECRET";

    private static Map<String, Object> validValues() {
        return new HashMap<>(Map.of(
            "listenAddress", "127.0.0.1",
            "port", 4711,
            "defaultWorld", "world",
            "token", SAMPLE_TOKEN
        ));
    }

    @Test
    void acceptsValidSettingsAndPreservesTokenExactly() {
        Map<String, Object> values = validValues();
        values.put("token", "  " + SAMPLE_TOKEN + "  ");

        BridgeConfig config = BridgeConfig.from(values);

        assertEquals("127.0.0.1", config.listenAddress());
        assertEquals(4711, config.port());
        assertEquals("world", config.defaultWorld());
        assertEquals("  " + SAMPLE_TOKEN + "  ", config.token());
        values.put("token", "changed");
        assertEquals("  " + SAMPLE_TOKEN + "  ", config.token());
    }

    @Test
    void acceptsBothPortBoundaries() {
        for (int port : new int[] {1, 65535}) {
            Map<String, Object> values = validValues();
            values.put("port", port);
            assertEquals(port, BridgeConfig.from(values).port());
        }
    }

    @Test
    void listenerRequiresNumericAddressWithoutDnsOrSensitiveDiagnostics() {
        for (String address : new String[] {"127.0.0.1", "0.0.0.0", "::1", "::"}) {
            Map<String, Object> values = validValues();
            values.put("listenAddress", address);
            assertEquals(address, BridgeConfig.from(values).listenAddress());
        }
        for (String address : new String[] {"localhost", "example.invalid", SAMPLE_TOKEN, "127.0.0.999"}) {
            Map<String, Object> values = validValues();
            values.put("listenAddress", address);
            assertSafeFailure(values);
        }
    }

    @Test
    void rejectsMissingAndNullSettings() {
        for (String key : validValues().keySet()) {
            Map<String, Object> values = validValues();
            values.remove(key);
            assertSafeFailure(values);
            values.put(key, null);
            assertSafeFailure(values);
        }
        IllegalArgumentException error = assertThrows(
            IllegalArgumentException.class, () -> BridgeConfig.from(null)
        );
        assertFalse(error.getMessage().contains(SAMPLE_TOKEN));
    }

    @Test
    void rejectsBlankStringsAndNonstringValues() {
        for (String key : new String[] {"listenAddress", "defaultWorld", "token"}) {
            for (Object invalid : new Object[] {"", " ", "\t\n", true, 4711, 1.5, Map.of()}) {
                Map<String, Object> values = validValues();
                values.put(key, invalid);
                assertSafeFailure(values);
            }
        }
    }

    @Test
    void rejectsInvalidPortTypesAndRanges() {
        for (Object invalid : new Object[] {
            0, -1, 65536, Integer.MIN_VALUE, Integer.MAX_VALUE,
            "4711", true, 4711.0, 4711L, Map.of()
        }) {
            Map<String, Object> values = validValues();
            values.put("port", invalid);
            assertSafeFailure(values);
        }
    }

    @Test
    void rejectsUnknownSettingWithoutPrintingItsNameOrValue() {
        Map<String, Object> values = validValues();
        values.put(SAMPLE_TOKEN, SAMPLE_TOKEN);
        assertSafeFailure(values);
    }

    @Test
    void directConstructionAlsoChecksInvariants() {
        assertThrows(IllegalArgumentException.class,
            () -> new BridgeConfig("127.0.0.1", 0, "world", SAMPLE_TOKEN));
        assertThrows(IllegalArgumentException.class,
            () -> new BridgeConfig("127.0.0.1", 4711, "world", ""));
        assertThrows(IllegalArgumentException.class,
            () -> new BridgeConfig("127.0.0.1", 4711, null, SAMPLE_TOKEN));
        assertThrows(IllegalArgumentException.class,
            () -> new BridgeConfig(null, 4711, "world", SAMPLE_TOKEN));
    }

    @Test
    void toStringRedactsToken() {
        BridgeConfig config = BridgeConfig.from(validValues());
        assertTrue(config.toString().contains("token=<redacted>"));
        assertFalse(config.toString().contains(SAMPLE_TOKEN));
    }

    private static void assertSafeFailure(Map<String, Object> values) {
        IllegalArgumentException error = assertThrows(
            IllegalArgumentException.class, () -> BridgeConfig.from(values)
        );
        assertFalse(error.getMessage().contains(SAMPLE_TOKEN));
    }
}
