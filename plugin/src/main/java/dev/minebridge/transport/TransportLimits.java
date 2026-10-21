package dev.minebridge.transport;

import java.time.Duration;
import java.util.Objects;

/** Internal transport limits, fixed to the protocol's development defaults in production. */
public record TransportLimits(int maxSessions, int maxQueuedRequests, int maxOutputFrames,
                              Duration handshakeTimeout, Duration frameAssemblyTimeout,
                              Duration writeTimeout) {
    public TransportLimits {
        count(maxSessions);
        count(maxQueuedRequests);
        count(maxOutputFrames);
        timeout(handshakeTimeout);
        timeout(frameAssemblyTimeout);
        timeout(writeTimeout);
    }

    public static TransportLimits defaults() {
        return new TransportLimits(8, 8, 8, Duration.ofSeconds(5),
                Duration.ofSeconds(5), Duration.ofSeconds(5));
    }

    private static void count(int value) {
        if (value < 1 || value > 1024) throw new IllegalArgumentException("Invalid transport capacity");
    }

    private static void timeout(Duration value) {
        Objects.requireNonNull(value, "timeout");
        if (value.isNegative() || value.isZero() || value.compareTo(Duration.ofDays(1)) > 0) {
            throw new IllegalArgumentException("Invalid transport deadline");
        }
    }
}
