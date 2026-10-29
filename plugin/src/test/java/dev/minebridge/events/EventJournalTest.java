package dev.minebridge.events;

import static org.junit.jupiter.api.Assertions.*;

import dev.minebridge.session.WorldContext;

import org.junit.jupiter.api.Test;

import java.util.UUID;

class EventJournalTest {
    private static final UUID EPOCH = UUID.randomUUID();
    private static final WorldContext WORLD =
            new WorldContext("lesson", "minecraft:overworld", UUID.randomUUID(), -64, 320);
    private static final EventsService.PlayerSnapshot PLAYER =
            new EventsService.PlayerSnapshot(UUID.randomUUID(), "Alice", 1, WORLD);

    @Test
    void clearedIngressLossDoesNotContaminateLaterEvictionOfPreConnectFacts() throws Exception {
        EventJournal journal = new EventJournal(0, 2, 1_000_000, 2400);
        journal.captureLoss(1, 1, 1, 100);
        journal.append(record(2, 1, "before this connection", 50));
        journal.append(record(3, 1, "also before this connection", 51));
        journal.append(record(4, 1, "still before this connection", 52));
        EventJournal.Page page = journal.poll(1, 4, 75, 100);
        assertTrue(page.events().isEmpty());
        assertEquals(4, page.nextSequence());
        assertFalse(journal.recentStart(1, 75, 100).windowLimited());
        assertEquals(2, journal.retainedEvictionWatermarks("chat.message"));
    }

    @Test
    void pairedFrontierPreservesUnreadLossAndDropsOnlyDominatedOlderPairs() throws Exception {
        EventJournal journal = new EventJournal(0, 1, 1_000_000, 2400);
        journal.captureLoss(1, 1, 1, 100);
        journal.append(record(2, 1, "older pending fact", 50));
        journal.append(record(3, 1, "new pending fact", 51));
        assertHistoryLost("retention", () -> journal.poll(0, 3, 75, 100));
        assertTrue(journal.poll(1, 3, 75, 100).events().isEmpty());
        journal.append(record(4, 1, "genuine post-connect fact", 101));
        journal.append(record(5, 1, "another genuine fact", 102));
        assertHistoryLost("retention", () -> journal.poll(1, 5, 75, 100));
        assertEquals(1, journal.retainedEvictionWatermarks("chat.message"));
        assertEquals(1, journal.poll(4, 5, 75, 100).events().size());
    }

    @Test
    void twoRuntimeStreamsKeepAConstantBoundAcrossRepeatedIngressLosses() throws Exception {
        EventJournal journal = new EventJournal(0, 1, 1_000_000, 2400);
        long sequence = 0;
        for (int group = 0; group < 100; group++) {
            journal.captureLoss(++sequence, 1, group * 100L + 1, group * 100L + 100);
            journal.append(record(++sequence, 1, "delayed normalization", group * 100L + 50));
            journal.append(record(++sequence, 1, "delayed normalization", group * 100L + 51));
            assertTrue(journal.retainedEvictionWatermarks("chat.message") <= 2);
        }
        assertEquals(2, journal.retainedEvictionWatermarks("chat.message"));
        assertTrue(journal.poll(sequence - 2, sequence, 10_000, 100).events().isEmpty());
    }

    @Test
    void anUnsupportedThirdCaptureStreamCannotGrowAnUnboundedEvictionArchive() {
        EventJournal journal = new EventJournal(0, 3, 1_000_000, 2);
        journal.captureLoss(1, 1, 100, 100);
        journal.append(record(2, 1, "second stream", 50));
        journal.append(record(3, 1, "unsupported third stream", 25));
        assertThrows(IllegalStateException.class, () -> journal.expire(3));
        assertEquals(2, journal.retainedEvictionWatermarks("chat.message"));
    }

    @Test
    void recordCountRetentionReportsLostIntervalAndDoesNotInventMissingRecords() throws Exception {
        EventJournal journal = new EventJournal(0, 2, 1_000_000, 2400);
        for (int i = 1; i <= 3; i++) journal.append(record(i, i, "hello", i));
        assertEquals(2, journal.size());
        assertHistoryLost("retention", () -> journal.poll(0, 3, 0, 100));
        EventJournal.Page page = journal.poll(1, 3, 0, 100);
        assertEquals(2, page.events().size());
        assertEquals(3, page.nextSequence());
    }

    @Test
    void byteAndGameTickRetentionAreIndependentBounds() {
        int bytes = record(1, 1, "hello", 1).encodedBytes();
        EventJournal byBytes = new EventJournal(0, 100, bytes + 1, 2400);
        byBytes.append(record(1, 1, "hello", 1));
        byBytes.append(record(2, 1, "hello", 2));
        assertEquals(1, byBytes.size());
        assertTrue(byBytes.retainedBytes() <= bytes + 1);
        EventJournal byAge = new EventJournal(0);
        byAge.append(record(1, 1, "hello", 1));
        byAge.expire(2400);
        assertEquals(1, byAge.size());
        byAge.expire(2401);
        assertEquals(0, byAge.size());
    }

