package dev.minebridge.integration;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Base64;
import org.bukkit.World;
import org.bukkit.plugin.java.JavaPlugin;

/** Read-only test fixture: no bridge code, RPC, block access, player access or world creation. */
public final class WorldMetadataProbe extends JavaPlugin {
    @Override public void onEnable() {
        if (!getServer().isPrimaryThread()) throw new IllegalStateException("Game thread required");
        StringBuilder rows = new StringBuilder();
        for (World world : getServer().getWorlds()) {
            rows.append(Base64.getEncoder().encodeToString(world.getName().getBytes(StandardCharsets.UTF_8)))
                    .append('\t').append(world.getUID()).append('\t').append(world.getMinHeight())
                    .append('\t').append(world.getMaxHeight()).append('\n');
        }
        try {
            Files.createDirectories(getDataFolder().toPath());
            Files.writeString(getDataFolder().toPath().resolve("worlds.tsv"), rows, StandardCharsets.UTF_8);
            getLogger().info("Read-only world metadata snapshot saved.");
        } catch (IOException failure) {
            getLogger().severe("Cannot save test world metadata snapshot.");
            getServer().getPluginManager().disablePlugin(this);
        }
    }
}
