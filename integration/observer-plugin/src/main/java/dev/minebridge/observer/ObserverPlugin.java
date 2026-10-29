package dev.minebridge.observer;

import dev.minebridge.execution.OperationTrace;
import dev.minebridge.testing.TestControl;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
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
import org.bukkit.scheduler.BukkitTask;

/** Separate local oracle: world reads use Paper directly, never BlockService or ACK data. */
public final class ObserverPlugin extends JavaPlugin {
    private static final int MAX_CASES = 16;
    private static final int MAX_POSITIONS = 16;
    private static final int MAX_REQUESTS = 4096;
    private final Map<String, CaseState> cases = new LinkedHashMap<>();
    private final Map<ChunkPosition, Integer> holds = new LinkedHashMap<>();
    private final Set<String> requestIds = new HashSet<>();
    private Path results;
    private long sequence;
    private InteractionObserver interactions;
    private ControlObserver controls;
    private ChatObserver chats;
    private GameEventsObserver gameEvents;
    private InventoryObserver inventories;
    private ReleaseObserver release;

    @Override public void onEnable() {
        requireGameThread();
        try {
            results = getDataFolder().toPath().resolve("results");
            Files.createDirectories(results);
            interactions = new InteractionObserver(this);
            getServer().getPluginManager().registerEvents(interactions, this);
            controls = new ControlObserver(this);
            getServer().getPluginManager().registerEvents(controls, this);
            chats = new ChatObserver(this);
            getServer().getPluginManager().registerEvents(chats, this);
            gameEvents = new GameEventsObserver(this);
            getServer().getPluginManager().registerEvents(gameEvents, this);
            inventories = new InventoryObserver(this);
            release = new ReleaseObserver(this);
            getServer().getPluginManager().registerEvents(release, this);
            getLogger().info("Console integration observer ready; no network listener.");
        } catch (IOException failure) {
            getLogger().severe("Cannot initialize local integration observer.");
            getServer().getPluginManager().disablePlugin(this);
        }
    }

