package dev.minebridge.session;

import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/** Immutable metadata of the world selected for this connection; no live Paper object escapes. */
public record WorldContext(String name, UUID uuid, int minY, int maxYExclusive) {
    public WorldContext {
        if (name == null || name.isBlank() || minY >= maxYExclusive) {
            throw new IllegalArgumentException("Invalid world metadata");
        }
        Objects.requireNonNull(uuid, "uuid");
    }

    public Map<String, Object> toProtocol() {
        return Map.of("name", name, "uuid", uuid.toString(), "minY", minY, "maxYExclusive", maxYExclusive);
    }
}
