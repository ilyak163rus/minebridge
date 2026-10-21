package dev.minebridge.blocks;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class WorldBorderBoundsTest {
    @Test void exactFractionalCentersDoNotFallBackToFlooredBlockCoordinates() {
        assertFalse(WorldBorderBounds.contains(0.5, 0, 0, 0, 1, 100));
        assertFalse(WorldBorderBounds.contains(0, 0.5, 0, 0, 1, 100));
        assertTrue(WorldBorderBounds.contains(-0.5, -0.5, 0, 0, 1, 100));
        assertTrue(WorldBorderBounds.contains(0.5, 0.5, 0.5, 0.5, 1, 100));
        assertFalse(WorldBorderBounds.contains(-0.5, 0.5, 0.5, 0.5, 1, 100));
    }

    @Test void lowerEdgesAreInclusiveAndUpperEdgesExclusiveOnBothAxes() {
        assertTrue(WorldBorderBounds.contains(5.25, -4.75, 10.25, 0.25, 10, 100));
        assertFalse(WorldBorderBounds.contains(15.25, 0.25, 10.25, 0.25, 10, 100));
        assertFalse(WorldBorderBounds.contains(10.25, 5.25, 10.25, 0.25, 10, 100));
        assertFalse(WorldBorderBounds.contains(5.249, 0.25, 10.25, 0.25, 10, 100));
    }

    @Test void clampsAgainstConfiguredAbsoluteWorldSizeRatherThanDefaultCenterLimit() {
        assertTrue(WorldBorderBounds.contains(-100, 0, 0, 0, 1000, 100));
        assertTrue(WorldBorderBounds.contains(99.5, 99.5, 0, 0, 1000, 100));
        assertFalse(WorldBorderBounds.contains(100, 0, 0, 0, 1000, 100));
        assertFalse(WorldBorderBounds.contains(-100.5, 0, 0, 0, 1000, 100));
        assertFalse(WorldBorderBounds.contains(0, 100, 0, 0, 1000, 100));
        assertFalse(WorldBorderBounds.contains(99.5, 0, 900, 0, 1000, 100));
    }
}
