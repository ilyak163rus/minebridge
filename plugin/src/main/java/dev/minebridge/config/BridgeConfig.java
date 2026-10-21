package dev.minebridge.config;

import java.net.InetAddress;
import java.util.Map;
import java.util.Set;

/** Validated settings shared by plugin lifecycle and transport. */
public record BridgeConfig(String listenAddress, int port, String defaultWorld, String token) {
    private static final Set<String> KEYS = Set.of("listenAddress", "port", "defaultWorld", "token");

    public BridgeConfig {
        requireText(listenAddress, "listenAddress");
        // A bind hostname could strand shutdown inside an uncancellable OS DNS
        // lookup. Listener configuration uses numeric IPv4/IPv6 exclusively.
        try {
            InetAddress.ofLiteral(listenAddress);
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("listenAddress must be an IP address literal");
        }
        if (port < 1 || port > 65535) {
            throw new IllegalArgumentException("port must be an integer between 1 and 65535");
        }
        requireText(defaultWorld, "defaultWorld");
        requireText(token, "token");
    }

    /** Read raw YAML values without coercing strings, booleans or floating-point numbers. */
    public static BridgeConfig from(Map<String, ?> values) {
        if (values == null) {
            throw new IllegalArgumentException("config.yml must contain a settings map");
        }
        if (!KEYS.containsAll(values.keySet())) {
            throw new IllegalArgumentException(
                "config.yml contains an unknown setting; expected listenAddress, port, defaultWorld and token"
            );
        }
        Object rawPort = values.get("port");
        if (!(rawPort instanceof Integer port)) {
            throw new IllegalArgumentException("port must be an integer between 1 and 65535");
        }
        return new BridgeConfig(
            readText(values, "listenAddress"),
            port,
            readText(values, "defaultWorld"),
            readText(values, "token")
        );
    }

    private static String readText(Map<String, ?> values, String key) {
        Object value = values.get(key);
        if (!(value instanceof String text)) {
            throw new IllegalArgumentException(key + " must be a nonblank string");
        }
        requireText(text, key);
        return text;
    }

    private static void requireText(String value, String key) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(key + " must be a nonblank string");
        }
    }

    /** Record-generated toString would reveal the lesson token in diagnostics. */
    @Override
    public String toString() {
        return "BridgeConfig[listenAddress=" + listenAddress + ", port=" + port
            + ", defaultWorld=" + defaultWorld + ", token=<redacted>]";
    }
}
