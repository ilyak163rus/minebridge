package dev.minebridge.execution;

/** Fixed development budgets shared by dispatch and the hello response. */
public record ExecutionLimits(int maxOperationsPerTick, int maxOperationsPerSessionPerTick,
                              long budgetNanos) {
    public ExecutionLimits {
        if (maxOperationsPerTick < 1 || maxOperationsPerSessionPerTick < 1
                || maxOperationsPerSessionPerTick > maxOperationsPerTick || budgetNanos < 1) {
            throw new IllegalArgumentException("Invalid execution budget");
        }
    }

    public static ExecutionLimits defaults() {
        return new ExecutionLimits(32, 4, 2_000_000L);
    }
}
