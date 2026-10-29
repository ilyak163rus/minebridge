package dev.minebridge.protocol;

import dev.minebridge.config.BridgeConfig;
import dev.minebridge.blocks.BlockService;
import dev.minebridge.blocks.BlockJobManager;
import dev.minebridge.blocks.ChunkService;
import dev.minebridge.players.PlayerService;
import dev.minebridge.players.PlayerJobManager;
import dev.minebridge.gameplay.GameplayService;
import dev.minebridge.gameplay.GameplayJobManager;
import dev.minebridge.execution.ExecutionLimits;
import dev.minebridge.execution.OperationTrace;
import dev.minebridge.session.Session;
import dev.minebridge.session.SessionManager;
import dev.minebridge.session.SessionActivityLog;
import dev.minebridge.session.WorldContext;
import dev.minebridge.transport.TransportLimits;
import dev.minebridge.worlds.WorldsService;
import dev.minebridge.worlds.WorldFailure;
import dev.minebridge.events.EventsService;
import dev.minebridge.events.EventFailure;
import dev.minebridge.inventories.InventoryService;
import dev.minebridge.inventories.InventoryJobManager;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** Synchronous application routing. GameExecutor must invoke it on the main game thread. */
public final class RequestRouter implements AutoCloseable {
    @FunctionalInterface public interface WorldLookup {
        /** Return loaded world metadata, or null. Invoked only from the game-thread dispatcher. */
        WorldContext find(String nameOrKey);
    }

    private final boolean authEnabled;
    private final byte[] expectedTokenDigest;
    private final SessionManager sessions;
    private final WorldLookup worlds;
    private final String pluginVersion;
    private final String serverVersion;
    private final Map<String, Object> limits;
    private final BlockService blocks;
    private final OperationTrace trace;
    private final BlockJobManager jobs;
    private final ChunkService chunks;
    private final PlayerJobManager playerJobs;
    private final GameplayJobManager gameplayJobs;
    private final SessionActivityLog activityLog;
    private final WorldsService worldSettings;
    private final EventsService events;
    private final InventoryJobManager inventoryJobs;

    public RequestRouter(BridgeConfig config, SessionManager sessions, WorldLookup worlds,
                         String pluginVersion, String serverVersion,
                         TransportLimits transportLimits, ExecutionLimits executionLimits,
                         BlockService blocks, OperationTrace trace) {
        this(config, sessions, worlds, pluginVersion, serverVersion, transportLimits, executionLimits, blocks, trace, null);
    }

    public RequestRouter(BridgeConfig config, SessionManager sessions, WorldLookup worlds,
                         String pluginVersion, String serverVersion,
                         TransportLimits transportLimits, ExecutionLimits executionLimits,
                         BlockService blocks, OperationTrace trace, PlayerService players) {
        this(config, sessions, worlds, pluginVersion, serverVersion, transportLimits, executionLimits, blocks, trace, players, null);
    }

    public RequestRouter(BridgeConfig config, SessionManager sessions, WorldLookup worlds,
                         String pluginVersion, String serverVersion,
                         TransportLimits transportLimits, ExecutionLimits executionLimits,
                         BlockService blocks, OperationTrace trace, PlayerService players, GameplayService gameplay) {
        this(config, sessions, worlds, pluginVersion, serverVersion, transportLimits, executionLimits,
                blocks, trace, players, gameplay, new SessionActivityLog());
    }

    public RequestRouter(BridgeConfig config, SessionManager sessions, WorldLookup worlds,
                         String pluginVersion, String serverVersion,
                         TransportLimits transportLimits, ExecutionLimits executionLimits,
                         BlockService blocks, OperationTrace trace, PlayerService players, GameplayService gameplay,
                         SessionActivityLog activityLog) {
        this(config, sessions, worlds, pluginVersion, serverVersion, transportLimits, executionLimits,
                blocks, trace, players, gameplay, activityLog, null);
    }

