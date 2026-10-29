package dev.minebridge.events;

import java.util.*;

/** Bounded canonical ring, with type-specific retention and capture-loss boundaries. */
public final class EventJournal {
    public static final int MAX_RECORDS = 4096, MAX_BYTES = 4 * 1024 * 1024, PAGE_BYTES = 32768;
    public static final long MAX_AGE_TICKS = 2400;

    record Entry(
            long sequence,
            long tick,
            long firstCapture,
            long lastCapture,
            EventRecord record,
            int bytes,
            Set<String> types) {
        boolean lost() {
            return record == null;
        }

        boolean matches(String type) {
            return types.contains(type);
        }
    }

    public record Page(
            List<Map<String, Object>> events,
            long nextSequence,
            long upperBound,
            long availableFrom,
            boolean hasMore) {
        public Page {
            events = List.copyOf(events);
        }
    }

    public record RecentStart(long cursor, long upperBound, boolean windowLimited) {}

    private record Watermark(long sequence, long capture) {}

    private final int maxRecords, maxBytes;
    private final long maxAge;
    private final ArrayDeque<Entry> entries = new ArrayDeque<>();
    /*
     * Keep the paired (sequence,capture) boundary, not independent maxima. Chat can normalize
     * old queued facts after publishing a coalesced ingress loss with a newer capture order.
     * The runtime has at most two monotone streams per type: FIFO normalization (including its
     * snapshot failures), and ingress-loss notices. Other native types have one direct stream.
     * The nondominated frontier therefore contains at most two pairs. A future asynchronous
     * source must explicitly revisit this invariant instead of silently broadening loss claims.
     */
    private static final int MAX_EVICTION_FRONTIER = 2;
    private final Map<String, List<Watermark>> evicted = new HashMap<>();
    private long tail;
    private int bytes;

    public EventJournal(long initialSequence) {
        this(initialSequence, MAX_RECORDS, MAX_BYTES, MAX_AGE_TICKS);
    }

    EventJournal(long initialSequence, int maxRecords, int maxBytes, long maxAge) {
        tail = initialSequence;
        this.maxRecords = maxRecords;
        this.maxBytes = maxBytes;
        this.maxAge = maxAge;
    }

    public long tail() {
        return tail;
    }

    public long availableFrom() {
        return availableFrom("chat.message");
    }

    public long availableFrom(String type) {
        for (Entry e : entries) if (e.matches(type)) return e.sequence();
        return tail + 1;
    }

    public int size() {
        return entries.size();
    }

    public int retainedBytes() {
        return bytes;
    }

    public void append(EventRecord record) {
        int count = record.encodedBytes();
        if (count > PAGE_BYTES)
            throw new IllegalArgumentException("Event snapshot exceeds page budget");
        append(
                new Entry(
                        record.sequence(),
                        record.serverTick(),
                        record.captureOrder(),
                        record.captureOrder(),
                        record,
                        count,
                        record.types()));
    }

    public void captureLoss(long sequence, long tick, long first, long last) {
        captureLoss(sequence, tick, first, last, Set.of("chat.message"));
    }

    public void captureLoss(long sequence, long tick, long first, long last, Set<String> types) {
        append(new Entry(sequence, tick, first, last, null, 64, Set.copyOf(types)));
    }

    private void append(Entry entry) {
        if (entry.sequence() <= tail)
            throw new IllegalArgumentException("Event sequence must advance");
        tail = entry.sequence();
        entries.addLast(entry);
        bytes += entry.bytes();
        expire(entry.tick());
    }

    public void expire(long tick) {
        while (!entries.isEmpty()
                && (entries.size() > maxRecords
                        || bytes > maxBytes
                        || tick - entries.getFirst().tick() >= maxAge)) {
            Entry old = entries.getFirst();
            Map<String, List<Watermark>> updated = new HashMap<>();
            for (String type : old.types()) {
                ArrayList<Watermark> frontier =
                        new ArrayList<>(evicted.getOrDefault(type, List.of()));
                // A later sequence with at least the same capture order dominates an older pair.
                while (!frontier.isEmpty() && frontier.getLast().capture() <= old.lastCapture()) {
                    frontier.removeLast();
                }
                frontier.add(new Watermark(old.sequence(), old.lastCapture()));
                if (frontier.size() > MAX_EVICTION_FRONTIER) {
                    // Do not retain an unbounded archive or invent a conservative permanent loss.
                    throw new IllegalStateException(
                            "Event capture stream ordering invariant failed");
                }
                updated.put(type, List.copyOf(frontier));
            }
            entries.removeFirst();
            bytes -= old.bytes();
            evicted.putAll(updated);
        }
    }

    public Page poll(long cursor, long upper, long startCapture, int limit) throws EventFailure {
        return poll("chat.message", cursor, upper, startCapture, limit);
    }

    public Page poll(String type, long cursor, long upper, long startCapture, int limit)
            throws EventFailure {
        check(type, cursor, upper, startCapture);
        List<Map<String, Object>> result = new ArrayList<>();
        int used = 0;
        long next = cursor;
        boolean more = false;
        for (Entry e : entries) {
            if (e.sequence() <= cursor || e.sequence() > upper) continue;
            if (e.lastCapture() <= startCapture || !e.matches(type)) {
                next = e.sequence();
                continue;
            }
            if (e.lost()) throw lost(type, "capture-overflow");
            if (result.size() == limit || used + e.bytes() > PAGE_BYTES) {
                more = true;
                break;
            }
            result.add(e.record().toProtocol(type));
            used += e.bytes();
            next = e.sequence();
        }
        if (!more) next = upper;
        return new Page(result, next, upper, Math.min(availableFrom(type), upper + 1), more);
    }

    public RecentStart recentStart(long startSequence, long startCapture, int limit)
            throws EventFailure {
        return recentStart("chat.message", startSequence, startCapture, limit);
    }

    public RecentStart recentStart(String type, long startSequence, long startCapture, int limit)
            throws EventFailure {
        ArrayDeque<Entry> selected = new ArrayDeque<>();
        for (Entry e : entries) {
            if (e.sequence() <= startSequence
                    || e.lastCapture() <= startCapture
                    || !e.matches(type)) continue;
            selected.addLast(e);
            while (selected.size() > limit) selected.removeFirst();
        }
        for (Entry e : selected) if (e.lost()) throw lost(type, "capture-overflow");
        long cursor =
                selected.isEmpty()
                        ? tail
                        : Math.max(startSequence, selected.getFirst().sequence() - 1);
        return new RecentStart(cursor, tail, lostAfter(type, startSequence, startCapture));
    }

    private void check(String type, long cursor, long upper, long startCapture)
            throws EventFailure {
        if (lostAfter(type, cursor, startCapture)) throw lost(type, "retention");
        for (Entry e : entries)
            if (e.lost()
                    && e.matches(type)
                    && e.sequence() > cursor
                    && e.sequence() <= upper
                    && e.lastCapture() > startCapture) throw lost(type, "capture-overflow");
    }

    private boolean lostAfter(String type, long cursor, long startCapture) {
        for (Watermark mark : evicted.getOrDefault(type, List.of())) {
            if (cursor < mark.sequence() && startCapture < mark.capture()) return true;
        }
        return false;
    }

    int retainedEvictionWatermarks(String type) {
        return evicted.getOrDefault(type, List.of()).size();
    }

    private EventFailure lost(String type, String reason) {
        return new EventFailure(
                "EVENT_HISTORY_LOST",
                Map.of(
                        "reason",
                        reason,
                        "availableFrom",
                        availableFrom(type),
                        "tail",
                        tail,
                        "eventType",
                        type));
    }
}
