package dev.minebridge.worlds;

/** Safe world-operation failure; never retains supplied values or backend exception text. */
public final class WorldFailure extends Exception {
    private final String code;
    private final String outcome;

    public WorldFailure(String code, String outcome) {
        super("World operation failed");
        this.code = code;
        this.outcome = outcome;
    }

    public String code() { return code; }
    public String outcome() { return outcome; }
}