    public RequestRouter(BridgeConfig config, SessionManager sessions, WorldLookup worlds,
                         String pluginVersion, String serverVersion,
                         TransportLimits transportLimits, ExecutionLimits executionLimits,
                         BlockService blocks, OperationTrace trace, PlayerService players, GameplayService gameplay,
                         SessionActivityLog activityLog, WorldsService worldSettings) {
        this(config, sessions, worlds, pluginVersion, serverVersion, transportLimits, executionLimits,
                blocks, trace, players, gameplay, activityLog, worldSettings, null);
    }

    public RequestRouter(BridgeConfig config, SessionManager sessions, WorldLookup worlds,
                         String pluginVersion, String serverVersion,
                         TransportLimits transportLimits, ExecutionLimits executionLimits,
                         BlockService blocks, OperationTrace trace, PlayerService players, GameplayService gameplay,
                         SessionActivityLog activityLog, WorldsService worldSettings, EventsService events) {
        this(config, sessions, worlds, pluginVersion, serverVersion, transportLimits, executionLimits,
                blocks, trace, players, gameplay, activityLog, worldSettings, events, null);
    }

    public RequestRouter(BridgeConfig config, SessionManager sessions, WorldLookup worlds,
                         String pluginVersion, String serverVersion,
                         TransportLimits transportLimits, ExecutionLimits executionLimits,
                         BlockService blocks, OperationTrace trace, PlayerService players, GameplayService gameplay,
                         SessionActivityLog activityLog, WorldsService worldSettings, EventsService events,
                         InventoryService inventories) {
        Objects.requireNonNull(config);
        this.authEnabled = config.authEnabled();
        this.expectedTokenDigest = digest(config.token());
        this.sessions = Objects.requireNonNull(sessions);
        this.worlds = Objects.requireNonNull(worlds);
        this.pluginVersion = version(pluginVersion);
        this.serverVersion = version(serverVersion);
        this.limits = activeLimits(Objects.requireNonNull(transportLimits), Objects.requireNonNull(executionLimits));
        this.blocks = Objects.requireNonNull(blocks);
        this.trace = Objects.requireNonNull(trace);
        this.activityLog = Objects.requireNonNull(activityLog);
        this.worldSettings = worldSettings;
        this.events = events;
        this.chunks = new ChunkService();
        this.jobs = new BlockJobManager(blocks, trace, chunks);
        this.playerJobs = players == null ? null : new PlayerJobManager(players, chunks);
        this.gameplayJobs = gameplay == null ? null : new GameplayJobManager(gameplay, Objects.requireNonNull(players), chunks);
        this.inventoryJobs = inventories == null ? null : new InventoryJobManager(inventories, Objects.requireNonNull(players), chunks);
    }

    public void pruneClosed() { jobs.tick(); if (playerJobs != null) playerJobs.tick(); if (gameplayJobs != null) gameplayJobs.tick(); if (inventoryJobs != null) inventoryJobs.tick(); sessions.pruneClosed(); }
    @Override public void close() { jobs.close(); if (playerJobs != null) playerJobs.close(); if (gameplayJobs != null) gameplayJobs.close(); if (inventoryJobs != null) inventoryJobs.close(); chunks.close(); }