    @Override public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        requireGameThread();
        if (!(sender instanceof ConsoleCommandSender) || args.length < 3
                || !args[0].matches("[a-f0-9]{32}") || !args[1].matches("[a-f0-9]{32}")) return true;
        Request request = new Request(args[0], args[1], args[2]);
        // A request path is immutable. A replay must not repeat setup or any mutation.
        if (requestIds.size() >= MAX_REQUESTS || !requestIds.add(request.id())
                || Files.exists(results.resolve(request.id() + ".json"))) return true;
        try {
            Map<String, Object> result = switch (request.action()) {
                case "worlds" -> worlds(args);
                case "serverStats" -> serverStats(args);
                case "gameProtocol" -> gameProtocol(args);
                case "players" -> players(args);
                case "playerPlace" -> playerPlace(args);
                case "entityFixture" -> entityFixture(args);
                case "inventoryFixture", "inventory", "entityState", "entityHold", "livingFixture",
                        "hangingFixture", "nearbyDrops", "lightningEvents", "farSpawnEvents" -> interactions.execute(args);
                case "controlPlayer", "controlWorld", "controlRule", "controlHealthFixture", "controlCancel", "controlState" -> controls.execute(args);
                case "chatState", "chatClear", "chatCancel" -> chats.execute(args);
                case "i03State", "i03Clear", "i03Cancel", "i03Player", "i03PlayerState", "i03Item", "i03Block", "i03Wall",
                        "i03Target", "i03Damage", "i03Death", "i03RespawnAt", "i03Resistance", "i03Remove", "i03SourceShot" -> gameEvents.execute(args);
                case "i04Chest", "i04ReadChest", "i04Split", "i04Merge", "i04Player", "i04EmptyPlayer", "i04Hidden",
                        "i04Fixture", "i04FillLong", "i04Chunk", "i04Unload" -> inventories.execute(args);
                case "releaseBurst", "releaseBurstStatus", "releaseBurstCancel", "releaseDifficulty",
                        "releaseEntities", "releaseRegion", "releaseFill" -> release.execute(args);
                case "setup" -> setup(request, args);
                case "seed" -> seed(request, args);
                case "read" -> read(args);
                case "checkChunk" -> checkChunk(args);
                case "unload" -> { unload(request, args); yield null; }
                case "border" -> border(request, args);
                case "restoreBorder" -> restoreBorder(request, args);
                case "cleanup" -> cleanup(request, args);
                case "gateArm", "track", "gateRelease", "gateStatus" -> gate(request, args);
                case "writerPause", "writerResume", "sessionStats" -> writer(request, args);
                case "status" -> status(args);
                case "trace" -> trace(args);
                default -> throw new ObserverFailure("UNKNOWN_ACTION");
            };
            if (result != null) respond(request, result, null);
        } catch (ObserverFailure failure) {
            respond(request, null, failure.code);
        } catch (IllegalArgumentException failure) {
            respond(request, null, "INVALID_ARGUMENT");
        } catch (RuntimeException failure) {
            // Never serialize exception messages, console arguments or arbitrary plugin state.
            respond(request, null, "OPERATION_FAILED");
        }
        return true;
    }

    private Map<String, Object> worlds(String[] args) {
        length(args, 3);
        List<Object> worlds = new ArrayList<>();
        for (World world : getServer().getWorlds()) worlds.add(map("name", world.getName(),
                "uuid", world.getUID().toString(), "minY", world.getMinHeight(),
                "maxYExclusive", world.getMaxHeight()));
        return map("worlds", worlds);
    }

    private Map<String, Object> serverStats(String[] args) {
        length(args, 3);
        List<Object> tps = new ArrayList<>();
        for (double value : getServer().getTPS()) tps.add(value);
        return map("tps", tps, "averageTickMillis", getServer().getAverageTickTime(),
                "players", getServer().getOnlinePlayers().size(),
                "tick", getServer().getCurrentTick());
    }

    /** Test clients need only framing and a few acknowledgements. Export the
     * pinned server's own packet IDs rather than trusting another MC version.
     * Reflection is deliberately confined to this disposable console observer. */
    private Map<String, Object> gameProtocol(String[] args) {
        length(args, 3);
        try {
            Class<?> provider = Class.forName("net.minecraft.network.ProtocolInfo$DetailsProvider");
            Class<?> detailsType = Class.forName("net.minecraft.network.ProtocolInfo$Details");
            Class<?> visitor = Class.forName("net.minecraft.network.ProtocolInfo$Details$PacketVisitor");
            Class<?> packetType = Class.forName("net.minecraft.network.protocol.PacketType");
            Map<String, Object> result = new LinkedHashMap<>();
            for (String state : List.of("login", "configuration", "game")) {
                String owner = "net.minecraft.network.protocol." + state + "."
                        + Character.toUpperCase(state.charAt(0)) + state.substring(1) + "Protocols";
                for (String direction : List.of("CLIENTBOUND", "SERVERBOUND")) {
                    Map<String, Object> packets = new LinkedHashMap<>();
                    Object template = Class.forName(owner).getField(direction + "_TEMPLATE").get(null);
                    Object details = provider.getMethod("details").invoke(template);
                    Object sink = java.lang.reflect.Proxy.newProxyInstance(visitor.getClassLoader(),
                            new Class<?>[]{visitor}, (proxy, method, values) -> {
                                if (method.getName().equals("accept")) {
                                    String id = packetType.getMethod("id").invoke(values[0]).toString();
                                    packets.put(id, values[1]);
                                }
                                return null;
                            });
                    detailsType.getMethod("listPackets", visitor).invoke(details, sink);
                    result.put(state + "." + direction.toLowerCase(java.util.Locale.ROOT), packets);
                }
            }
            return result;
        } catch (ReflectiveOperationException failure) {
            throw new ObserverFailure("PROTOCOL_EXPORT_FAILED");
        }
    }

    private Map<String, Object> players(String[] args) {
        length(args, 3);
        List<Object> values = new ArrayList<>();
        for (org.bukkit.entity.Player player : getServer().getOnlinePlayers()) {
            Location at = player.getLocation();
            values.add(map("uuid", player.getUniqueId().toString(), "name", player.getName(),
                    "entityId", player.getEntityId(), "world", at.getWorld().getName(),
                    "x", at.getX(), "y", at.getY(), "z", at.getZ(),
                    "yaw", (double) at.getYaw(), "pitch", (double) at.getPitch()));
        }
        return map("players", values);
    }

    private Map<String, Object> playerPlace(String[] args) {
        length(args, 8);
        org.bukkit.entity.Player player = getServer().getPlayerExact(args[3]);
        if (player == null) throw new ObserverFailure("PLAYER_NOT_FOUND");
        World destination = world(args[4]);
        Location at = new Location(destination, finite(args[5]), finite(args[6]), finite(args[7]));
        // Stable fixture positions: these network clients intentionally have no
        // simulation/physics loop and must not fall while another RPC runs.
        player.setGameMode(org.bukkit.GameMode.CREATIVE);
        player.setGravity(false);
        player.setInvulnerable(true);
        if (!player.teleport(at)) throw new ObserverFailure("TELEPORT_FAILED");
        return map("placed", true);
    }

    private Map<String, Object> entityFixture(String[] args) {
        length(args, 7);
        World world = world(args[3]);
        var entity = world.spawnEntity(new Location(world, finite(args[4]), finite(args[5]), finite(args[6])),
                org.bukkit.entity.EntityType.ARMOR_STAND);
        entity.setGravity(false);
        entity.setInvulnerable(true);
        return map("uuid", entity.getUniqueId().toString(), "entityId", entity.getEntityId());
    }

    private Map<String, Object> setup(Request request, String[] args) {
        if (args.length < 5 || args.length > 4 + MAX_POSITIONS) throw new ObserverFailure("INVALID_ARGUMENT");
        if (cases.containsKey(request.caseId())) throw new ObserverFailure("CASE_EXISTS");
        if (cases.size() == MAX_CASES) throw new ObserverFailure("CASE_LIMIT");
        World world = world(args[3]);
        CaseState state = new CaseState();
        List<Position> positions = new ArrayList<>();
        Set<Position> unique = new HashSet<>();
        for (int i = 4; i < args.length; i++) {
            String[] coordinates = args[i].split(",", -1);
            if (coordinates.length != 3) throw new ObserverFailure("INVALID_ARGUMENT");
            Position position = position(world, coordinates[0], coordinates[1], coordinates[2]);
            if (!unique.add(position)) throw new ObserverFailure("DUPLICATE_POSITION");
            for (CaseState existing : cases.values()) {
                if (existing.originals.containsKey(position)) throw new ObserverFailure("POSITION_OWNED");
            }
            positions.add(position);
        }
        cases.put(request.caseId(), state);
        try {
            for (Position p : positions) {
                ChunkPosition chunk = p.chunk();
                if (state.chunks.add(chunk)) hold(world, chunk);
            }
            List<Object> originals = new ArrayList<>();
            for (Position p : positions) {
                BlockData original = world.getBlockAt(p.x(), p.y(), p.z()).getBlockData().clone();
                state.originals.put(p, original);
                originals.add(snapshot(world, p, original));
                world.getBlockAt(p.x(), p.y(), p.z()).setType(Material.AIR, false);
            }
            List<Object> snapshots = new ArrayList<>();
            for (Position p : positions) snapshots.add(snapshot(world, p));
            List<Object> chunks = new ArrayList<>();
            for (ChunkPosition chunk : state.chunks) chunks.add(chunkSnapshot(world, chunk));
            return map("originals", originals, "snapshots", snapshots, "chunks", chunks);
        } catch (RuntimeException failure) {
            restoreCase(request.caseId(), state);
            throw failure;
        }
    }

    private Map<String, Object> read(String[] args) {
        length(args, 7);
        World world = world(args[3]);
        Position p = position(world, args[4], args[5], args[6]);
        if (!world.isChunkLoaded(p.chunk().x(), p.chunk().z())) throw new ObserverFailure("CHUNK_NOT_LOADED");
        return snapshot(world, p);
    }

    /** Fixed stable fixture materials only; this path is not the production setter. */
    private Map<String, Object> seed(Request request, String[] args) {
        length(args, 8);
        World world = world(args[3]);
        Position p = position(world, args[4], args[5], args[6]);
        CaseState state = state(request.caseId());
        if (!state.originals.containsKey(p)) throw new ObserverFailure("POSITION_NOT_OWNED");
        if (!world.isChunkLoaded(p.chunk().x(), p.chunk().z())) throw new ObserverFailure("CHUNK_NOT_LOADED");
        Material material = switch (args[7]) {
            case "minecraft:air" -> Material.AIR;
            case "minecraft:stone" -> Material.STONE;
            case "minecraft:cobblestone" -> Material.COBBLESTONE;
            default -> throw new ObserverFailure("INVALID_FIXTURE_MATERIAL");
        };
        world.getBlockAt(p.x(), p.y(), p.z()).setType(material, false);
        return snapshot(world, p);
    }

    private Map<String, Object> checkChunk(String[] args) {
        length(args, 6);
        World world = world(args[3]);
        ChunkPosition chunk = new ChunkPosition(world.getUID(), integer(args[4]), integer(args[5]));
        return chunkSnapshot(world, chunk);
    }

    private void unload(Request request, String[] args) {
        length(args, 7);
        World world = world(args[3]);
        ChunkPosition chunk = new ChunkPosition(world.getUID(), integer(args[4]), integer(args[5]));
        int deadlineTicks = integer(args[6]);
        if (deadlineTicks < 1 || deadlineTicks > 400) throw new ObserverFailure("INVALID_ARGUMENT");
        CaseState state = state(request.caseId());
        if (state.pending != null) throw new ObserverFailure("CASE_BUSY");
        if (!state.chunks.contains(chunk)) throw new ObserverFailure("CHUNK_NOT_OWNED");
        if (holds.getOrDefault(chunk, 0) != 1) throw new ObserverFailure("CHUNK_SHARED");
        // Restore before releasing our last ticket. No read is allowed to load a chunk.
        restoreChunk(world, state, chunk);
        release(world, chunk);
        state.chunks.remove(chunk);
        if (!world.isChunkLoaded(chunk.x(), chunk.z())) {
            respond(request, chunkSnapshot(world, chunk), null); return;
        }
        if (!world.unloadChunkRequest(chunk.x(), chunk.z())) throw new ObserverFailure("UNLOAD_REJECTED");
        PendingUnload pending = new PendingUnload(request, world.getUID(), chunk, deadlineTicks);
        state.pending = pending;
        pending.task = getServer().getScheduler().runTaskTimer(this, () -> {
            requireGameThread();
            World current = getServer().getWorld(pending.world);
            if (current == null) finishUnload(state, pending, null, "WORLD_NOT_FOUND");
            else if (!current.isChunkLoaded(chunk.x(), chunk.z()))
                finishUnload(state, pending, chunkSnapshot(current, chunk), null);
            else if (++pending.elapsed >= pending.deadline)
                finishUnload(state, pending, null, "UNLOAD_TIMEOUT");
        }, 1L, 1L);
    }

    private void finishUnload(CaseState state, PendingUnload pending, Map<String, Object> result, String error) {
        pending.task.cancel();
        state.pending = null;
        respond(pending.request, result, error);
    }

    private Map<String, Object> border(Request request, String[] args) {
        length(args, 7);
        World world = world(args[3]);
        double size = finite(args[4]), x = finite(args[5]), z = finite(args[6]);
        if (size < 1 || size > 59_999_968 || Math.abs(x) > 29_999_984 || Math.abs(z) > 29_999_984)
            throw new ObserverFailure("INVALID_ARGUMENT");
        CaseState state = state(request.caseId());
        for (var entry : cases.entrySet()) {
            if (!entry.getKey().equals(request.caseId()) && entry.getValue().borders.containsKey(world.getUID()))
                throw new ObserverFailure("BORDER_OWNED");
        }
        WorldBorder border = world.getWorldBorder();
        Location center = border.getCenter();
        state.borders.putIfAbsent(world.getUID(), new SavedBorder(center.getX(), center.getZ(), border.getSize()));
        border.setCenter(x, z); border.setSize(size);
        return map("world", world.getUID().toString(), "size", border.getSize(), "centerX", x, "centerZ", z);
    }

    private Map<String, Object> restoreBorder(Request request, String[] args) {
        length(args, 4);
        World world = world(args[3]);
        SavedBorder saved = state(request.caseId()).borders.remove(world.getUID());
        if (saved == null) throw new ObserverFailure("BORDER_NOT_OWNED");
        restoreBorder(world, saved);
        return map("world", world.getUID().toString(), "size", saved.size(),
                "centerX", saved.x(), "centerZ", saved.z());
    }

    private Map<String, Object> cleanup(Request request, String[] args) {
        length(args, 3);
        TestControl control = control(false);
        if (control != null) {
            try { control.clearCase(request.caseId()); }
            catch (IllegalStateException failure) { throw new ObserverFailure("CASE_BUSY"); }
        }
        CaseState state = state(request.caseId());
        int restored = state.originals.size(), released = state.chunks.size();
        restoreCase(request.caseId(), state);
        return map("restoredBlocks", restored, "releasedChunks", released, "remainingCases", cases.size());
    }

    private Map<String, Object> gate(Request request, String[] args) {
        length(args, 5);
        TestControl control = control(true);
        UUID session = uuid(args[3]);
        long id = Long.parseLong(args[4]);
        if (id < 1 || id > 9_007_199_254_740_991L) throw new ObserverFailure("INVALID_ARGUMENT");
        switch (request.action()) {
            case "gateArm" -> control.arm(request.caseId(), session, id);
            case "track" -> control.track(request.caseId(), session, id);
            case "gateRelease" -> control.release(request.caseId(), session, id);
            default -> { }
        }
        return gateSnapshot(control.gateStatus(request.caseId(), session, id));
    }

    private Map<String, Object> status(String[] args) {
        length(args, 3);
        TestControl control = control(false);
        if (control == null) return map("controlEnabled", false, "sessions", List.of());
        List<Object> sessions = new ArrayList<>();
        for (var session : control.sessions()) sessions.add(sessionSnapshot(session));
        return map("controlEnabled", true, "sessions", sessions);
    }

    private Map<String, Object> writer(Request request, String[] args) {
        length(args, 4);
        TestControl control = control(true);
        UUID session = uuid(args[3]);
        return sessionSnapshot(switch (request.action()) {
            case "writerPause" -> control.writerPause(request.caseId(), session);
            case "writerResume" -> control.writerResume(request.caseId(), session);
            default -> control.sessionStats(request.caseId(), session);
        });
    }

    private static Map<String, Object> sessionSnapshot(TestControl.SessionStatus session) {
        var diagnostic = session.diagnostics();
        return map("sessionId", session.sessionId().toString(), "ready", session.ready(), "open", session.open(),
                "queuedRequests", session.queuedRequests(), "outputFrames", session.outputFrames(),
                "writerPaused", diagnostic.writerPaused(), "requestHighWater", diagnostic.requestHighWater(),
                "outputHighWater", diagnostic.outputHighWater(), "receivedFrames", diagnostic.receivedFrames(),
                "partialFrameBytes", diagnostic.partialFrameBytes());
    }

    private Map<String, Object> trace(String[] args) {
        length(args, 4);
        long after = Long.parseLong(args[3]);
        if (after < 0) throw new ObserverFailure("INVALID_ARGUMENT");
        OperationTrace.Snapshot snapshot = control(true).trace(after);
        List<Object> events = new ArrayList<>();
        for (OperationTrace.Event event : snapshot.events()) events.add(map("sequence", event.sequence(),
                "phase", event.phase().name(), "sessionId", event.sessionId().toString(),
                "requestId", event.requestId(), "applySequence", event.applySequence(),
                "threadId", event.threadId(), "primaryThread", event.primaryThread(), "caseId", event.caseId(),
                "worldName", event.worldName(), "worldUuid", event.worldUuid() == null ? null : event.worldUuid().toString(),
                "x", event.x(), "y", event.y(), "z", event.z(), "errorCode", event.errorCode(), "outcome", event.outcome()));
        return map("events", events, "latestSequence", snapshot.latestSequence(),
                "oldestSequence", snapshot.oldestSequence(), "droppedEvents", snapshot.droppedEvents(),
                "evictedEvents", snapshot.evictedEvents());
    }

    private Map<String, Object> gateSnapshot(TestControl.GateStatus gate) {
        return map("caseId", gate.caseId(), "sessionId", gate.sessionId().toString(), "requestId", gate.requestId(),
                "state", gate.state().toString(), "sessionOpen", gate.sessionOpen(), "queuedRequests", gate.queuedRequests());
    }

    private TestControl control(boolean required) {
        TestControl service = getServer().getServicesManager().load(TestControl.class);
        if (required && service == null) throw new ObserverFailure("CONTROL_DISABLED");
        return service;
    }

    private Map<String, Object> snapshot(World world, Position p) {
        return snapshot(world, p, world.getBlockAt(p.x(), p.y(), p.z()).getBlockData());
    }

    private Map<String, Object> snapshot(World world, Position p, BlockData data) {
        String canonical = data.getAsString();
        int bracket = canonical.indexOf('[');
        String key = bracket < 0 ? canonical : canonical.substring(0, bracket);
        TreeMap<String, Object> properties = new TreeMap<>();
        if (bracket >= 0) {
            for (String pair : canonical.substring(bracket + 1, canonical.length() - 1).split(",")) {
                String[] parts = pair.split("=", 2);
                if (parts.length != 2) throw new ObserverFailure("INVALID_BLOCK_DATA");
                properties.put(parts[0], parts[1]);
            }
        }
        return map("world", world.getUID().toString(), "x", p.x(), "y", p.y(), "z", p.z(),
                "key", key, "properties", properties, "blockData", canonical);
    }

    private Map<String, Object> chunkSnapshot(World world, ChunkPosition chunk) {
        return map("world", world.getUID().toString(), "chunkX", chunk.x(), "chunkZ", chunk.z(),
                "loaded", world.isChunkLoaded(chunk.x(), chunk.z()), "ticketHeld", holds.containsKey(chunk));
    }

    private void hold(World world, ChunkPosition chunk) {
        if (!holds.containsKey(chunk)) world.getChunkAt(chunk.x(), chunk.z()).addPluginChunkTicket(this);
        holds.merge(chunk, 1, Integer::sum);
    }

    private void release(World world, ChunkPosition chunk) {
        Integer count = holds.get(chunk);
        if (count == null) return;
        if (count == 1) {
            world.removePluginChunkTicket(chunk.x(), chunk.z(), this);
            holds.remove(chunk);
        } else holds.put(chunk, count - 1);
    }

    private void restoreChunk(World world, CaseState state, ChunkPosition chunk) {
        if (!world.isChunkLoaded(chunk.x(), chunk.z())) return;
        for (var entry : state.originals.entrySet()) {
            Position p = entry.getKey();
            if (p.chunk().equals(chunk)) world.getBlockAt(p.x(), p.y(), p.z()).setBlockData(entry.getValue(), false);
        }
    }

    private void restoreCase(String caseId, CaseState state) {
        if (state.pending != null) finishUnload(state, state.pending, null, "CANCELLED");
        for (var entry : state.originals.entrySet()) {
            Position p = entry.getKey();
            World world = getServer().getWorld(p.world());
            if (world == null) continue;
            // Cleanup is explicit fixture work. Loading here is necessary after an unload test.
            world.getChunkAt(p.chunk().x(), p.chunk().z());
            world.getBlockAt(p.x(), p.y(), p.z()).setBlockData(entry.getValue(), false);
        }
        for (var entry : state.borders.entrySet()) {
            World world = getServer().getWorld(entry.getKey());
            if (world != null) restoreBorder(world, entry.getValue());
        }
        for (ChunkPosition chunk : state.chunks) {
            World world = getServer().getWorld(chunk.world());
            if (world != null) release(world, chunk);
        }
        cases.remove(caseId);
    }

    private static void restoreBorder(World world, SavedBorder saved) {
        world.getWorldBorder().setCenter(saved.x(), saved.z());
        world.getWorldBorder().setSize(saved.size());
    }

    private void respond(Request request, Map<String, Object> result, String error) {
        requireGameThread();
        Map<String, Object> body = map("schemaVersion", 1, "caseId", request.caseId(), "requestId", request.id(),
                "action", request.action(), "status", error == null ? "ok" : "error", "sequence", ++sequence,
                "tick", getServer().getCurrentTick(), "primaryThread", getServer().isPrimaryThread(),
                "threadId", Thread.currentThread().threadId());
        if (error == null) body.put("result", result); else body.put("error", error);
        try {
            Path temporary = results.resolve(request.id() + ".tmp");
            Files.writeString(temporary, SnapshotJson.encode(body), StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW);
            Files.move(temporary, results.resolve(request.id() + ".json"));
        } catch (IOException failure) {
            getLogger().severe("Cannot publish local observer result.");
        }
    }

    @Override public void onDisable() {
        requireGameThread();
        if (controls != null) { controls.close(); controls = null; }
        TestControl control = control(false);
        for (var entry : new ArrayList<>(cases.entrySet())) {
            try {
                if (control != null) {
                    // Closing these sessions only signals their reactor; it does not
                    // perform socket IO or wait for a worker on the server thread.
                    control.cancelCase(entry.getKey());
                    control.clearCase(entry.getKey());
                }
                restoreCase(entry.getKey(), entry.getValue());
            }
            catch (RuntimeException failure) { getLogger().severe("Cannot restore local observer fixture."); }
        }
        for (World world : getServer().getWorlds()) world.removePluginChunkTickets(this);
        holds.clear();
        cases.clear();
        requestIds.clear();
    }

    private World world(String value) {
        World world = getServer().getWorld(uuid(value));
        if (world == null) throw new ObserverFailure("WORLD_NOT_FOUND");
        return world;
    }
    private CaseState state(String caseId) {
        CaseState state = cases.get(caseId);
        if (state == null) throw new ObserverFailure("CASE_NOT_FOUND");
        return state;
    }
    private Position position(World world, String x, String y, String z) {
        int px = integer(x), py = integer(y), pz = integer(z);
        if (py < world.getMinHeight() || py >= world.getMaxHeight()) throw new ObserverFailure("Y_OUT_OF_BOUNDS");
        if (Math.abs((long) px) > 29_999_984 || Math.abs((long) pz) > 29_999_984)
            throw new ObserverFailure("XZ_OUT_OF_BOUNDS");
        return new Position(world.getUID(), px, py, pz);
    }
    private static UUID uuid(String value) {
        UUID id = UUID.fromString(value);
        if (!id.toString().equals(value)) throw new ObserverFailure("INVALID_ARGUMENT");
        return id;
    }
    private static int integer(String value) {
        if (!value.matches("-?(0|[1-9][0-9]*)")) throw new ObserverFailure("INVALID_ARGUMENT");
        return Integer.parseInt(value);
    }
    private static double finite(String value) {
        double number = Double.parseDouble(value);
        if (!Double.isFinite(number)) throw new ObserverFailure("INVALID_ARGUMENT");
        return number;
    }
    private static void length(String[] args, int expected) {
        if (args.length != expected) throw new ObserverFailure("INVALID_ARGUMENT");
    }
    private void requireGameThread() {
        if (!getServer().isPrimaryThread()) throw new IllegalStateException("Game thread required");
    }
    private static Map<String, Object> map(Object... pairs) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) result.put((String) pairs[i], pairs[i + 1]);
        return result;
    }

    private record Request(String caseId, String id, String action) { }
    private record ChunkPosition(UUID world, int x, int z) { }
    private record Position(UUID world, int x, int y, int z) {
        ChunkPosition chunk() { return new ChunkPosition(world, Math.floorDiv(x, 16), Math.floorDiv(z, 16)); }
    }
    private record SavedBorder(double x, double z, double size) { }
    private static final class CaseState {
        final Map<Position, BlockData> originals = new LinkedHashMap<>();
        final Set<ChunkPosition> chunks = new java.util.LinkedHashSet<>();
        final Map<UUID, SavedBorder> borders = new LinkedHashMap<>();
        PendingUnload pending;
    }
    private static final class PendingUnload {
        final Request request;
        final UUID world;
        final ChunkPosition chunk;
        final int deadline;
        int elapsed;
        BukkitTask task;
        PendingUnload(Request request, UUID world, ChunkPosition chunk, int deadline) {
            this.request = request; this.world = world; this.chunk = chunk; this.deadline = deadline;
        }
    }
    private static final class ObserverFailure extends RuntimeException {
        final String code;
        ObserverFailure(String code) { super(null, null, false, false); this.code = code; }
    }
}
