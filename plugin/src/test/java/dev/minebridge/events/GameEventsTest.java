package dev.minebridge.events;

import static dev.minebridge.events.EventSnapshotCache.map;

import static org.junit.jupiter.api.Assertions.*;

import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;
import dev.minebridge.session.WorldContext;

import org.junit.jupiter.api.Test;

import java.util.*;

class GameEventsTest {
    private static final UUID EPOCH = UUID.randomUUID(),
            ALICE = UUID.randomUUID(),
            MOB = UUID.randomUUID();
    private static final WorldContext WORLD =
            new WorldContext("lesson", "minecraft:overworld", UUID.randomUUID(), -64, 320);

    private static Map<String, Object> player() {
        return Map.of(
                "uuid",
                ALICE.toString(),
                "entityId",
                1,
                "key",
                "minecraft:player",
                "living",
                true,
                "name",
                "Alice");
    }

    private static Map<String, Object> mob() {
        return map(
                "uuid",
                MOB.toString(),
                "entityId",
                2,
                "key",
                "minecraft:zombie",
                "living",
                true,
                "name",
                null);
    }

    private static EventRecord record(
            long sequence, String type, Map<String, Object> data, UUID actor) {
        return new EventRecord(
                UUID.randomUUID(),
                EPOCH,
                sequence,
                1,
                WORLD,
                type,
                data,
                actor,
                List.of(1d, 2d, 3d),
                "minecraft:stone",
                sequence);
    }

    private static EventRecord damage(long sequence, boolean isPlayer) {
        return record(
                sequence,
                "entity.damage",
                map(
                        "victim",
                        isPlayer ? player() : mob(),
                        "directSource",
                        null,
                        "causingEntity",
                        null,
                        "cause",
                        "FALL",
                        "rawDamage",
                        2d,
                        "finalDamage",
                        2d,
                        "cancelled",
                        false),
                isPlayer ? ALICE : null);
    }

    @Test
    void damageProjectionSharesCanonicalIdentityAndSequenceWithoutAnotherJournalEntry()
            throws Exception {
        EventJournal journal = new EventJournal(0);
        EventRecord fact = damage(1, true);
        journal.append(fact);
        journal.append(damage(2, false));
        var canonical = journal.poll("entity.damage", 0, 2, 0, 100);
        var projection = journal.poll("player.damage", 0, 2, 0, 100);
        assertEquals(2, journal.size());
        assertEquals(2, canonical.events().size());
        assertEquals(1, projection.events().size());
        assertEquals(
                canonical.events().getFirst().get("eventId"),
                projection.events().getFirst().get("eventId"));
        assertEquals(1L, projection.events().getFirst().get("sequence"));
        assertEquals("player.damage", projection.events().getFirst().get("eventType"));
        assertEquals(
                canonical.events().getFirst().get("data"),
                projection.events().getFirst().get("data"));
    }

    @Test
    void otherTypeEvictionIsNotHistoryLossAndSparseCursorScansThroughUnrelatedFacts()
            throws Exception {
        EventJournal journal = new EventJournal(0, 2, 1000000, 2400);
        journal.append(damage(1, false));
        journal.append(damage(2, false));
        journal.append(damage(3, false));
        var chat = journal.poll("chat.message", 0, 3, 0, 100);
        assertTrue(chat.events().isEmpty());
        assertEquals(3, chat.nextSequence());
        EventFailure lost =
                assertThrows(EventFailure.class, () -> journal.poll("entity.damage", 0, 3, 0, 100));
        assertEquals("entity.damage", lost.details().get("eventType"));
        assertTrue(journal.poll("player.damage", 0, 3, 0, 100).events().isEmpty());
    }

    @Test
    void projectedMembershipHasOwnEvictionBoundary() throws Exception {
        EventJournal journal = new EventJournal(0, 1, 1000000, 2400);
        journal.append(damage(1, true));
        journal.append(damage(2, false));
        assertThrows(EventFailure.class, () -> journal.poll("player.damage", 0, 2, 0, 100));
        assertTrue(journal.poll("player.damage", 1, 2, 0, 100).events().isEmpty());
    }

    @Test
    void chatCaptureLossDoesNotContaminateOtherTypesAndRecentSelectsOnlyRequestedType()
            throws Exception {
        EventJournal journal = new EventJournal(0);
        journal.captureLoss(1, 1, 1, 1);
        journal.append(damage(2, true));
        var recent = journal.recentStart("entity.damage", 0, 0, 10);
        assertEquals(1, recent.cursor());
        assertEquals(1, journal.poll("entity.damage", 0, 2, 0, 10).events().size());
        assertThrows(EventFailure.class, () -> journal.poll("chat.message", 0, 2, 0, 10));
    }