    public void route(Session session, Request request) {
        Objects.requireNonNull(session);
        Objects.requireNonNull(request);
        if (!session.isOpen()) {
            if ("blocks.set".equals(request.method()) && !request.notification()) {
                trace.operation(session, request, session.worldContext()).cancelled();
            }
            return;
        }
        if (request.notification()) { session.close(); return; }
        session.logRequest(request);
        boolean hello = "system.hello".equals(request.method());
        WorldContext selectedWorld = sessions.context(session).orElse(null);
        boolean ready = selectedWorld != null;
        if (!ready && !hello) {
            traceFailure(session, request, selectedWorld, "NOT_READY", "not-applied");
            reject(session, request, "NOT_READY", true);
            return;
        }
        if (ready && hello) { reject(session, request, "INVALID_STATE", true); return; }
        try {
            // State/authentication policy is evaluated before known-command parameter validation.
            if (hello && authEnabled && request.params().containsKey("token")
                    && (request.params().get("token") == null
                        || request.params().get("token") instanceof String token
                            && (token.isBlank() || !MessageDigest.isEqual(expectedTokenDigest, digest(token))))) {
                reject(session, request, "AUTH_FAILED", true);
                return;
            }
            JsonRpcCodec.validateRequestParameters(request);
            if (hello) hello(session, request);
            else if (List.of("blocks.set", "blocks.get", "blocks.setRegion", "blocks.getRegion").contains(request.method())) {
                jobs.submit(session, request, selectedWorld);
            } else if (playerJobs != null && List.of("players.get", "players.list", "players.getPos", "players.teleport", "chat.post",
                    "players.getGameMode", "players.getHealth", "players.getFoodLevel").contains(request.method())) {
                playerJobs.submit(session, request, selectedWorld);
            } else if (gameplayJobs != null && List.of("players.giveItem", "effects.add", "entities.spawn", "effects.remove", "effects.clear",
                    "players.setGameMode", "players.setHealth", "players.setFoodLevel").contains(request.method())) {
                gameplayJobs.submit(session, request, selectedWorld);
            } else if (inventoryJobs != null && List.of("inventories.ofBlock", "inventories.ofPlayer", "inventories.getItem", "inventories.getContents",
                    "inventories.setItem", "inventories.clear", "players.setItem").contains(request.method())) {
                inventoryJobs.submit(session, request, selectedWorld);
            } else if (worldSettings != null && List.of("worlds.getTime", "worlds.setTime", "worlds.getWeather", "worlds.setWeather",
                    "worlds.getGameRule", "worlds.setGameRule").contains(request.method())) {
                session.sendResult(request, worldSettings.execute(request, selectedWorld));
            } else if (events != null && List.of("events.subscribe", "events.unsubscribe", "events.pollEvents", "events.getRecent",
                    "events.clearPending").contains(request.method())) {
                Map<String, Object> result = events.execute(session, request, selectedWorld);
                boolean accepted = session.sendResult(request, result);
                events.afterResponse(session, request, accepted);
            } else reject(session, request, "METHOD_NOT_FOUND", false);
        } catch (CodecException failure) {
            if (hello && events != null) events.abortHello(session);
            traceFailure(session, request, selectedWorld, failure.code(), "not-applied");
            if (failure.reply()) reject(session, request, failure.code(), hello || failure.close());
            else session.close();
        } catch (WorldFailure failure) {
            reject(session, request, failure.code(), failure.outcome(), false);
        } catch (EventFailure failure) {
            session.sendError(request, failure.code(), failure.outcome(), failure.details());
            if (hello) { if (events != null) events.abortHello(session); session.closeAfterFlush(); }
        } catch (RuntimeException failure) {
            if (hello && events != null) events.abortHello(session);
            // Never retain/forward exception messages, causes, parameters, or configured credentials.
            traceFailure(session, request, selectedWorld, "INTERNAL_ERROR", "not-applied");
            reject(session, request, "INTERNAL_ERROR", hello);
        }
    }

    private void traceFailure(Session session, Request request, WorldContext world, String code, String outcome) {
        if ("blocks.set".equals(request.method()) && !request.notification()) {
            trace.operation(session, request, world).error(code, outcome);
        }
    }

