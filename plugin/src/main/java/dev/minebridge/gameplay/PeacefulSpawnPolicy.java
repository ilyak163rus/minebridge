package dev.minebridge.gameplay;

import java.util.Set;

/** The pinned Paper 26.2/133 vanilla EntityTypes.Builder.notInPeaceful flags.
 *
 * Bukkit does not expose EntityType.isAllowedInPeaceful. Enemy/Monster are not
 * substitutes: shulkers, piglins and the ender dragon are allowed, while ghasts,
 * slimes and hoglins need not implement Bukkit Monster. No NMS is used at runtime.
 */
final class PeacefulSpawnPolicy {
    private static final Set<String> BLOCKED = Set.of(
            "minecraft:blaze", "minecraft:bogged", "minecraft:breeze", "minecraft:cave_spider",
            "minecraft:creaking", "minecraft:creeper", "minecraft:drowned", "minecraft:elder_guardian",
            "minecraft:enderman", "minecraft:endermite", "minecraft:evoker", "minecraft:ghast",
            "minecraft:giant", "minecraft:guardian", "minecraft:hoglin", "minecraft:husk",
            "minecraft:illusioner", "minecraft:magma_cube", "minecraft:parched", "minecraft:phantom",
            "minecraft:piglin_brute", "minecraft:pillager", "minecraft:ravager", "minecraft:silverfish",
            "minecraft:skeleton", "minecraft:slime", "minecraft:spider", "minecraft:stray",
            "minecraft:vex", "minecraft:vindicator", "minecraft:warden", "minecraft:witch",
            "minecraft:wither", "minecraft:wither_skeleton", "minecraft:zoglin", "minecraft:zombie",
            "minecraft:zombie_villager", "minecraft:zombified_piglin");

    private PeacefulSpawnPolicy() {}

    static void requireAllowed(String entityKey, boolean peaceful) throws GameplayFailure {
        if (peaceful && BLOCKED.contains(entityKey)) throw new GameplayFailure("PEACEFUL_SPAWN_BLOCKED");
    }
}
