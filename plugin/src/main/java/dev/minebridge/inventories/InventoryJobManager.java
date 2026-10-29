package dev.minebridge.inventories;

import dev.minebridge.blocks.BlockFailure;
import dev.minebridge.blocks.ChunkService;
import dev.minebridge.players.PlayerFailure;
import dev.minebridge.players.PlayerService;
import dev.minebridge.protocol.CodecException;
import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;
import dev.minebridge.session.WorldContext;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** FIFO inventory heads share chunk leases; asynchronous waits never block Paper's game thread. */
public final class InventoryJobManager implements AutoCloseable {
    private static final long BUDGET_NANOS = 2_000_000L;
    private static final long HEARTBEAT_NANOS = 500_000_000L;
    private static final int TARGETS_PER_STEP = 128;
    private final InventoryService inventories;
    private final PlayerService players;
    private final ChunkService chunks;
    private final Map<UUID, Job> jobs = new LinkedHashMap<>();
    private int nextJob;

    public InventoryJobManager(
            InventoryService inventories, PlayerService players, ChunkService chunks) {
        this.inventories = inventories;
        this.players = players;
        this.chunks = chunks;
    }

    public void submit(Session session, Request request, WorldContext context) {
        try {
            Job job;
            if (request.method().equals("players.setItem")) {
                Map<String, Object> p = request.params();
                PlayerService.Selection selected =
                        players.select(
                                context,
                                (String) p.get("world"),
                                (String) p.get("executor"),
                                p.get("targets"));
                InventoryService.PreparedItem item = inventories.item(p.get("item"));
                Object slot = inventories.playerSlot(p.get("slot"));
                checkResultSize(request, selected.players());
                job = new BulkJob(session, request, selected.players(), item, slot);
            } else {
                InventoryService.BlockAddress address =
                        request.method().equals("inventories.ofPlayer")
                                ? null
                                : inventories.address(request, context);
                InventoryService.Handle player =
                        address == null ? inventories.playerReference(request, context) : null;
                job = new SingleJob(session, request, address, player);
            }
            if (!session.tryBeginOperation(request.id())) return;
            jobs.put(session.id(), job);
            step(job, System.nanoTime() + BUDGET_NANOS);
        } catch (InventoryFailure failure) {
            fail(session, request, failure.code(), failure.outcome());
        } catch (PlayerFailure failure) {
            fail(session, request, failure.code(), "not-applied");
        } catch (BlockFailure failure) {
            fail(session, request, failure.code(), failure.outcome());
        } catch (RuntimeException failure) {
            fail(session, request, "INTERNAL_ERROR", "not-applied");
        }
    }

    public void tick() {
        long deadline = System.nanoTime() + BUDGET_NANOS;
        List<Job> active = new ArrayList<>(jobs.values());
        int start = active.isEmpty() ? 0 : Math.floorMod(nextJob, active.size());
        for (int i = 0; i < active.size(); i++) {
            Job job = active.get((start + i) % active.size());
            if (!job.session.isOpen()) {
                release(job);
                continue;
            }
            long now = System.nanoTime();
            if (now - job.heartbeat >= HEARTBEAT_NANOS) {
                job.heartbeat = now;
                job.session.sendFrame(
                        JsonRpcCodec.encodeFrame(
                                Map.of(
                                        "jsonrpc",
                                        "2.0",
                                        "method",
                                        "system.progress",
                                        "params",
                                        Map.of("requestId", job.request.id()))));
            }
            if (System.nanoTime() < deadline) step(job, deadline);
        }
        if (!active.isEmpty()) nextJob = (start + 1) % active.size();
    }

    private void step(Job job, long deadline) {
        try {
            if (!job.session.isOpen()) {
                release(job);
                return;
            }
            Map<String, Object> result = job.advance(deadline);
            if (result != null) {
                job.session.sendResult(job.request, result);
                release(job);
            }
        } catch (InventoryFailure failure) {
            fail(job.session, job.request, failure.code(), failure.outcome());
            release(job);
        } catch (BlockFailure failure) {
            fail(job.session, job.request, failure.code(), "not-applied");
            release(job);
        } catch (RuntimeException failure) {
            fail(
                    job.session,
                    job.request,
                    "INTERNAL_ERROR",
                    job.entered ? "unknown" : "not-applied");
            release(job);
        }
    }

    private abstract static class Job {
        final Session session;
        final Request request;
        long heartbeat = System.nanoTime();
        boolean entered;

        Job(Session session, Request request) {
            this.session = session;
            this.request = request;
        }

        abstract Map<String, Object> advance(long deadline) throws InventoryFailure, BlockFailure;

        void close() {}
    }

    private record Chunk(int x, int z) {}

    private final class SingleJob extends Job {
        final InventoryService.BlockAddress address;
        final InventoryService.Handle player;
        final List<ChunkService.Lease> leases = new ArrayList<>();
        boolean acquired;

