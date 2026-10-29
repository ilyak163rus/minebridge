package dev.minebridge.gameplay;

/** Fixed gameplay rejection; arbitrary backend messages never cross the protocol boundary. */
public final class GameplayFailure extends Exception {
    private final String code;
    public GameplayFailure(String code) { super(code); this.code = code; }
    public String code() { return code; }
}