    @Test
    void limitStopsBeforeNextMatchingEventButAdvancesAcrossOtherTypes() throws Exception {
        EventJournal journal = new EventJournal(0);
        journal.append(damage(1, true));
        journal.append(record(2, "player.join", Map.of("player", player()), ALICE));
        journal.append(damage(3, true));
        var first = journal.poll("player.damage", 0, 3, 0, 1);
        assertEquals(1, first.events().size());
        assertEquals(2, first.nextSequence());
        assertTrue(first.hasMore());
        assertEquals(
                3L, journal.poll("player.damage", 2, 3, 0, 1).events().getFirst().get("sequence"));
    }

    @Test
    void snapshotDeepCopyDoesNotRetainMutableInputs() {
        Map<String, Object> source = new HashMap<>();
        List<Object> position = new ArrayList<>(List.of(1, 2, 3));
        source.put("position", position);
        EventRecord fact = record(1, "player.death", source, ALICE);
        position.set(0, 999);
        source.put("later", true);
        Map<?, ?> data = (Map<?, ?>) fact.toProtocol().get("data");
        assertEquals(List.of(1, 2, 3), data.get("position"));
        assertFalse(data.containsKey("later"));
    }

    @Test
    void regionAndBlockKeyFiltersIntersectAndPlayersNoneCanObserveNonPlayerActor()
            throws Exception {
        Session session = new Session(10, 10, () -> {});
        session.markReady();
        SubscriptionRegistry registry = new SubscriptionRegistry();
        UUID all = UUID.randomUUID(), none = UUID.randomUUID(), filtered = UUID.randomUUID();
        registry.add(session, all, "entity.damage", WORLD.uuid(), null, true, 0, null, null);
        registry.activate(session, all);
        registry.add(session, none, "entity.damage", WORLD.uuid(), null, false, 0, null, null);
        registry.activate(session, none);
        registry.publish(damage(1, false));
        assertEquals(1, session.eventOutputFrames());
        var head = session.reactorOutputHead();
        session.reactorRemoveOutputHead(head);
        registry.add(
                session,
                filtered,
                "block.break",
                WORLD.uuid(),
                Set.of(ALICE),
                true,
                0,
                new SubscriptionRegistry.RegionBox(
                        WORLD.uuid(), List.of(0, 0, 0), List.of(1, 2, 3)),
                Set.of("minecraft:stone"));
        registry.activate(session, filtered);
        registry.publish(record(2, "block.break", Map.of("player", player()), ALICE));
        assertEquals(1, session.eventOutputFrames());
        session.reactorRemoveOutputHead(session.reactorOutputHead());
        registry.publish(
                new EventRecord(
                        UUID.randomUUID(),
                        EPOCH,
                        3,
                        1,
                        WORLD,
                        "block.break",
                        Map.of("player", player()),
                        ALICE,
                        List.of(1.01, 2d, 3d),
                        "minecraft:stone",
                        3));
        assertEquals(0, session.eventOutputFrames());
        registry.publish(
                new EventRecord(
                        UUID.randomUUID(),
                        EPOCH,
                        4,
                        1,
                        WORLD,
                        "block.break",
                        Map.of("player", player()),
                        ALICE,
                        List.of(1d, 2d, 3d),
                        "minecraft:dirt",
                        4));
        assertEquals(0, session.eventOutputFrames());
    }

    @Test
    void captureLossBreaksOnlySubscriptionsForAffectedTypes() throws Exception {
        Session session = new Session(10, 10, () -> {});
        session.markReady();
        SubscriptionRegistry registry = new SubscriptionRegistry();
        UUID chat = UUID.randomUUID(), damage = UUID.randomUUID();
        registry.add(session, chat, WORLD.uuid(), null, 0);
        registry.activate(session, chat);
        registry.add(session, damage, "entity.damage", WORLD.uuid(), null, false, 0, null, null);
        registry.activate(session, damage);
        registry.captureLoss(WORLD.uuid(), Set.of("chat.message"), 2, 1);
        String control =
                new String(
                        session.reactorOutputHead().array(),
                        java.nio.charset.StandardCharsets.UTF_8);
        assertTrue(control.contains(chat.toString()));
        assertFalse(control.contains(damage.toString()));
        session.reactorRemoveOutputHead(session.reactorOutputHead());
        registry.publish(damage(2, false));
        assertEquals(1, session.eventOutputFrames());
    }