        SingleJob(
                Session session,
                Request request,
                InventoryService.BlockAddress address,
                InventoryService.Handle player) {
            super(session, request);
            this.address = address;
            this.player = player;
        }

        @Override
        Map<String, Object> advance(long deadline) throws InventoryFailure, BlockFailure {
            InventoryService.Handle handle = player;
            if (address != null) {
                if (!acquired) {
                    LinkedHashSet<Chunk> required = new LinkedHashSet<>();
                    for (int[] delta :
                            List.of(
                                    new int[] {0, 0},
                                    new int[] {1, 0},
                                    new int[] {-1, 0},
                                    new int[] {0, 1},
                                    new int[] {0, -1}))
                        required.add(
                                new Chunk(
                                        (int) Math.floorDiv((long) address.x() + delta[0], 16),
                                        (int) Math.floorDiv((long) address.z() + delta[1], 16)));
                    for (Chunk chunk : required)
                        leases.add(chunks.acquire(address.world(), chunk.x(), chunk.z()));
                    acquired = true;
                }
                for (ChunkService.Lease lease : leases) if (!lease.ready()) return null;
                handle = inventories.openBlock(address);
            }
            Map<String, Object> result = inventories.execute(handle, request);
            if (request.method().equals("inventories.setItem")
                    || request.method().equals("inventories.clear")) entered = true;
            return result;
        }

        @Override
        void close() {
            try {
                for (ChunkService.Lease lease : leases) {
                    try {
                        lease.close();
                    } catch (RuntimeException cleanupFailure) {
                        // Release every reference and never turn an already queued ACK into a
                        // second response. ChunkService removes its entry before native ticket IO.
                    }
                }
            } finally {
                leases.clear();
            }
        }
    }

    private final class BulkJob extends Job {
        final List<PlayerService.Player> targets;
        final InventoryService.PreparedItem item;
        final Object rawSlot;
        final List<Map<String, Object>> outcomes = new ArrayList<>();
        int validated, current, applied;

        BulkJob(
                Session session,
                Request request,
                List<PlayerService.Player> targets,
                InventoryService.PreparedItem item,
                Object rawSlot) {
            super(session, request);
            this.targets = targets;
            this.item = item;
            this.rawSlot = rawSlot;
        }

        @Override
        Map<String, Object> advance(long deadline) throws InventoryFailure {
            int pieces = 0;
            // No mutation until every selected player has passed slot/stack validation.
            while (validated < targets.size()
                    && pieces++ < TARGETS_PER_STEP
                    && System.nanoTime() < deadline) {
                if (!session.isOpen()) return null;
                InventoryService.Handle handle =
                        inventories.openPlayer(targets.get(validated).uuid());
                inventories.validate(handle, inventories.slot(handle, rawSlot), item);
                validated++;
            }
            if (validated < targets.size()) return null;
            pieces = 0;
            while (current < targets.size()
                    && pieces++ < TARGETS_PER_STEP
                    && System.nanoTime() < deadline) {
                if (!session.isOpen()) return null;
                UUID target = targets.get(current++).uuid();
                boolean success = false;
                String code = null;
                try {
                    InventoryService.Handle handle = inventories.openPlayer(target);
                    Object slot = inventories.slot(handle, rawSlot);
                    entered = true;
                    inventories.write(handle, slot, item);
                    success = true;
                } catch (InventoryFailure failure) {
                    code = failure.code();
                } catch (RuntimeException failure) {
                    code = "INTERNAL_ERROR";
                }
                if (success) applied++;
                outcomes.add(
                        InventoryService.map(
                                "uuid", target.toString(), "applied", success, "code", code));
            }
            return current == targets.size()
                    ? Map.of("matched", targets.size(), "applied", applied, "targets", outcomes)
                    : null;
        }
    }

    private static void checkResultSize(Request request, List<PlayerService.Player> players)
            throws InventoryFailure {
        List<Map<String, Object>> worst =
                players.stream()
                        .map(
                                player ->
                                        InventoryService.map(
                                                "uuid",
                                                player.uuid().toString(),
                                                "applied",
                                                false,
                                                "code",
                                                "INVENTORY_WRITE_REJECTED"))
                        .toList();
        try {
            JsonRpcCodec.encodeFrame(
                    Map.of(
                            "jsonrpc",
                            "2.0",
                            "id",
                            request.id(),
                            "result",
                            Map.of("matched", players.size(), "applied", 0, "targets", worst)));
        } catch (CodecException tooLarge) {
            throw new InventoryFailure("LIMIT_EXCEEDED");
        }
    }

    private static void fail(Session session, Request request, String code, String outcome) {
        if (session.isOpen()) session.sendError(request, code, outcome);
    }

    private void release(Job job) {
        jobs.remove(job.session.id(), job);
        try {
            job.close();
        } finally {
            job.session.endOperation(job.request.id());
        }
    }

    public int activeJobs() {
        return jobs.size();
    }

    @Override
    public void close() {
        for (Job job : new ArrayList<>(jobs.values())) release(job);
    }
}
