package dev.minebridge.blocks;

/** Safe domain failure for one operation. Never retains remote input or backend exception text. */
public final class BlockFailure extends Exception {
    private final String code;
    private final String outcome;

    BlockFailure(String code, String outcome) {
        super("Block operation failed");
        this.code = code;
        this.outcome = outcome;
    }

    public String code() { return code; }
    public String outcome() { return outcome; }

    @Override public String toString() { return "BlockFailure[code=" + code + ", outcome=" + outcome + "]"; }
}
