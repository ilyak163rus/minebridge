package dev.minebridge.integration;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.World;
import org.bukkit.WorldBorder;
import org.bukkit.block.data.BlockData;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.command.ConsoleCommandSender;
import org.bukkit.plugin.java.JavaPlugin;

/** Separate, local console fixture; no bridge dependency, RPC, player command or worker. */
public final class BlockSmokeProbe extends JavaPlugin {
    private static final int X = 16_384;
    private static final int Z = 16_384;
    private final Map<Position, BlockData> originals = new LinkedHashMap<>();
    private final Map<UUID, SavedBorder> borders = new LinkedHashMap<>();
    private final List<World> prepared = new ArrayList<>();

    @Override public void onEnable() {
        requireGameThread();
        StringBuilder rows = new StringBuilder();
        for (World world : getServer().getWorlds()) {
            rows.append(Base64.getEncoder().encodeToString(world.getName().getBytes(StandardCharsets.UTF_8)))
                    .append('\t').append(world.getUID()).append('\t').append(world.getMinHeight())
                    .append('\t').append(world.getMaxHeight()).append('\n');
        }
        try {
            Files.createDirectories(getDataFolder().toPath());
            Files.createDirectories(getDataFolder().toPath().resolve("results"));
            Files.writeString(getDataFolder().toPath().resolve("worlds.tsv"), rows, StandardCharsets.UTF_8);
            getLogger().info("Console block smoke fixture ready.");
        } catch (IOException failure) {
            getLogger().severe("Cannot initialize local block smoke fixture.");
            getServer().getPluginManager().disablePlugin(this);
        }
    }

    @Override public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        requireGameThread();
        if (!(sender instanceof ConsoleCommandSender)) return true;
        if (args.length < 3 || !args[0].matches("[a-f0-9]{32}")) return true;
        String correlation = args[0];
        try {
            World world = getServer().getWorld(UUID.fromString(args[2]));
            if (world == null) throw new IllegalArgumentException();
            String result = switch (args[1]) {
                case "prepare" -> prepare(world, args);
                case "read" -> read(world, args);
                case "chunk" -> chunk(world, args);
                case "border" -> border(world, args);
                case "restore-border" -> restoreBorder(world, args);
                default -> throw new IllegalArgumentException();
            };
            saveResult(correlation, "ok\t" + result + "\n");
        } catch (RuntimeException failure) {
            saveResult(correlation, "error\toperation-failed\n");
        }
        return true;
    }

    private String prepare(World world, String[] args) {
        if (args.length != 4 || prepared.contains(world)) throw new IllegalArgumentException();
        int y = Integer.parseInt(args[3]);
        if (y < world.getMinHeight() || y >= world.getMaxHeight()) throw new IllegalArgumentException();
        saveBorder(world);
        // Only fixture setup loads/generates chunks. The bridge must never use this path.
        for (int chunkX : new int[] {1024, 1025, -1024}) {
            world.getChunkAt(chunkX, 1024).addPluginChunkTicket(this);
        }
        prepared.add(world);
        for (int dx = 0; dx < 8; dx++) rememberAndClear(world, X + dx, y, Z);
        rememberAndClear(world, -X, y, Z);
        return "prepared\t" + y;
    }

    private void rememberAndClear(World world, int x, int y, int z) {
        Position position = new Position(world.getUID(), x, y, z);
        originals.putIfAbsent(position, world.getBlockAt(x, y, z).getBlockData().clone());
        world.getBlockAt(x, y, z).setType(Material.AIR, false);
    }

    private String read(World world, String[] args) {
        if (args.length != 6) throw new IllegalArgumentException();
        int x = Integer.parseInt(args[3]), y = Integer.parseInt(args[4]), z = Integer.parseInt(args[5]);
        if (y < world.getMinHeight() || y >= world.getMaxHeight()
                || !world.isChunkLoaded(Math.floorDiv(x, 16), Math.floorDiv(z, 16))) {
            throw new IllegalArgumentException();
        }
        return world.getBlockAt(x, y, z).getBlockData().getAsString() + "\ttrue";
    }

    private String chunk(World world, String[] args) {
        if (args.length != 5) throw new IllegalArgumentException();
        return Boolean.toString(world.isChunkLoaded(Integer.parseInt(args[3]), Integer.parseInt(args[4])));
    }

    private String border(World world, String[] args) {
        if (args.length != 6) throw new IllegalArgumentException();
        saveBorder(world);
        WorldBorder border = world.getWorldBorder();
        border.setCenter(Double.parseDouble(args[4]), Double.parseDouble(args[5]));
        border.setSize(Double.parseDouble(args[3]));
        return "border-set";
    }

    private void saveBorder(World world) {
        WorldBorder border = world.getWorldBorder();
        Location center = border.getCenter();
        borders.putIfAbsent(world.getUID(), new SavedBorder(center.getX(), center.getZ(), border.getSize()));
    }

    private String restoreBorder(World world, String[] args) {
        if (args.length != 3) throw new IllegalArgumentException();
        SavedBorder saved = borders.get(world.getUID());
        if (saved == null) throw new IllegalArgumentException();
        world.getWorldBorder().setCenter(saved.x(), saved.z());
        world.getWorldBorder().setSize(saved.size());
        return "border-restored";
    }

    private void saveResult(String correlation, String row) {
        try {
            var results = getDataFolder().toPath().resolve("results");
            var temporary = results.resolve(correlation + ".tmp");
            Files.writeString(temporary, correlation + "\t" + row, StandardCharsets.UTF_8);
            // Each request publishes a fresh path exactly once. Never replace a
            // published result: Windows readers can hold a non-delete-sharing handle.
            Files.move(temporary, results.resolve(correlation + ".tsv"));
        } catch (IOException failure) {
            getLogger().severe("Cannot save local block smoke result.");
        }
    }

    @Override public void onDisable() {
        requireGameThread();
        for (var entry : originals.entrySet()) {
            Position p = entry.getKey();
            World world = getServer().getWorld(p.world());
            if (world != null && world.isChunkLoaded(Math.floorDiv(p.x(), 16), Math.floorDiv(p.z(), 16))) {
                world.getBlockAt(p.x(), p.y(), p.z()).setBlockData(entry.getValue(), false);
            }
        }
        for (var entry : borders.entrySet()) {
            World world = getServer().getWorld(entry.getKey());
            if (world != null) {
                SavedBorder saved = entry.getValue();
                world.getWorldBorder().setCenter(saved.x(), saved.z());
                world.getWorldBorder().setSize(saved.size());
            }
        }
        for (World world : prepared) world.removePluginChunkTickets(this);
        originals.clear();
        borders.clear();
        prepared.clear();
    }

    private void requireGameThread() {
        if (!getServer().isPrimaryThread()) throw new IllegalStateException("Game thread required");
    }

    private record Position(UUID world, int x, int y, int z) { }
    private record SavedBorder(double x, double z, double size) { }
}
