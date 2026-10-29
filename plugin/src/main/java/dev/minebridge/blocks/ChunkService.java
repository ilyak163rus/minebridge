package dev.minebridge.blocks;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;

/** Game-thread ownership of async load requests and reference-counted plugin tickets. Never waits. */
public final class ChunkService implements AutoCloseable {
    private record Key(UUID world, int x, int z) {}
    private final Map<Key, Entry> entries = new HashMap<>();
    private boolean closed;

    private static final class Entry {
        final BlockService.WorldAccess world;
        final CompletableFuture<Boolean> future;
        int references;
        boolean ticket;
        Entry(BlockService.WorldAccess world, int x, int z) {
            this.world = world;
            future = world.isChunkLoaded(x, z) ? CompletableFuture.completedFuture(true)
                    : world.loadChunk(x, z).toCompletableFuture();
        }
    }

    public Lease acquire(BlockService.WorldAccess world, int x, int z) {
        if (closed) throw new IllegalStateException("Chunk service closed");
        Key key = new Key(world.uuid(), x, z);
        Entry entry = entries.computeIfAbsent(key, ignored -> new Entry(world, x, z));
        entry.references++;
        return new Lease(key, entry);
    }

    public final class Lease implements AutoCloseable {
        private final Key key;
        private final Entry entry;
        private boolean released;
        private Lease(Key key, Entry entry) { this.key = key; this.entry = entry; }
        public boolean ready() throws BlockFailure {
            if (released || closed) throw new BlockFailure("CHUNK_LOAD_FAILED", "not-applied");
            if (!entry.future.isDone()) return false;
            try {
                if (!Boolean.TRUE.equals(entry.future.getNow(false)) || !entry.world.isChunkLoaded(key.x, key.z)) {
                    throw new BlockFailure("CHUNK_LOAD_FAILED", "not-applied");
                }
                if (!entry.ticket) {
                    entry.world.addChunkTicket(key.x, key.z);
                    entry.ticket = true;
                }
                return true;
            } catch (CompletionException | java.util.concurrent.CancellationException failure) {
                throw new BlockFailure("CHUNK_LOAD_FAILED", "not-applied");
            }
        }
        @Override public void close() {
            if (released) return;
            released = true;
            if (--entry.references == 0) {
                entries.remove(key, entry);
                if (entry.ticket) {
                    entry.ticket = false;
                    entry.world.removeChunkTicket(key.x, key.z);
                }
            }
        }
    }

    public int retainedChunks() { return entries.size(); }
    @Override public void close() {
        closed = true;
        for (Map.Entry<Key, Entry> item : entries.entrySet()) {
            Entry entry = item.getValue();
            if (entry.ticket) {
                entry.ticket = false;
                entry.world.removeChunkTicket(item.getKey().x, item.getKey().z);
            }
        }
        entries.clear();
    }
}
