package dev.minebridge.blocks;

/** Inclusive normalized box. Bounded multiplication rejects enormous int32 boxes before overflow. */
public record BlockRegion(int minX, int minY, int minZ, int maxX, int maxY, int maxZ, int volume) {
    public static BlockRegion of(int[] from, int[] to, int maximum) throws BlockFailure {
        int minX = Math.min(from[0], to[0]), maxX = Math.max(from[0], to[0]);
        int minY = Math.min(from[1], to[1]), maxY = Math.max(from[1], to[1]);
        int minZ = Math.min(from[2], to[2]), maxZ = Math.max(from[2], to[2]);
        long count = 1;
        for (long width : new long[] {(long) maxX - minX + 1, (long) maxY - minY + 1, (long) maxZ - minZ + 1}) {
            if (width > maximum || count > maximum / width) throw new BlockFailure("LIMIT_EXCEEDED", "not-applied");
            count *= width;
        }
        return new BlockRegion(minX, minY, minZ, maxX, maxY, maxZ, (int) count);
    }

    public int[] position(int offset) {
        int width = maxX - minX + 1, depth = maxZ - minZ + 1;
        return new int[] {minX + offset % width, minY + offset / (width * depth), minZ + offset / width % depth};
    }

    public boolean overlaps(BlockRegion other) {
        return minX <= other.maxX && maxX >= other.minX && minY <= other.maxY && maxY >= other.minY
                && minZ <= other.maxZ && maxZ >= other.minZ;
    }
}
