package dev.minebridge.players;

import dev.minebridge.blocks.BlockFailure;
import dev.minebridge.blocks.BlockService;
import dev.minebridge.blocks.ChunkService;
import dev.minebridge.protocol.JsonNumber;
import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;
import dev.minebridge.session.WorldContext;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;

/** Async teleport completion is polled on the game thread, retaining the connection's FIFO head. */
public final class PlayerJobManager implements AutoCloseable {
    private static final long HEARTBEAT_NANOS = 500_000_000L;
    private static final int STARTS_PER_TICK = 128;
    private final PlayerService players;
    private final ChunkService chunks;
    private final Map<UUID, Job> jobs = new LinkedHashMap<>();
    public PlayerJobManager(PlayerService players, ChunkService chunks) { this.players = players; this.chunks = chunks; }

    public void submit(Session session, Request request, WorldContext context) {
        try {
            Map<String, Object> p = request.params();
            String world = (String) p.get("world");
            if (request.method().equals("chat.post")) {
                players.broadcast((String) p.get("message")); respond(session, request, Map.of("applied", true)); return;
            }
            players.validateWorld(context, world);
            if (request.method().equals("players.get")) {
                respond(session, request, Map.of("player", players.dto(players.get((String) p.get("target"))))); return;
            }
            PlayerService.Selection selected = players.select(context, world, (String) p.get("executor"), p.get("targets"));
            switch (request.method()) {
                case "players.list" -> respond(session, request, Map.of("players", selected.players().stream().map(players::dto).toList()));
                case "players.getPos" -> respond(session, request, Map.of("location", players.getPosition(selected).toProtocol()));
                case "players.getGameMode" -> respond(session, request, Map.of("mode", players.getGameMode(selected)));
                case "players.getHealth" -> respond(session, request, Map.of("value", players.getHealth(selected)));
                case "players.getFoodLevel" -> respond(session, request, Map.of("value", players.getFoodLevel(selected)));
                case "players.teleport" -> {
                    List<?> position = (List<?>) p.get("position");
                    double x = number(position.get(0)), y = number(position.get(1)), z = number(position.get(2));
                    BlockService.WorldAccess destination = players.destination(context, world, (String) p.get("destinationWorld"), x, y, z);
                    Job job = new Job(session, request, selected.players(), destination, x, y, z);
                    if (!session.tryBeginOperation(request.id())) return;
                    jobs.put(session.id(), job); step(job);
                }
                default -> fail(session, request, "METHOD_NOT_FOUND", "not-applied");
            }
        } catch (PlayerFailure failure) { fail(session, request, failure.code(), "not-applied"); }
        catch (BlockFailure failure) { fail(session, request, failure.code(), failure.outcome()); }
        catch (RuntimeException failure) { fail(session, request, "INTERNAL_ERROR", "not-applied"); }
    }
    public void tick() {
        for (Job job : new ArrayList<>(jobs.values())) {
            if (!job.session.isOpen()) { release(job); continue; }
            long now = System.nanoTime();
            if (now - job.lastHeartbeat >= HEARTBEAT_NANOS) {
                job.lastHeartbeat = now;
                job.session.sendFrame(JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "method", "system.progress", "params", Map.of("requestId", job.request.id()))));
            }
            step(job);
        }
    }
    private void step(Job job) {
        try {
            if (!job.session.isOpen()) { release(job); return; }
            if (!job.targets.isEmpty()) {
                if (job.lease == null) job.lease = chunks.acquire(job.world, Math.floorDiv((int) Math.floor(job.x), 16), Math.floorDiv((int) Math.floor(job.z), 16));
                if (!job.lease.ready()) return;
            }
            int starts = 0;
            while (job.started < job.targets.size() && starts++ < STARTS_PER_TICK) {
                if (!job.session.isOpen()) { release(job); return; }
                int index = job.started++;
                PlayerService.Player player = job.targets.get(index);
                if (!player.online()) { job.codes.set(index, "PLAYER_NOT_FOUND"); continue; }
                PlayerService.Position at = player.position();
                try {
                    job.entered = true;
                    job.futures.set(index, player.teleport(job.world, job.x, job.y, job.z, at.yaw(), at.pitch()).toCompletableFuture());
                } catch (RuntimeException failure) { job.codes.set(index, "INTERNAL_ERROR"); }
            }
            if (job.started < job.targets.size()) return;
            for (CompletableFuture<Boolean> future : job.futures) if (future != null && !future.isDone()) return;
            List<Map<String, Object>> outcomes = new ArrayList<>(); int applied = 0;
            for (int i = 0; i < job.targets.size(); i++) {
                String code = job.codes.get(i); boolean success = false;
                CompletableFuture<Boolean> future = job.futures.get(i);
                if (future != null) {
                    try { success = Boolean.TRUE.equals(future.getNow(false)); if (!success) code = "TELEPORT_REJECTED"; }
                    catch (CompletionException | java.util.concurrent.CancellationException failure) { code = "INTERNAL_ERROR"; }
                }
                if (success) { applied++; code = null; }
                Map<String, Object> outcome = new LinkedHashMap<>();
                outcome.put("uuid", job.targets.get(i).uuid().toString()); outcome.put("applied", success); outcome.put("code", code);
                outcomes.add(outcome);
            }
            respond(job.session, job.request, Map.of("matched", job.targets.size(), "applied", applied, "targets", outcomes));
            release(job);
        } catch (BlockFailure failure) { fail(job.session, job.request, failure.code(), job.entered ? "unknown" : "not-applied"); release(job); }
        catch (RuntimeException failure) { fail(job.session, job.request, "INTERNAL_ERROR", job.entered ? "unknown" : "not-applied"); release(job); }
    }
    private static double number(Object value) { return Double.parseDouble(((JsonNumber) value).text()); }
    private static void respond(Session session, Request request, Map<String, Object> result) {
        session.sendResult(request, result);
    }
    private static void fail(Session session, Request request, String code, String outcome) {
        if (session.isOpen()) session.sendError(request, code, outcome);
    }
    private void release(Job job) {
        jobs.remove(job.session.id(), job);
        try { if (job.lease != null) { job.lease.close(); job.lease = null; } }
        finally { job.session.endOperation(job.request.id()); }
    }
    public int activeJobs() { return jobs.size(); }
    @Override public void close() { for (Job job : new ArrayList<>(jobs.values())) release(job); }
    private static final class Job {
        final Session session; final Request request; final List<PlayerService.Player> targets;
        final BlockService.WorldAccess world; final double x, y, z;
        final List<CompletableFuture<Boolean>> futures = new ArrayList<>();
        final List<String> codes = new ArrayList<>();
        int started; boolean entered; ChunkService.Lease lease; long lastHeartbeat = System.nanoTime();
        Job(Session session, Request request, List<PlayerService.Player> targets, BlockService.WorldAccess world, double x, double y, double z) {
            this.session = session; this.request = request; this.targets = targets; this.world = world; this.x = x; this.y = y; this.z = z;
            for (int i = 0; i < targets.size(); i++) { futures.add(null); codes.add(null); }
        }
    }
}
