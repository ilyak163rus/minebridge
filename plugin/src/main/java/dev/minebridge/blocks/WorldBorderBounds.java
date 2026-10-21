package dev.minebridge.blocks;

/** Exact block-center policy; lower edges inclusive, upper edges exclusive. */
final class WorldBorderBounds {
    private WorldBorderBounds() { }

    static boolean contains(double x, double z, double centerX, double centerZ,
                            double size, int maxWorldSize) {
        double half = size / 2d;
        double minX = clamp(centerX - half, maxWorldSize);
        double maxX = clamp(centerX + half, maxWorldSize);
        double minZ = clamp(centerZ - half, maxWorldSize);
        double maxZ = clamp(centerZ + half, maxWorldSize);
        return x >= minX && x < maxX && z >= minZ && z < maxZ;
    }

    private static double clamp(double coordinate, int limit) {
        return Math.max(-(double) limit, Math.min((double) limit, coordinate));
    }
}