    @Test
    void byteBudgetStopsBeforeUnfittedRecordAndNextPageNeverSkipsIt() throws Exception {
        EventJournal journal = new EventJournal(0);
        for (int i = 1; i <= 3; i++) journal.append(record(i, 1, "\u0000".repeat(4096), i));
        EventJournal.Page first = journal.poll(0, 3, 0, 1000);
        assertEquals(1, first.events().size());
        assertTrue(first.hasMore());
        assertEquals(1, first.nextSequence());
        EventJournal.Page second = journal.poll(first.nextSequence(), first.upperBound(), 0, 1000);
        assertEquals(2L, second.events().getFirst().get("sequence"));
        assertEquals(2, second.nextSequence());
        assertTrue(second.hasMore());
        EventJournal.Page third = journal.poll(2, 3, 0, 1000);
        assertEquals(3, third.nextSequence());
        assertFalse(third.hasMore());
    }

    @Test
    void fixedUpperBoundNeverChasesNewTailAndWorldSequencesMayHaveGaps() throws Exception {
        EventJournal journal = new EventJournal(10);
        journal.append(record(15, 1, "first", 1));
        long upper = journal.tail();
        journal.append(record(20, 1, "later", 2));
        EventJournal.Page page = journal.poll(10, upper, 0, 100);
        assertEquals(1, page.events().size());
        assertEquals(15, page.nextSequence());
        assertFalse(page.hasMore());
    }

    @Test
    void captureLossIsVisibleWithoutLiveSubscriptionsAndClearBoundaryCanSkipIt() throws Exception {
        EventJournal journal = new EventJournal(0);
        journal.append(record(1, 1, "first", 1));
        journal.captureLoss(2, 1, 2, 9);
        journal.append(record(3, 1, "after", 10));
        assertHistoryLost("capture-overflow", () -> journal.poll(0, 3, 0, 100));
        assertHistoryLost("capture-overflow", () -> journal.recentStart(0, 0, 20));
        assertEquals(1, journal.poll(2, 3, 0, 100).events().size());
        assertEquals(0, journal.poll(3, 3, 0, 100).events().size());
    }

    @Test
    void ingressCaptureBaselineSkipsPreConnectFactsAndLossesStillWaitingNormalization()
            throws Exception {
        EventJournal journal = new EventJournal(0);
        journal.append(record(1, 1, "before", 1));
        journal.captureLoss(2, 1, 2, 3);
        journal.append(record(3, 1, "after", 4));
        EventJournal.Page page = journal.poll(0, 3, 3, 100);
        assertEquals(1, page.events().size());
        assertEquals(
                "after",
                ((java.util.Map<?, ?>) page.events().getFirst().get("data")).get("message"));
        EventJournal.RecentStart recent = journal.recentStart(0, 3, 20);
        assertEquals(2, recent.cursor());
    }

    @Test
    void recentStartsInsideAvailableWindowButContinuationDetectsSubsequentEviction()
            throws Exception {
        EventJournal journal = new EventJournal(0, 3, 1_000_000, 2400);
        for (int i = 1; i <= 4; i++) journal.append(record(i, i, "hello", i));
        EventJournal.RecentStart recent = journal.recentStart(0, 0, 3);
        assertTrue(recent.windowLimited());
        assertEquals(1, recent.cursor());
        assertEquals(4, recent.upperBound());
        EventJournal.Page first = journal.poll(recent.cursor(), recent.upperBound(), 0, 1);
        journal.append(record(5, 5, "hello", 5));
        journal.append(record(6, 6, "hello", 6));
        assertHistoryLost(
                "retention", () -> journal.poll(first.nextSequence(), recent.upperBound(), 0, 2));
    }

    @Test
    void recentChoosesLatestRequestedRecordsAndReturnsThemOldestFirst() throws Exception {
        EventJournal journal = new EventJournal(0);
        for (int i = 1; i <= 5; i++) journal.append(record(i, i, "hello", i));
        EventJournal.RecentStart recent = journal.recentStart(0, 0, 2);
        EventJournal.Page page = journal.poll(recent.cursor(), recent.upperBound(), 0, 2);
        assertEquals(4L, page.events().get(0).get("sequence"));
        assertEquals(5L, page.events().get(1).get("sequence"));
        assertFalse(page.hasMore());
    }

    private static EventRecord record(long sequence, long tick, String message, long captureOrder) {
        return new EventRecord(
                UUID.randomUUID(),
                EPOCH,
                sequence,
                tick,
                WORLD,
                PLAYER,
                message,
                false,
                captureOrder);
    }

    private static void assertHistoryLost(String reason, Checked operation) {
        EventFailure failure = assertThrows(EventFailure.class, operation::run);
        assertEquals("EVENT_HISTORY_LOST", failure.code());
        assertEquals("not-applied", failure.outcome());
        assertEquals(reason, failure.details().get("reason"));
    }

    @FunctionalInterface
    private interface Checked {
        Object run() throws Exception;
    }
}
