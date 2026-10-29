package dev.minebridge.blocks;

import dev.minebridge.execution.OperationTrace;
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
import java.util.function.LongSupplier;

/** One resumable head operation per connection. All state and Paper work belongs to the game thread. */
public final class BlockJobManager implements AutoCloseable {
    public static final int MAX_SET_VOLUME = 1_000_000;
    public static final int MAX_READ_VOLUME = 262_144;
    public static final int MAX_READ_PAGE = 64;
    // A normal-sized fill is one bounded server operation, like the default
    // vanilla max_block_modifications budget. The former 256 setters per tick
    // imposed >5 seconds of scheduling alone on a 30x30x30 cube.
    private static final int FAST_SET_VOLUME = 32_768;
    private static final int BLOCKS_PER_SLICE = 32_768;
    private static final long BUDGET_NANOS = 2_000_000L;
    private static final long HEARTBEAT_NANOS = 500_000_000L;
    private final BlockService blocks;
    private final OperationTrace trace;
    private final ChunkService chunks;
    private final boolean ownsChunks;
    private final Map<UUID, Job> jobs = new LinkedHashMap<>();
    private UUID lastVisited;
    private final LongSupplier clock;

    public BlockJobManager(BlockService blocks, OperationTrace trace) { this(blocks, trace, System::nanoTime); }
    public BlockJobManager(BlockService blocks, OperationTrace trace, ChunkService chunks) {
        this(blocks, trace, System::nanoTime, chunks, false);
    }
    BlockJobManager(BlockService blocks, OperationTrace trace, LongSupplier clock) {
        this(blocks, trace, clock, new ChunkService(), true);
    }
    private BlockJobManager(BlockService blocks, OperationTrace trace, LongSupplier clock, ChunkService chunks, boolean ownsChunks) {
        this.blocks = blocks; this.trace = trace; this.clock = clock; this.chunks = chunks; this.ownsChunks = ownsChunks;
    }

    public void submit(Session session, Request request, WorldContext context) {
        Job job = null;
        try {
            job = new Job(session, request, context);
            if (job.mutation) {
                for (Job existing : jobs.values()) {
                    if (existing.mutation && existing.context.uuid().equals(context.uuid())
                            && existing.region.overlaps(job.region)) throw new BlockFailure("REGION_BUSY", "not-applied");
                }
            }
            if (!session.tryBeginOperation(request.id())) { job.operation.cancelled(); job.operation.finished(); return; }
            jobs.put(session.id(), job);
            // Loaded single writes and normal-sized fills complete in this
            // dispatch instead of paying a tick for every tiny block slice.
            step(job, clock.getAsLong() + BUDGET_NANOS);
        } catch (BlockFailure failure) {
            failBeforeStart(session, request, context, failure.code());
        } catch (RuntimeException failure) {
            if (job != null && jobs.get(session.id()) == job) fail(job, "INTERNAL_ERROR");
            else failBeforeStart(session, request, context, "INTERNAL_ERROR");
        }
    }

