package dev.minebridge.inventories;

/** Fixed domain rejection; never retains supplied text or native exception details. */
public final class InventoryFailure extends Exception {
    private final String code;
    private final String outcome;

    public InventoryFailure(String code) {
        this(code, "not-applied");
    }

    public InventoryFailure(String code, String outcome) {
        super("Inventory operation failed");
        this.code = code;
        this.outcome = outcome;
    }

    public String code() {
        return code;
    }

    public String outcome() {
        return outcome;
    }
}