    private void hello(Session session, Request request) throws EventFailure {
        Map<String, Object> params = request.params();
        Map<?, ?> protocol = (Map<?, ?>) params.get("protocol");
        // Schema has established nonnegative lexical integers. Do not parse unbounded values.
        if (!"2".equals(((JsonNumber) protocol.get("major")).text())) {
            reject(session, request, "PROTOCOL_VERSION", true);
            return;
        }
        String selected = params.get("world") == null ? "minecraft:overworld" : (String) params.get("world");
        WorldContext world = worlds.find(selected);
        if (world == null) { reject(session, request, "WORLD_NOT_FOUND", true); return; }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("protocol", Map.of("major", 2, "minor", 0));
        result.put("sessionId", session.id().toString());
        result.put("pluginVersion", pluginVersion);
        result.put("serverVersion", serverVersion);
        result.put("world", world.toProtocol());
        result.put("coordinates", "absolute");
        result.put("chunkPolicy", "load-generate");
        result.put("applyPhysics", true);
        java.util.ArrayList<String> capabilities = new java.util.ArrayList<>(List.of("blocks.set", "blocks.get", "blocks.setRegion", "blocks.getRegion", "writes.buffered", "session.logging"));
        if (playerJobs != null) capabilities.addAll(List.of("players.get", "players.list", "players.getPos", "players.teleport", "chat.post",
                "players.getGameMode", "players.getHealth", "players.getFoodLevel"));
        if (gameplayJobs != null) capabilities.addAll(List.of("players.giveItem", "effects.add", "entities.spawn", "effects.remove", "effects.clear",
                "players.setGameMode", "players.setHealth", "players.setFoodLevel"));
        if (worldSettings != null) capabilities.addAll(List.of("worlds.getTime", "worlds.setTime", "worlds.getWeather", "worlds.setWeather",
                "worlds.getGameRule", "worlds.setGameRule"));
        if (events != null) capabilities.addAll(List.of("events.subscribe", "events.unsubscribe", "events.pollEvents",
                "events.getRecent", "events.clearPending"));
        if (events != null) for (String eventType : EventsService.supportedTypes()) capabilities.add("events.type." + eventType);
        if (inventoryJobs != null) capabilities.addAll(List.of("inventories.ofBlock", "inventories.ofPlayer", "inventories.getItem",
                "inventories.getContents", "inventories.setItem", "inventories.clear", "players.setItem"));
        result.put("capabilities", capabilities);
        result.put("limits", limits);
        if (events != null) result.put("eventHistory", events.prepareHello(session, world));
        byte[] frame = JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", request.id(), "result", result));
        if (sessions.completeHandshake(session, world, frame)) {
            if (events != null) events.commitHello(session);
            if (Boolean.TRUE.equals(params.get("logging"))) {
                session.enableActivityLog(activityLog);
                session.logRequest(request);
                session.logResult(request, Map.of("logging", true, "connected", true), true);
            }
        } else {
            if (events != null) events.abortHello(session);
            if (session.isOpen()) reject(session, request, "LIMIT_EXCEEDED", true);
        }
    }

    private static void reject(Session session, Request request, String code, boolean close) {
        reject(session, request, code, "not-applied", close);
    }

    private static void reject(Session session, Request request, String code, String outcome, boolean close) {
        session.sendError(request, code, outcome);
        if (close) session.closeAfterFlush();
    }

    private static byte[] digest(String token) {
        try { return MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8)); }
        catch (NoSuchAlgorithmException impossible) { throw new IllegalStateException("Required digest unavailable"); }
    }

    private static String version(String value) {
        if (value == null || value.isBlank()) throw new IllegalArgumentException("Invalid version metadata");
        return value;
    }

    private static BigDecimal seconds(Duration duration) {
        return BigDecimal.valueOf(duration.toNanos(), 9).stripTrailingZeros();
    }

    private static Map<String, Object> activeLimits(TransportLimits transport, ExecutionLimits execution) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("maxFrameBytes", JsonRpcCodec.MAX_FRAME_BYTES);
        result.put("maxJsonDepth", JsonRpcCodec.MAX_JSON_DEPTH);
        result.put("maxSessions", transport.maxSessions());
        result.put("maxQueuedRequests", transport.maxQueuedRequests());
        result.put("maxOutputFrames", transport.maxOutputFrames());
        result.put("handshakeTimeoutSeconds", seconds(transport.handshakeTimeout()));
        result.put("frameAssemblyTimeoutSeconds", seconds(transport.frameAssemblyTimeout()));
        result.put("writeTimeoutSeconds", seconds(transport.writeTimeout()));
        result.put("maxOperationsPerTick", execution.maxOperationsPerTick());
        result.put("maxOperationsPerSessionPerTick", execution.maxOperationsPerSessionPerTick());
        result.put("executorBudgetMillis", BigDecimal.valueOf(execution.budgetNanos(), 6).stripTrailingZeros());
        return Map.copyOf(result);
    }

    @Override public String toString() { return "RequestRouter[credentials=redacted]"; }
}
