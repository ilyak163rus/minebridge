package dev.minebridge.gameplay;

import dev.minebridge.blocks.BlockFailure;
import dev.minebridge.blocks.BlockService;
import dev.minebridge.blocks.ChunkService;
import dev.minebridge.players.PlayerFailure;
import dev.minebridge.players.PlayerService;
import dev.minebridge.players.TargetResolver;
import dev.minebridge.protocol.JsonNumber;
import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.CodecException;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;
import dev.minebridge.session.WorldContext;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Gameplay FIFO heads share the block/teleport chunk service and advance only on Paper's thread. */
public final class GameplayJobManager implements AutoCloseable {
    private static final long HEARTBEAT_NANOS = 500_000_000L;
    private static final long BUDGET_NANOS = 2_000_000L;
    private final GameplayService gameplay;
    private final PlayerService players;
    private final ChunkService chunks;
    private final Map<UUID, Job> jobs = new LinkedHashMap<>();
    private int nextJob;
    public GameplayJobManager(GameplayService gameplay, PlayerService players, ChunkService chunks) {
        this.gameplay = gameplay; this.players = players; this.chunks = chunks;
    }
    @SuppressWarnings("unchecked")
    public void submit(Session session, Request request, WorldContext context) {
        try {
            Map<String, Object> p = request.params(); String world = (String) p.get("world");
            players.validateWorld(context, world);
            Job job;
            switch (request.method()) {
                case "players.giveItem" -> {
                    GameplayService.PreparedItem item = gameplay.item(item((Map<String, Object>) p.get("item")));
                    PlayerService.Selection selected = players.select(context, world, (String) p.get("executor"), p.get("targets"));
                    checkResultSize(request, selected.players(), item((Map<String, Object>) p.get("item")));
                    job = new GiveJob(session, request, selected.players(), item, p.get("overflow").equals("drop"));
                }
                case "effects.add" -> {
                    Map<String, Object> e = (Map<String, Object>) p.get("effect");
                    GameplayService.PreparedEffect effect = gameplay.effect(new GameplayService.Effect((String) e.get("key"), integer(e.get("durationTicks")), integer(e.get("level")), (Boolean) e.get("particles")));
                    List<PlayerService.Target> selected = players.resolver().select(context, world, (String) p.get("executor"), p.get("targets"), TargetResolver.Kind.LIVING);
                    checkResultSize(request, selected, null);
                    job = new EffectJob(session, request, selected, effect);
                }
                case "effects.remove", "effects.clear" -> {
                    GameplayService.PreparedEffect effect = request.method().equals("effects.remove")
                            ? gameplay.effectRemoval((String) ((Map<?, ?>) p.get("effect")).get("key")) : null;
                    List<PlayerService.Target> selected = players.resolver().select(context, world, (String) p.get("executor"), p.get("targets"), TargetResolver.Kind.LIVING);
                    checkResultSize(request, selected, null);
                    job = new EffectJob(session, request, selected, effect);
                }
                case "players.setGameMode", "players.setHealth", "players.setFoodLevel" -> {
                    PlayerService.Selection selected = players.select(context, world, (String) p.get("executor"), p.get("targets"));
                    String mode = (String) p.get("mode");
                    double value = p.get("value") == null ? 0 : number(p.get("value"));
                    players.validateControl(selected, request.method(), mode, value);
                    checkResultSize(request, selected.players(), null);
                    job = new ControlJob(session, request, selected.players(), mode, value);
                }
                case "entities.spawn" -> {
                    List<?> position = (List<?>) p.get("position"); double x = number(position.get(0)), y = number(position.get(1)), z = number(position.get(2));
                    BlockService.WorldAccess destination = players.destination(context, world, (String) p.get("destinationWorld"), x, y, z);
                    Map<String, Object> o = (Map<String, Object>) p.get("options");
                    Map<String, Object> block = (Map<String, Object>) o.get("block");
                    GameplayService.SpawnOptions options = new GameplayService.SpawnOptions(o.get("item") == null ? null : item((Map<String, Object>) o.get("item")),
                            block == null ? null : (String) block.get("key"), block == null ? null : (Map<String, String>) block.get("states"), (String) o.get("face"), (String) o.get("owner"));
                    GameplayService.PreparedSpawn spawn = gameplay.spawn((String) ((Map<?, ?>) p.get("entity")).get("key"), options, destination);
                    job = new SpawnJob(session, request, destination, x, y, z, spawn, (String) o.get("face"));
                }
                default -> { fail(session, request, "METHOD_NOT_FOUND", "not-applied"); return; }
            }
            if (!session.tryBeginOperation(request.id())) return;
            jobs.put(session.id(), job); step(job, System.nanoTime() + BUDGET_NANOS);
        } catch (PlayerFailure failure) { fail(session, request, failure.code(), "not-applied"); }
        catch (GameplayFailure failure) { fail(session, request, failure.code(), "not-applied"); }
        catch (BlockFailure failure) { fail(session, request, failure.code(), failure.outcome()); }
        catch (RuntimeException failure) { fail(session, request, "INTERNAL_ERROR", "not-applied"); }
    }
    public void tick() {
        long deadline = System.nanoTime() + BUDGET_NANOS;
        List<Job> active = new ArrayList<>(jobs.values());
        int start = active.isEmpty() ? 0 : Math.floorMod(nextJob, active.size());
        for (int index = 0; index < active.size(); index++) {
            Job job = active.get((start + index) % active.size());
            if (!job.session.isOpen()) { release(job); continue; }
            long now = System.nanoTime();
            if (now - job.lastHeartbeat >= HEARTBEAT_NANOS) {
                job.lastHeartbeat = now;
                job.session.sendFrame(JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "method", "system.progress", "params", Map.of("requestId", job.request.id()))));
            }
            if (System.nanoTime() < deadline) step(job, deadline);
        }
        if (!active.isEmpty()) nextJob = (start + 1) % active.size();
    }
    private void step(Job job, long deadline) {
        try {
            if (!job.session.isOpen()) { release(job); return; }
            Map<String, Object> result = job.advance(deadline);
            if (result != null) {
                job.session.sendResult(job.request, result);
                release(job);
            }
        } catch (GameplayFailure failure) { fail(job.session, job.request, failure.code(), job.entered ? "unknown" : "not-applied"); release(job); }
        catch (BlockFailure failure) { fail(job.session, job.request, failure.code(), job.entered ? "unknown" : "not-applied"); release(job); }
        catch (RuntimeException failure) { fail(job.session, job.request, "INTERNAL_ERROR", job.entered ? "unknown" : "not-applied"); release(job); }
    }
    private abstract static class Job {
        final Session session; final Request request; boolean entered; long lastHeartbeat = System.nanoTime();
        Job(Session session, Request request) { this.session = session; this.request = request; }
        abstract Map<String, Object> advance(long deadline) throws GameplayFailure, BlockFailure;
        void close() {}
    }
    private final class GiveJob extends Job {
        final List<PlayerService.Player> targets; final GameplayService.PreparedItem item; final boolean drop;
        final List<Map<String, Object>> outcomes = new ArrayList<>(); int current, applied; GameplayService.GiveOperation operation;
        GiveJob(Session session, Request request, List<PlayerService.Player> targets, GameplayService.PreparedItem item, boolean drop) {
            super(session, request); this.targets = targets; this.item = item; this.drop = drop;
        }
        @Override Map<String, Object> advance(long deadline) {
            int pieces = 0;
            while (current < targets.size() && pieces++ < 32 && System.nanoTime() < deadline) {
                if (!session.isOpen()) return null;
                if (operation == null) operation = gameplay.give(targets.get(current), item, drop);
                entered = true; operation.step(1);
                if (operation.done()) {
                    GameplayService.GiveResult result = operation.result();
                    outcomes.add(result.toProtocol(targets.get(current).uuid())); if (result.applied()) applied++;
                    operation = null; current++;
                }
            }
            return current == targets.size() ? Map.of("matched", targets.size(), "applied", applied, "targets", outcomes) : null;
        }
    }
    private final class EffectJob extends Job {
        final List<PlayerService.Target> targets; final GameplayService.PreparedEffect effect;
        final List<Map<String, Object>> outcomes = new ArrayList<>(); int current, applied;
        EffectJob(Session session, Request request, List<PlayerService.Target> targets, GameplayService.PreparedEffect effect) {
            super(session, request); this.targets = targets; this.effect = effect;
        }
        @Override Map<String, Object> advance(long deadline) throws GameplayFailure {
            int count = 0;
            while (current < targets.size() && count++ < 128 && System.nanoTime() < deadline) {
                if (!session.isOpen()) return null;
                PlayerService.Target target = targets.get(current++); String code = null; boolean success = false;
                if (!target.valid()) code = target instanceof PlayerService.Player ? "PLAYER_NOT_FOUND" : "ENTITY_NOT_FOUND";
                else {
                    entered = true;
                    try {
                        success = switch (request.method()) {
                            case "effects.add" -> gameplay.addEffect(target, effect);
                            case "effects.remove" -> gameplay.removeEffect(target, effect);
                            case "effects.clear" -> gameplay.clearEffects(target);
                            default -> throw new IllegalStateException("Unknown effect operation");
                        };
                        if (!success) code = "EFFECT_REJECTED";
                    }
                    catch (GameplayFailure failure) {
                        if (!List.of("PLAYER_NOT_FOUND", "ENTITY_NOT_FOUND").contains(failure.code())) throw failure;
                        code = failure.code();
                    }
                }
                Map<String, Object> outcome = new LinkedHashMap<>(); outcome.put("uuid", target.uuid().toString()); outcome.put("applied", success); outcome.put("code", code);
                outcomes.add(outcome); if (success) applied++;
            }
            return current == targets.size() ? Map.of("matched", targets.size(), "applied", applied, "targets", outcomes) : null;
        }
    }
    private final class ControlJob extends Job {
        final List<PlayerService.Player> targets; final String mode; final double value;
        final List<Map<String, Object>> outcomes = new ArrayList<>(); int current, applied;
        ControlJob(Session session, Request request, List<PlayerService.Player> targets, String mode, double value) {
            super(session, request); this.targets = targets; this.mode = mode; this.value = value;
        }
        @Override Map<String, Object> advance(long deadline) {
            int count = 0;
            while (current < targets.size() && count++ < 128 && System.nanoTime() < deadline) {
                if (!session.isOpen()) return null;
                PlayerService.Player target = targets.get(current++); String code = null; boolean success = false;
                if (!target.online()) code = "PLAYER_NOT_FOUND";
                else {
                    entered = true;
                    try {
                        success = players.applyControl(target, request.method(), mode, value);
                        if (!success) code = request.method().equals("players.setGameMode") ? "GAME_MODE_REJECTED" : "PLAYER_VALUE_REJECTED";
                    } catch (RuntimeException failure) { code = "INTERNAL_ERROR"; }
                }
                Map<String, Object> outcome = new LinkedHashMap<>();
                outcome.put("uuid", target.uuid().toString()); outcome.put("applied", success); outcome.put("code", code);
                outcomes.add(outcome); if (success) applied++;
            }
            return current == targets.size() ? Map.of("matched", targets.size(), "applied", applied, "targets", outcomes) : null;
        }
    }
    private final class SpawnJob extends Job {
        final BlockService.WorldAccess world; final double x, y, z; final GameplayService.PreparedSpawn spawn; final String face;
        ChunkService.Lease lease, backing;
        SpawnJob(Session session, Request request, BlockService.WorldAccess world, double x, double y, double z, GameplayService.PreparedSpawn spawn, String face) {
            super(session, request); this.world = world; this.x = x; this.y = y; this.z = z; this.spawn = spawn; this.face = face;
        }
        @Override Map<String, Object> advance(long deadline) throws BlockFailure, GameplayFailure {
            if (lease == null) lease = chunks.acquire(world, Math.floorDiv((int) Math.floor(x), 16), Math.floorDiv((int) Math.floor(z), 16));
            if (!lease.ready()) return null;
            if (face != null) {
                int bx = (int) Math.floor(x) + (face.equals("east") ? -1 : face.equals("west") ? 1 : 0);
                int bz = (int) Math.floor(z) + (face.equals("south") ? -1 : face.equals("north") ? 1 : 0);
                if (backing == null) backing = chunks.acquire(world, Math.floorDiv(bx, 16), Math.floorDiv(bz, 16));
                if (!backing.ready()) return null;
            }
            gameplay.validateSpawnLocation(world, x, y, z, spawn);
            entered = true;
            return Map.of("entity", gameplay.spawn(world, x, y, z, spawn).toProtocol());
        }
        @Override void close() {
            if (lease != null) { lease.close(); lease = null; }
            if (backing != null) { backing.close(); backing = null; }
        }
    }
    private void release(Job job) {
        jobs.remove(job.session.id(), job);
        try { job.close(); } finally { job.session.endOperation(job.request.id()); }
    }
    private static GameplayService.Item item(Map<String, Object> p) {
        @SuppressWarnings("unchecked") List<String> lore = (List<String>) p.get("lore");
        return new GameplayService.Item((String) p.get("key"), integer(p.get("amount")), (String) p.get("name"), lore);
    }
    private static int integer(Object value) { return Integer.parseInt(((JsonNumber) value).text()); }
    private static void checkResultSize(Request request, List<? extends PlayerService.Target> targets, GameplayService.Item item) throws GameplayFailure {
        if (targets.size() > 1024) throw new GameplayFailure("LIMIT_EXCEEDED");
        List<Map<String, Object>> outcomes = targets.stream().map(target -> {
            if (item != null) return new GameplayService.GiveResult(false, "PLAYER_NOT_FOUND", item.amount(), item.amount(), List.of(item), item.amount()).toProtocol(target.uuid());
            return Map.<String, Object>of("uuid", target.uuid().toString(), "applied", false, "code", "PLAYER_VALUE_REJECTED");
        }).toList();
        try { JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", request.id(), "result", Map.of("matched", targets.size(), "applied", 0, "targets", outcomes))); }
        catch (CodecException tooLarge) { throw new GameplayFailure("LIMIT_EXCEEDED"); }
    }
    private static double number(Object value) { return Double.parseDouble(((JsonNumber) value).text()); }
    private static void fail(Session session, Request request, String code, String outcome) {
        if (session.isOpen()) session.sendError(request, code, outcome);
    }
    public int activeJobs() { return jobs.size(); }
    @Override public void close() { for (Job job : new ArrayList<>(jobs.values())) release(job); }
}
