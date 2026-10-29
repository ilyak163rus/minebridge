package dev.minebridge.events;

import java.util.Map;

/** Fixed event rejection; supplied player names and message text are never retained. */
public final class EventFailure extends Exception {
    private final String code;
    private final Map<String, Object> details;

    public EventFailure(String code) {
        this(code, Map.of());
    }

    public EventFailure(String code, Map<String, Object> details) {
        super("Event operation failed");
        this.code = code;
        this.details = Map.copyOf(details);
    }

    public String code() {
        return code;
    }

    public String outcome() {
        return "not-applied";
    }

    public Map<String, Object> details() {
        return details;
    }
}
