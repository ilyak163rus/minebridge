package dev.minebridge.events;

import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.session.Session;

import java.util.*;

/** Main-thread subscriptions: all intersections are applied before allocating a live frame. */
public final class SubscriptionRegistry {
    public static final int MAX_SUBSCRIPTIONS = 32;

    public record RegionBox(UUID world, List<Integer> min, List<Integer> max) {
        public RegionBox {
            min = List.copyOf(min);
            max = List.copyOf(max);
        }

        boolean contains(List<Double> position) {
            if (position == null) return false;
            for (int i = 0; i < 3; i++)
                if (position.get(i) < min.get(i) || position.get(i) > max.get(i)) return false;
            return true;
        }
    }

    static final class Subscription {
        final UUID id, world;
        final String type;
        final Set<UUID> players;
        final boolean requirePlayer;
        final long startCapture;
        final RegionBox region;
        final Set<String> blocks;
        boolean active, broken;
        long deliverySequence;

        Subscription(
                UUID id,
                String type,
                UUID world,
                Set<UUID> players,
                boolean requirePlayer,
                long startCapture,
                RegionBox region,
                Set<String> blocks) {
            this.id = id;
            this.type = type;
            this.world = world;
            this.players = players;
            this.requirePlayer = requirePlayer;
            this.startCapture = startCapture;
            this.region = region;
            this.blocks = blocks;
        }
    }

    private final Map<Session, Map<UUID, Subscription>> sessions = new HashMap<>();

    public void add(Session session, UUID id, UUID world, Set<UUID> players, long startCapture)
            throws EventFailure {
        add(session, id, "chat.message", world, players, true, startCapture, null, null);
    }

    public void add(
            Session session,
            UUID id,
            String type,
            UUID world,
            Set<UUID> players,
            boolean requirePlayer,
            long startCapture,
            RegionBox region,
            Set<String> blocks)
            throws EventFailure {
        Map<UUID, Subscription> owned =
                sessions.computeIfAbsent(session, ignored -> new HashMap<>());
        if (owned.containsKey(id)) throw new EventFailure("INVALID_STATE");
        if (owned.size() >= MAX_SUBSCRIPTIONS) throw new EventFailure("LIMIT_EXCEEDED");
        owned.put(
                id,
                new Subscription(
                        id, type, world, players, requirePlayer, startCapture, region, blocks));
    }

    public void activate(Session session, UUID id) {
        Subscription sub = get(session, id);
        if (sub != null) sub.active = true;
    }

    public boolean remove(Session session, UUID id) {
        Map<UUID, Subscription> owned = sessions.get(session);
        if (owned == null || owned.remove(id) == null) return false;
        session.purgeEvents(id);
        if (owned.isEmpty()) sessions.remove(session);
        return true;
    }

    public void remove(Session session) {
        Map<UUID, Subscription> removed = sessions.remove(session);
        if (removed != null) removed.keySet().forEach(session::purgeEvents);
    }

    public void publish(EventRecord event) {
        for (var owner : sessions.entrySet())
            for (Subscription sub : owner.getValue().values()) {
                if (!sub.active
                        || sub.broken
                        || !sub.world.equals(event.world().uuid())
                        || !event.matches(sub.type)
                        || event.captureOrder() <= sub.startCapture
                        || sub.requirePlayer && event.actor() == null
                        || sub.players != null && !sub.players.contains(event.actor())
                        || sub.region != null && !sub.region.contains(event.filterPosition())
                        || sub.blocks != null && !sub.blocks.contains(event.blockKey())) continue;
                long delivery = sub.deliverySequence + 1;
                byte[] frame =
                        JsonRpcCodec.encodeFrame(
                                Map.of(
                                        "jsonrpc",
                                        "2.0",
                                        "method",
                                        "events.event",
                                        "params",
                                        Map.of(
                                                "subscriptionId",
                                                sub.id.toString(),
                                                "deliverySequence",
                                                delivery,
                                                "event",
                                                event.toProtocol(sub.type))));
                if (owner.getKey().offerEvent(frame, sub.id)) {
                    sub.deliverySequence = delivery;
                    owner.getKey().logEvent(sub.id, "queued", delivery);
                } else breakSubscription(owner.getKey(), sub, "server", 1);
            }
    }

    public void captureLoss(UUID world, long count, long lastCapture) {
        captureLoss(world, Set.of("chat.message"), count, lastCapture);
    }

    public void captureLoss(UUID world, Set<String> types, long count, long lastCapture) {
        for (var owner : sessions.entrySet())
            for (Subscription sub : owner.getValue().values())
                if (sub.active
                        && !sub.broken
                        && sub.world.equals(world)
                        && types.contains(sub.type)
                        && lastCapture > sub.startCapture)
                    breakSubscription(owner.getKey(), sub, "capture", count);
    }

    private void breakSubscription(Session owner, Subscription sub, String source, long count) {
        sub.broken = true;
        owner.purgeEvents(sub.id);
        owner.offerEventOverflow(sub.id, source, count);
        owner.logEvent(sub.id, "overflow", sub.deliverySequence);
    }

    private Subscription get(Session session, UUID id) {
        Map<UUID, Subscription> owned = sessions.get(session);
        return owned == null ? null : owned.get(id);
    }

    public int size(Session session) {
        Map<UUID, Subscription> owned = sessions.get(session);
        return owned == null ? 0 : owned.size();
    }

    public void close() {
        for (Session session : Set.copyOf(sessions.keySet())) remove(session);
    }
}
