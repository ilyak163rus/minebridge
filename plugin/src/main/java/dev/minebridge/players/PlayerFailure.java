package dev.minebridge.players;

/** Fixed rejection, without retaining selector, player or server exception text. */
public final class PlayerFailure extends Exception {
    private final String code;
    public PlayerFailure(String code) { super(code); this.code = code; }
    public String code() { return code; }
}
