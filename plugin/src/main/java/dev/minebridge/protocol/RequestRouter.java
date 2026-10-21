package dev.minebridge.protocol;

import dev.minebridge.config.BridgeConfig;
import dev.minebridge.blocks.BlockFailure;
import dev.minebridge.blocks.BlockService;
import dev.minebridge.execution.ExecutionLimits;
import dev.minebridge.execution.OperationTrace;
import dev.minebridge.session.Session;
import dev.minebridge.session.SessionManager;
import dev.minebridge.session.WorldContext;
import dev.minebridge.transport.TransportLimits;

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
public final class RequestRouter {
    @FunctionalInterface public interface WorldLookup {
        /** Return loaded world metadata, or null. Invoked only from the game-thread dispatcher. */
        WorldContext find(String name);
    }

    private final String defaultWorld;
    private final byte[] expectedTokenDigest;
    private final SessionManager sessions;
    private final WorldLookup worlds;
    private final String pluginVersion;
    private final String serverVersion;
    private final Map<String, Object> limits;
    private final BlockService blocks;
    private final OperationTrace trace;

    public RequestRouter(BridgeConfig config, SessionManager sessions, WorldLookup worlds,
                         String pluginVersion, String serverVersion,
                         TransportLimits transportLimits, ExecutionLimits executionLimits,
                         BlockService blocks, OperationTrace trace) {
        Objects.requireNonNull(config);
        this.defaultWorld = config.defaultWorld();
        this.expectedTokenDigest = digest(config.token());
        this.sessions = Objects.requireNonNull(sessions);
        this.worlds = Objects.requireNonNull(worlds);
        this.pluginVersion = version(pluginVersion);
        this.serverVersion = version(serverVersion);
        this.limits = activeLimits(Objects.requireNonNull(transportLimits), Objects.requireNonNull(executionLimits));
        this.blocks = Objects.requireNonNull(blocks);
        this.trace = Objects.requireNonNull(trace);
    }

    public void pruneClosed() { sessions.pruneClosed(); }

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
        boolean hello = "system.hello".equals(request.method());
        WorldContext selectedWorld = sessions.context(session).orElse(null);
        boolean ready = selectedWorld != null;
        if (!ready && !hello) {
            traceFailure(session, request, selectedWorld, "NOT_READY", "not-applied");
            reject(session, request.id(), "NOT_READY", true);
            return;
        }
        if (ready && hello) { reject(session, request.id(), "INVALID_STATE", true); return; }
        try {
            // State/authentication policy is evaluated before known-command parameter validation.
            if (hello && request.params().get("token") instanceof String token
                    && (token.isBlank() || !MessageDigest.isEqual(expectedTokenDigest, digest(token)))) {
                reject(session, request.id(), "AUTH_FAILED", true);
                return;
            }
            JsonRpcCodec.validateRequestParameters(request);
            if (hello) hello(session, request);
            else if ("blocks.set".equals(request.method())) {
                setBlock(session, request, selectedWorld);
            } else reject(session, request.id(), "METHOD_NOT_FOUND", false);
        } catch (CodecException failure) {
            traceFailure(session, request, selectedWorld, failure.code(), "not-applied");
            if (failure.reply()) reject(session, request.id(), failure.code(), hello || failure.close());
            else session.close();
        } catch (RuntimeException failure) {
            // Never retain/forward exception messages, causes, parameters, or configured credentials.
            traceFailure(session, request, selectedWorld, "INTERNAL_ERROR", "not-applied");
            reject(session, request.id(), "INTERNAL_ERROR", hello);
        }
    }

    private void setBlock(Session session, Request request, WorldContext world) {
        // Encode before any write: a local encoding failure cannot follow a mutation.
        byte[] ack = JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", request.id(),
                "result", Map.of("applied", true)));
        List<?> position = (List<?>) request.params().get("position");
        Map<?, ?> block = (Map<?, ?>) request.params().get("block");
        OperationTrace.Operation operation = trace.operation(session, request, world);
        class Observer implements BlockService.SetterObserver {
            boolean started;
            @Override public void beforeSetter() {
                if (!session.tryBeginOperation(request.id())) throw new OperationCancelled();
                started = true;
                operation.beforeSetter();
            }
            @Override public void afterSetter() { operation.afterSetter(); }
        }
        Observer observer = new Observer();
        try {
            blocks.set(world, (String) request.params().get("world"),
                    Integer.parseInt(((JsonNumber) position.get(0)).text()),
                    Integer.parseInt(((JsonNumber) position.get(1)).text()),
                    Integer.parseInt(((JsonNumber) position.get(2)).text()),
                    (String) block.get("key"), observer);
            // The bounded output publication itself emits ACK_ENQUEUED before writer visibility.
            session.sendFrame(ack, operation::ackEnqueued);
        } catch (BlockFailure failure) {
            if (!observer.started && !session.isOpen()) operation.cancelled();
            else {
                operation.error(failure.code(), failure.outcome());
                reject(session, request.id(), failure.code(), failure.outcome(), false);
            }
        } catch (RuntimeException failure) {
            if (!observer.started && !session.isOpen()) operation.cancelled();
            else {
                String outcome = observer.started ? "unknown" : "not-applied";
                operation.error("INTERNAL_ERROR", outcome);
                reject(session, request.id(), "INTERNAL_ERROR", outcome, false);
            }
        } finally {
            if (observer.started) session.endOperation(request.id());
            operation.finished();
        }
    }

    private void traceFailure(Session session, Request request, WorldContext world, String code, String outcome) {
        if ("blocks.set".equals(request.method()) && !request.notification()) {
            trace.operation(session, request, world).error(code, outcome);
        }
    }

    private static final class OperationCancelled extends RuntimeException {
        OperationCancelled() { super("Operation cancelled", null, false, false); }
    }

    private void hello(Session session, Request request) {
        Map<String, Object> params = request.params();
        Map<?, ?> protocol = (Map<?, ?>) params.get("protocol");
        // Schema has established nonnegative lexical integers. Do not parse unbounded values.
        if (!"1".equals(((JsonNumber) protocol.get("major")).text())) {
            reject(session, request.id(), "PROTOCOL_VERSION", true);
            return;
        }
        String selected = params.get("world") == null ? defaultWorld : (String) params.get("world");
        WorldContext world = worlds.find(selected);
        if (world == null) { reject(session, request.id(), "WORLD_NOT_FOUND", true); return; }
        if (!defaultWorld.equals(selected) || !defaultWorld.equals(world.name())) {
            reject(session, request.id(), "PERMISSION_DENIED", true);
            return;
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("protocol", Map.of("major", 1, "minor", 0));
        result.put("sessionId", session.id().toString());
        result.put("pluginVersion", pluginVersion);
        result.put("serverVersion", serverVersion);
        result.put("world", world.toProtocol());
        result.put("coordinates", "absolute");
        result.put("chunkPolicy", "loaded-only");
        result.put("applyPhysics", true);
        result.put("capabilities", List.of("blocks.set"));
        result.put("limits", limits);
        byte[] frame = JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", request.id(), "result", result));
        if (!sessions.completeHandshake(session, world, frame) && session.isOpen()) {
            reject(session, request.id(), "LIMIT_EXCEEDED", true);
        }
    }

    private static void reject(Session session, Long id, String code, boolean close) {
        reject(session, id, code, "not-applied", close);
    }

    private static void reject(Session session, Long id, String code, String outcome, boolean close) {
        session.sendFrame(JsonRpcCodec.errorFrame(id, code, outcome));
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