    @Test
    void lavaEdgesIgnoreDamageAndBaselineDoesNotInventAnEntry() throws Exception {
        Fixture f = new Fixture();
        LavaContactMonitor lava = new LavaContactMonitor(f.events);
        lava.tick(List.of(sample(true, false)), Set.of(WORLD.uuid()));
        assertEquals(0, f.poll("player.enter_lava").size());
        lava.tick(List.of(sample(false, false)), Set.of(WORLD.uuid()));
        lava.tick(List.of(sample(true, false)), Set.of(WORLD.uuid()));
        lava.tick(List.of(sample(true, false)), Set.of(WORLD.uuid()));
        assertEquals(1, f.poll("player.enter_lava").size());
        lava.moved(ALICE);
        lava.tick(List.of(sample(true, false)), Set.of(WORLD.uuid()));
        assertEquals(2, f.poll("player.enter_lava").size());
        lava.died(ALICE);
        lava.tick(List.of(sample(true, false)), Set.of(WORLD.uuid()));
        assertEquals(2, f.poll("player.enter_lava").size());
        lava.respawn(ALICE);
        lava.tick(List.of(sample(true, false)), Set.of(WORLD.uuid()));
        assertEquals(3, f.poll("player.enter_lava").size());
        lava.tick(List.of(), Set.of());
        assertEquals(0, lava.retainedPlayers());
        lava.close();
        f.events.close();
    }

    @Test
    void lavaSubscribeSamplesBeforeCaptureFenceWithoutResettingExistingContacts() throws Exception {
        Fixture f = new Fixture();
        LavaContactMonitor lava = new LavaContactMonitor(f.events);
        lava.tick(List.of(sample(false, false)), Set.of(WORLD.uuid()));
        f.events.beforeLavaSubscribe(
                () -> lava.tick(List.of(sample(true, false)), Set.of(WORLD.uuid())));
        Request subscribe =
                f.request(
                        "events.subscribe",
                        map(
                                "subscriptionId",
                                UUID.randomUUID().toString(),
                                "eventType",
                                "player.enter_lava",
                                "world",
                                WORLD.name(),
                                "executor",
                                null,
                                "players",
                                "@a"));
        f.events.execute(f.session, subscribe, WORLD);
        f.events.afterResponse(f.session, subscribe, true);
        assertNull(f.session.reactorOutputHead());
        assertEquals(1, f.poll("player.enter_lava").size());
        lava.tick(List.of(sample(false, false)), Set.of(WORLD.uuid()));
        lava.tick(List.of(sample(true, false)), Set.of(WORLD.uuid()));
        assertEquals(1, f.session.eventOutputFrames());
    }

    @Test
    void invalidObservedDamageIsTypedCaptureLossWithoutCorruptingOtherHistories() throws Exception {
        Fixture f = new Fixture();
        Map<String, Object> data =
                map(
                        "victim",
                        player(),
                        "directSource",
                        null,
                        "causingEntity",
                        null,
                        "cause",
                        "CUSTOM",
                        "rawDamage",
                        -1,
                        "finalDamage",
                        1,
                        "cancelled",
                        false);
        f.events.captureGame("entity.damage", WORLD, data, ALICE, List.of(0d, 0d, 0d), null);
        assertThrows(EventFailure.class, () -> f.poll("entity.damage"));
        assertThrows(EventFailure.class, () -> f.poll("player.damage"));
        assertTrue(f.poll("chat.message").isEmpty());
    }

    private static LavaContactMonitor.Sample sample(boolean inLava, boolean dead) {
        return new LavaContactMonitor.Sample(
                ALICE, WORLD, inLava, dead, List.of(1d, 2d, 3d), player());
    }

    private static class Fixture {
        final List<Session> sessions = new ArrayList<>();
        final Session session = new Session(100, 100, () -> {});
        final EventsService events =
                new EventsService(name -> WORLD, () -> sessions, name -> ALICE, () -> {});

        Fixture() throws Exception {
            sessions.add(session);
            events.prepareHello(session, WORLD);
            session.markReady();
            events.commitHello(session);
        }

        Request request(String method, Map<String, Object> params) {
            byte[] frame =
                    JsonRpcCodec.encodeFrame(
                            Map.of("jsonrpc", "2.0", "id", 1, "method", method, "params", params));
            return JsonRpcCodec.decodeRequest(Arrays.copyOf(frame, frame.length - 1));
        }

        List<?> poll(String type) throws Exception {
            return (List<?>)
                    events.execute(
                                    session,
                                    request(
                                            "events.pollEvents",
                                            map(
                                                    "world",
                                                    WORLD.name(),
                                                    "eventType",
                                                    type,
                                                    "cursor",
                                                    null,
                                                    "limit",
                                                    100)),
                                    WORLD)
                            .get("events");
        }
    }
}
