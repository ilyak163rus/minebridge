package dev.minebridge.events;

import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.session.WorldContext;

import java.util.*;

/** Canonical immutable fact. Projections preserve identity and sequence. */
public final class EventRecord {
    private final UUID eventId, serverEpoch, actor;
    private final long sequence, serverTick, captureOrder;
    private final WorldContext world;
    private final String eventType, blockKey;
    private final Map<String, Object> data;
    private final List<Double> filterPosition;
    private final EventsService.PlayerSnapshot legacyPlayer;

    public EventRecord(
            UUID eventId,
            UUID epoch,
            long sequence,
            long tick,
            WorldContext world,
            EventsService.PlayerSnapshot player,
            String message,
            boolean truncated,
            long captureOrder) {
        this(
                eventId,
                epoch,
                sequence,
                tick,
                world,
                "chat.message",
                Map.of(
                        "player",
                        Map.of(
                                "uuid",
                                player.uuid().toString(),
                                "name",
                                player.name(),
                                "entityId",
                                player.entityId()),
                        "message",
                        message,
                        "cancelled",
                        false,
                        "truncated",
                        truncated),
                player.uuid(),
                null,
                null,
                captureOrder,
                player);
    }

    public EventRecord(
            UUID eventId,
            UUID epoch,
            long sequence,
            long tick,
            WorldContext world,
            String type,
            Map<String, Object> data,
            UUID actor,
            List<Double> position,
            String blockKey,
            long order) {
        this(
                eventId, epoch, sequence, tick, world, type, data, actor, position, blockKey, order,
                null);
    }

    private EventRecord(
            UUID eventId,
            UUID epoch,
            long sequence,
            long tick,
            WorldContext world,
            String type,
            Map<String, Object> data,
            UUID actor,
            List<Double> position,
            String blockKey,
            long order,
            EventsService.PlayerSnapshot legacyPlayer) {
        this.eventId = eventId;
        serverEpoch = epoch;
        this.sequence = sequence;
        serverTick = tick;
        this.world = world;
        eventType = type;
        this.data = freezeMap(data);
        this.actor = actor;
        filterPosition = position == null ? null : List.copyOf(position);
        this.blockKey = blockKey;
        captureOrder = order;
        this.legacyPlayer = legacyPlayer;
    }

    public UUID eventId() {
        return eventId;
    }

    public UUID serverEpoch() {
        return serverEpoch;
    }

    public long sequence() {
        return sequence;
    }

    public long serverTick() {
        return serverTick;
    }

    public long captureOrder() {
        return captureOrder;
    }

    public WorldContext world() {
        return world;
    }

    public String eventType() {
        return eventType;
    }

    public UUID actor() {
        return actor;
    }

    public List<Double> filterPosition() {
        return filterPosition;
    }

    public String blockKey() {
        return blockKey;
    }

    public EventsService.PlayerSnapshot player() {
        return legacyPlayer;
    }

    public String message() {
        return (String) data.get("message");
    }

    public boolean truncated() {
        return Boolean.TRUE.equals(data.get("truncated"));
    }

    public Set<String> types() {
        if (eventType.equals("entity.damage")
                && data.get("victim") instanceof Map<?, ?> victim
                && "minecraft:player".equals(victim.get("key")))
            return Set.of("entity.damage", "player.damage");
        return Set.of(eventType);
    }

    public boolean matches(String type) {
        return types().contains(type);
    }

    public Map<String, Object> toProtocol() {
        return toProtocol(eventType);
    }

    public Map<String, Object> toProtocol(String type) {
        if (!matches(type)) throw new IllegalArgumentException("Invalid event projection");
        return Map.of(
                "eventId",
                eventId.toString(),
                "serverEpoch",
                serverEpoch.toString(),
                "sequence",
                sequence,
                "serverTick",
                serverTick,
                "eventType",
                type,
                "world",
                Map.of("uuid", world.uuid().toString(), "name", world.name(), "key", world.key()),
                "data",
                data);
    }

    public int encodedBytes() {
        return JsonRpcCodec.encodeFrame(toProtocol()).length;
    }

    @SuppressWarnings("unchecked")
    private static Object freeze(Object value) {
        if (value instanceof Map<?, ?> map) return freezeMap((Map<String, Object>) map);
        if (value instanceof List<?> list) {
            List<Object> copy = new ArrayList<>();
            for (Object item : list) copy.add(freeze(item));
            return Collections.unmodifiableList(copy);
        }
        return value;
    }

    private static Map<String, Object> freezeMap(Map<String, Object> value) {
        Map<String, Object> copy = new LinkedHashMap<>();
        value.forEach((key, item) -> copy.put(key, freeze(item)));
        return Collections.unmodifiableMap(copy);
    }
}