    public void tick() {
        if (jobs.isEmpty()) return;
        List<Job> active = new ArrayList<>(jobs.values());
        int start = 0;
        for (int i = 0; i < active.size(); i++) if (active.get(i).session.id().equals(lastVisited)) start = (i + 1) % active.size();
        long deadline = clock.getAsLong() + BUDGET_NANOS;
        // Heartbeats and cleanup must run for every job even when another job consumed its budget.
        for (Job job : active) {
            if (!job.session.isOpen()) { cancel(job); continue; }
            if (clock.getAsLong() - job.lastHeartbeat >= HEARTBEAT_NANOS) {
                job.lastHeartbeat = clock.getAsLong();
                job.session.sendFrame(JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "method", "system.progress",
                        "params", Map.of("requestId", job.request.id()))));
            }
        }
        for (int i = 0; i < active.size(); i++) {
            Job job = active.get((start + i) % active.size());
            if (jobs.get(job.session.id()) != job) continue;
            if (clock.getAsLong() >= deadline) break;
            lastVisited = job.session.id();
            step(job, deadline);
        }
    }

    private void step(Job job, long deadline) {
        try {
            if (!job.session.isOpen()) { cancel(job); return; }
            BlockService.WorldAccess world = blocks.world(job.context, job.requestedWorld);
            boolean fastFill = job.mutation && job.region.volume() <= FAST_SET_VOLUME;
            int performed = 0;
            do {
                int[] position = job.mutation ? null : job.position();
                int x = job.mutation ? job.wx : position[0];
                int y = job.mutation ? job.wy : position[1];
                int z = job.mutation ? job.wz : position[2];
                blocks.checkPosition(world, x, y, z);
                int cx = Math.floorDiv(x, 16), cz = Math.floorDiv(z, 16);
                if (job.lease == null || cx != job.chunkX || cz != job.chunkZ) {
                    if (job.lease != null) job.lease.close();
                    job.lease = chunks.acquire(world, cx, cz);
                    job.chunkX = cx; job.chunkZ = cz;
                }
                if (!job.lease.ready()) return;
                if (job.mutation) {
                    // Resolve the target before entering the setter. A lookup
                    // may fail or close the session; neither permits mutation.
                    BlockService.BlockAccess target = world.blockAt(x, y, z);
                    if (!job.session.isOpen()) { cancel(job); return; }
                    if (!job.setterEntered) job.operation.beforeSetter();
                    job.setterEntered = true;
                    target.setType(job.material, true);
                    if (job.count == 1) job.operation.afterSetter();
                } else {
                    BlockService.BlockValue value = world.readBlock(x, y, z);
                    job.values.add(Map.of("position", List.of(x, y, z), "block", value.toProtocol()));
                }
                job.completed++;
                if (!job.session.isOpen()) { cancel(job); return; }
                if (job.completed == job.count) { complete(job); return; }
                job.advance();
                performed++;
            } while (performed < BLOCKS_PER_SLICE && (fastFill || clock.getAsLong() < deadline));
        } catch (BlockFailure failure) { fail(job, failure.code()); }
        catch (RuntimeException failure) { fail(job, "INTERNAL_ERROR"); }
    }

    private void complete(Job job) {
        Map<String, Object> result;
        if (job.mutation) {
            if (job.count != 1) job.operation.afterSetter();
            result = Map.of("applied", true);
        } else if ("blocks.get".equals(job.request.method())) {
            result = Map.of("block", job.values.getFirst().get("block"));
        } else {
            int next = job.offset + job.count;
            result = new LinkedHashMap<>();
            result.put("blocks", job.values);
            result.put("nextOffset", next < job.region.volume() ? next : null);
            result.put("total", job.region.volume());
        }
        job.session.sendResult(job.request, result, job.operation::ackEnqueued);
        release(job);
    }

    private void fail(Job job, String code) {
        if (!job.session.isOpen()) { cancel(job); return; }
        String outcome = job.setterEntered ? "unknown" : "not-applied";
        job.operation.error(code, outcome);
        job.session.sendError(job.request, code, outcome);
        release(job);
    }
    private void cancel(Job job) {
        if (!job.setterEntered) job.operation.cancelled();
        release(job);
    }
    private void release(Job job) {
        jobs.remove(job.session.id(), job);
        try { if (job.lease != null) { job.lease.close(); job.lease = null; } }
        finally {
            job.session.endOperation(job.request.id());
            job.operation.finished();
        }
    }
    private void failBeforeStart(Session session, Request request, WorldContext context, String code) {
        trace.operation(session, request, context).error(code, "not-applied");
        session.sendError(request, code, "not-applied");
    }
    public int activeJobs() { return jobs.size(); }
    public int retainedChunks() { return chunks.retainedChunks(); }
    @Override public void close() {
        for (Job job : new ArrayList<>(jobs.values())) cancel(job);
        if (ownsChunks) chunks.close();
    }

    private final class Job {
        final Session session;
        final Request request;
        final WorldContext context;
        final String requestedWorld;
        final BlockRegion region;
        final boolean mutation;
        final BlockService.BlockMaterial material;
        final OperationTrace.Operation operation;
        final List<Map<String, Object>> values = new ArrayList<>();
        final int offset, count;
        int completed, chunkX, chunkZ;
        int wx, wy, wz, writeChunkX, writeChunkZ;
        boolean setterEntered;
        ChunkService.Lease lease;
        long lastHeartbeat = clock.getAsLong();

        @SuppressWarnings("unchecked")
        Job(Session session, Request request, WorldContext context) throws BlockFailure {
            this.session = session; this.request = request; this.context = context;
            requestedWorld = (String) request.params().get("world");
            mutation = "blocks.set".equals(request.method()) || "blocks.setRegion".equals(request.method());
            boolean single = request.method().equals("blocks.set") || request.method().equals("blocks.get");
            int[] from = coordinates(request.params().get(single ? "position" : "from"));
            int[] to = single ? from : coordinates(request.params().get("to"));
            region = BlockRegion.of(from, to, mutation ? MAX_SET_VOLUME : MAX_READ_VOLUME);
            BlockService.WorldAccess world = blocks.world(context, requestedWorld);
            // An axis-aligned border and height range contain the box iff both opposite corners fit.
            blocks.checkPosition(world, region.minX(), region.minY(), region.minZ());
            blocks.checkPosition(world, region.maxX(), region.maxY(), region.maxZ());
            if (mutation) {
                Map<?, ?> value = (Map<?, ?>) request.params().get("block");
                material = blocks.material((String) value.get("key"), (Map<String, String>) value.get("states"));
            } else material = null;
            offset = request.method().equals("blocks.getRegion") ? number(request.params().get("offset")) : 0;
            if (offset >= region.volume()) throw new BlockFailure("INVALID_PARAMS", "not-applied");
            count = mutation ? region.volume() : single ? 1
                    : Math.min(number(request.params().get("limit")), region.volume() - offset);
            wx = region.minX(); wy = region.minY(); wz = region.minZ();
            writeChunkX = Math.floorDiv(wx, 16); writeChunkZ = Math.floorDiv(wz, 16);
            operation = trace.operation(session, request, context);
        }
        int[] position() { return mutation ? new int[] {wx, wy, wz} : region.position(offset + completed); }
        void advance() {
            // Finish one chunk before moving on: a large fill holds at most one ticket per job.
            int chunkMaxX = (int) Math.min(region.maxX(), (long) writeChunkX * 16 + 15);
            int chunkMaxZ = (int) Math.min(region.maxZ(), (long) writeChunkZ * 16 + 15);
            if (wx < chunkMaxX) { wx++; return; }
            wx = (int) Math.max(region.minX(), (long) writeChunkX * 16);
            if (wz < chunkMaxZ) { wz++; return; }
            wz = (int) Math.max(region.minZ(), (long) writeChunkZ * 16);
            if (wy < region.maxY()) { wy++; return; }
            wy = region.minY();
            if (writeChunkX < Math.floorDiv(region.maxX(), 16)) writeChunkX++;
            else { writeChunkX = Math.floorDiv(region.minX(), 16); writeChunkZ++; }
            wx = (int) Math.max(region.minX(), (long) writeChunkX * 16);
            wz = (int) Math.max(region.minZ(), (long) writeChunkZ * 16);
        }
    }

    private static int[] coordinates(Object value) {
        List<?> position = (List<?>) value;
        return new int[] {number(position.get(0)), number(position.get(1)), number(position.get(2))};
    }
    private static int number(Object value) { return Integer.parseInt(((JsonNumber) value).text()); }
}
