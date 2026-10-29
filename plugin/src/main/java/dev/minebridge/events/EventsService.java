package dev.minebridge.events;

import dev.minebridge.protocol.CodecException;
import dev.minebridge.protocol.JsonNumber;
import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;
import dev.minebridge.session.WorldContext;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.function.Supplier;

/**
 * Bounded CHAT_MESSAGE ingress, world history and live delivery. All state except ingress is
 * game-thread owned.
 */
public final class EventsService implements AutoCloseable {
    public static final String CHAT_MESSAGE = "chat.message";
    private static final List<String> TYPES =
            List.of(
                    CHAT_MESSAGE,
                    "block.interact",
                    "block.break",
                    "block.place",
                    "entity.attack",
                    "entity.damage",
                    "player.damage",
                    "player.enter_lava",
                    "player.join",
                    "player.quit",
                    "player.death",
                    "player.respawn",
                    "projectile.shot",
                    "projectile.hit");

    public static List<String> supportedTypes() {
        return TYPES;
    }

    public static final int MAX_WORLDS = 8;
    public static final int MAX_INGRESS = 1024;
    public static final int MAX_PER_TICK = 128;
    private static final long TICK_BUDGET_NANOS = 2_000_000L;

    @FunctionalInterface
    public interface WorldLookup {
        WorldContext find(String nameOrKey);
    }

    @FunctionalInterface
    public interface PlayerDirectory {
        UUID findOnline(String nameOrUuid);
    }

    public record PlayerSnapshot(UUID uuid, String name, int entityId, WorldContext world) {
        public PlayerSnapshot {
            Objects.requireNonNull(uuid);
            Objects.requireNonNull(name);
            Objects.requireNonNull(world);
        }
    }

    private record Baseline(WorldContext world, long sequence, long captureOrder) {}

    private static final class Owner {
        final Map<UUID, Baseline> worlds = new HashMap<>();
        boolean committed;
    }

    private record ChatInput(
            long order, PlayerSnapshot player, String message, boolean truncated) {}

    private static final class CaptureLoss {
        final UUID world;
        final long firstOrder;
        long lastOrder;
        long count = 1;

        CaptureLoss(UUID world, long order) {
            this.world = world;
            firstOrder = order;
            lastOrder = order;
        }
    }

    private final WorldLookup worlds;
    private final Supplier<List<Session>> connections;
    private final PlayerDirectory players;
    private final Runnable requireGameThread;
    private final UUID epoch = UUID.randomUUID();
    private final SubscriptionRegistry subscriptions = new SubscriptionRegistry();
    private final Map<Session, Owner> owners = new HashMap<>();
    private final Map<UUID, EventJournal> journals = new HashMap<>();
    private Map<UUID, PlayerSnapshot> currentPlayers = Map.of();
    private final Object ingressLock = new Object();
    private final ArrayDeque<ChatInput> ingress = new ArrayDeque<>();
    private final Map<UUID, CaptureLoss> captureLosses = new HashMap<>();
    // Published together under ingressLock, also used as the atomic hello/other-world capture
    // boundary.
    private Set<UUID> captureWorlds = Set.of();
    private long captureOrder;
    private long sequence;
    private long tick;
    private boolean closed;
    private Runnable beforeLavaSubscribe = () -> {};

    public EventsService(
            WorldLookup worlds,
            Supplier<List<Session>> connections,
            PlayerDirectory players,
            Runnable requireGameThread) {
        this.worlds = Objects.requireNonNull(worlds);
        this.connections = Objects.requireNonNull(connections);
        this.players = Objects.requireNonNull(players);
        this.requireGameThread = Objects.requireNonNull(requireGameThread);
    }

    /**
     * The capture interest and baseline exist before hello ACK can become visible to the reactor.
     */
    public Map<String, Object> prepareHello(Session session, WorldContext context)
            throws EventFailure {
        requireGameThread.run();
        if (closed || owners.containsKey(session)) throw new EventFailure("INVALID_STATE");
        owners.put(session, new Owner());
        Baseline baseline;
        try {
            baseline = ensureWorld(session, context);
        } catch (EventFailure failure) {
            owners.remove(session);
            throw failure;
        }
        return Map.of(
                "epoch",
                epoch.toString(),
                "world",
                context.uuid().toString(),
                "startSequence",
                baseline.sequence(),
                "retention",
                Map.of(
                        "maxRecords",
                        EventJournal.MAX_RECORDS,
                        "maxBytes",
                        EventJournal.MAX_BYTES,
                        "maxAgeTicks",
                        EventJournal.MAX_AGE_TICKS),
                "maxSubscriptions",
                SubscriptionRegistry.MAX_SUBSCRIPTIONS,
                "maxLiveEvents",
                512);
    }

    public void commitHello(Session session) {
        requireGameThread.run();
        Owner owner = owners.get(session);
        if (owner != null) owner.committed = true;
    }

    public void abortHello(Session session) {
        requireGameThread.run();
        owners.remove(session);
        subscriptions.remove(session);
        pruneWorlds();
    }

    /**
     * Register/resolve calls execute only on Paper's thread; async listeners see immutable
     * snapshots only.
     */
    public void replacePlayers(List<PlayerSnapshot> snapshots) {
        requireGameThread.run();
        HashMap<UUID, PlayerSnapshot> next = new HashMap<>();
        for (PlayerSnapshot player : snapshots) next.put(player.uuid(), player);
        currentPlayers = Map.copyOf(next);
    }

    public Set<UUID> interestedWorlds() {
        requireGameThread.run();
        synchronized (ingressLock) {
            return Set.copyOf(captureWorlds);
        }
    }

    public long tickCounter() {
        requireGameThread.run();
        return tick;
    }

    public void beforeLavaSubscribe(Runnable observer) {
        requireGameThread.run();
        beforeLavaSubscribe = Objects.requireNonNull(observer);
    }

    /** Native adapters provide immutable primitive snapshots, never retained Bukkit events. */
    public void captureGame(
            String type,
            WorldContext world,
            Map<String, Object> data,
            UUID playerActor,
            List<Double> filterPosition,
            String blockKey) {
        requireGameThread.run();
        if (closed || !TYPES.contains(type) || type.equals("player.damage")) return;
        EventJournal journal = journals.get(world.uuid());
        if (journal == null) return;
        long order;
        synchronized (ingressLock) {
            order = ++captureOrder;
        }
        EventRecord record =
                new EventRecord(
                        UUID.randomUUID(),
                        epoch,
                        nextSequence(),
                        tick,
                        world,
                        type,
                        data,
                        playerActor,
                        filterPosition,
                        blockKey,
                        order);
        try {
            if (type.equals("entity.damage")) {
                for (String key : List.of("rawDamage", "finalDamage")) {
                    Object value = data.get(key);
                    if (!(value instanceof Number number)
                            || !Double.isFinite(number.doubleValue())
                            || number.doubleValue() < 0)
                        throw new IllegalArgumentException("Invalid observed damage");
                }
            }
            journal.append(record);
        } catch (CodecException | IllegalArgumentException invalidForeignSnapshot) {
            journal.captureLoss(record.sequence(), tick, order, order, record.types());
            subscriptions.captureLoss(world.uuid(), record.types(), 1, order);
            return;
        }
        subscriptions.publish(record);
    }

    /**
     * May run on the chat thread. No Bukkit objects, socket waits, callbacks or journal mutation.
     */
    public void captureChat(PlayerSnapshot player, String message, boolean cancelled) {
        if (cancelled || player == null || message == null) return;
        Text text = text(message);
        synchronized (ingressLock) {
            if (!captureWorlds.contains(player.world().uuid())) return;
            long order = ++captureOrder;
            if (ingress.size() >= MAX_INGRESS) {
                CaptureLoss loss = captureLosses.get(player.world().uuid());
                if (loss == null)
                    captureLosses.put(
                            player.world().uuid(), new CaptureLoss(player.world().uuid(), order));
                else {
                    loss.lastOrder = order;
                    loss.count = Math.min(JsonRpcCodec.MAX_REQUEST_ID, loss.count + 1);
                }
            } else ingress.addLast(new ChatInput(order, player, text.value(), text.truncated()));
        }
    }

    /** A foreign chat component could not be copied. Preserve a visible bounded loss boundary. */
    public void captureFailed(PlayerSnapshot player) {
        if (player == null) return;
        synchronized (ingressLock) {
            if (!captureWorlds.contains(player.world().uuid())) return;
            long order = ++captureOrder;
            CaptureLoss loss = captureLosses.get(player.world().uuid());
            if (loss == null)
                captureLosses.put(
                        player.world().uuid(), new CaptureLoss(player.world().uuid(), order));
            else {
                loss.lastOrder = order;
                loss.count = Math.min(JsonRpcCodec.MAX_REQUEST_ID, loss.count + 1);
            }
        }
    }

    private record Text(String value, boolean truncated) {}

    private static Text text(String original) {
        StringBuilder result = new StringBuilder(Math.min(original.length(), 4096));
        int offset = 0, count = 0;
        while (offset < original.length() && count < 4096) {
            char first = original.charAt(offset++);
            if (Character.isHighSurrogate(first)
                    && offset < original.length()
                    && Character.isLowSurrogate(original.charAt(offset)))
                result.append(first).append(original.charAt(offset++));
            else if (Character.isSurrogate(first)) result.append('\uFFFD');
            else result.append(first);
            count++;
        }
        return new Text(result.toString(), offset < original.length());
    }

    public Map<String, Object> execute(Session session, Request request, WorldContext context)
            throws EventFailure {
        requireGameThread.run();
        if (closed) throw new EventFailure("INVALID_STATE");
        if (request.method().equals("events.unsubscribe")) {
            UUID id = uuid(request.params().get("subscriptionId"));
            if (!subscriptions.remove(session, id))
                throw new EventFailure("SUBSCRIPTION_NOT_FOUND");
            return Map.of("subscriptionId", id.toString(), "unsubscribed", true);
        }
        String eventType = (String) request.params().get("eventType");
        if (eventType != null) validateType(eventType);
        else if (!request.method().equals("events.clearPending"))
            throw new EventFailure("INVALID_EVENT_TYPE");
        WorldContext selected = resolveWorld(context, (String) request.params().get("world"));
        Baseline baseline = ensureWorld(session, selected);
        EventJournal journal = journals.get(selected.uuid());
        journal.expire(tick);
        return switch (request.method()) {
            case "events.subscribe" -> {
                UUID id = uuid(request.params().get("subscriptionId"));
                Set<UUID> filter =
                        filter(request.params().get("players"), request.params().get("executor"));
                SubscriptionRegistry.RegionBox region =
                        region(request.params().get("region"), selected, eventType);
                Set<String> blocks = blocks(request.params().get("blocks"), eventType);
                if (eventType.equals("player.enter_lava")) beforeLavaSubscribe.run();
                synchronized (ingressLock) {
                    subscriptions.add(
                            session,
                            id,
                            eventType,
                            selected.uuid(),
                            filter,
                            request.params().get("players") != null,
                            captureOrder,
                            region,
                            blocks);
                }
                yield Map.of(
                        "subscriptionId",
                        id.toString(),
                        "eventType",
                        eventType,
                        "world",
                        selected.uuid().toString());
            }
            case "events.pollEvents" -> {
                long cursor = cursor(request.params().get("cursor"), baseline, journal);
                int limit = limit(request.params().get("limit"));
                EventJournal.Page page =
                        journal.poll(
                                eventType, cursor, journal.tail(), baseline.captureOrder(), limit);
                yield page(page, selected.uuid());
            }
            case "events.getRecent" -> {
                int limit = limit(request.params().get("limit"));
                Object rawCursor = request.params().get("cursor"),
                        rawUpper = request.params().get("upperBound");
                long cursor, upper;
                boolean windowLimited;
                if (rawCursor == null && rawUpper == null) {
                    EventJournal.RecentStart start =
                            journal.recentStart(
                                    eventType, baseline.sequence(), baseline.captureOrder(), limit);
                    cursor = start.cursor();
                    upper = start.upperBound();
                    windowLimited = start.windowLimited();
                } else if (rawCursor != null && rawUpper != null) {
                    cursor = cursor(rawCursor, baseline, journal);
                    upper = number(rawUpper);
                    if (upper < cursor || upper > journal.tail())
                        throw new EventFailure("INVALID_PARAMS");
                    windowLimited = false;
                } else throw new EventFailure("INVALID_PARAMS");
                LinkedHashMap<String, Object> result =
                        new LinkedHashMap<>(
                                page(
                                        journal.poll(
                                                eventType,
                                                cursor,
                                                upper,
                                                baseline.captureOrder(),
                                                limit),
                                        selected.uuid()));
                result.put("sessionStart", baseline.sequence());
                result.put("windowLimited", windowLimited);
                yield result;
            }
            case "events.clearPending" -> Map.of("cursor", cursor(selected.uuid(), journal.tail()));
            default -> throw new EventFailure("METHOD_NOT_FOUND");
        };
    }

    /**
     * Called immediately after result publication. It does no IO and never runs under the session
     * lock.
     */
    public void afterResponse(Session session, Request request, boolean accepted) {
        requireGameThread.run();
        if (!request.method().equals("events.subscribe")) return;
        UUID id;
        try {
            id = uuid(request.params().get("subscriptionId"));
        } catch (EventFailure invalid) {
            return;
        }
        if (accepted) subscriptions.activate(session, id);
        else subscriptions.remove(session, id);
    }

    public void tick() {
        requireGameThread.run();
        if (closed) return;
        tick++;
        // The supplier is a bounded snapshot; no session or player reference is retained after
        // disconnect.
        Set<Session> connected = new HashSet<>(connections.get());
        for (Iterator<Map.Entry<Session, Owner>> iterator = owners.entrySet().iterator();
                iterator.hasNext(); ) {
            Map.Entry<Session, Owner> owner = iterator.next();
            if (!owner.getKey().isOpen()
                    || owner.getValue().committed
                            && (!owner.getKey().isReady() || !connected.contains(owner.getKey()))) {
                subscriptions.remove(owner.getKey());
                iterator.remove();
            }
        }
        pruneWorlds();
        for (EventJournal journal : journals.values()) journal.expire(tick);
        long started = System.nanoTime();
        for (int count = 0;
                count < MAX_PER_TICK && System.nanoTime() - started < TICK_BUDGET_NANOS;
                count++) {
            Object input = nextInput();
            if (input == null) break;
            if (input instanceof CaptureLoss loss) {
                EventJournal journal = journals.get(loss.world);
                if (journal == null) continue;
                journal.captureLoss(nextSequence(), tick, loss.firstOrder, loss.lastOrder);
                subscriptions.captureLoss(loss.world, loss.count, loss.lastOrder);
            } else {
                ChatInput chat = (ChatInput) input;
                PlayerSnapshot player =
                        currentPlayers.getOrDefault(chat.player().uuid(), chat.player());
                EventJournal journal = journals.get(player.world().uuid());
                if (journal == null) continue;
                EventRecord record =
                        new EventRecord(
                                UUID.randomUUID(),
                                epoch,
                                nextSequence(),
                                tick,
                                player.world(),
                                player,
                                chat.message(),
                                chat.truncated(),
                                chat.order());
                try {
                    journal.append(record);
                } catch (CodecException | IllegalArgumentException invalidForeignMetadata) {
                    journal.captureLoss(record.sequence(), tick, chat.order(), chat.order());
                    subscriptions.captureLoss(player.world().uuid(), 1, chat.order());
                    continue;
                }
                subscriptions.publish(record);
            }
        }
    }

    private Object nextInput() {
        synchronized (ingressLock) {
            CaptureLoss first = null;
            for (CaptureLoss loss : captureLosses.values())
                if (first == null || loss.firstOrder < first.firstOrder) first = loss;
            if (first != null
                    && (ingress.isEmpty() || first.firstOrder < ingress.peekFirst().order())) {
                captureLosses.remove(first.world);
                return first;
            }
            return ingress.pollFirst();
        }
    }

    private long nextSequence() {
        if (sequence == JsonRpcCodec.MAX_REQUEST_ID)
            throw new IllegalStateException("Event sequence exhausted");
        return ++sequence;
    }

    private Baseline ensureWorld(Session session, WorldContext world) throws EventFailure {
        Owner owner = owners.get(session);
        if (owner == null) throw new EventFailure("INVALID_STATE");
        Baseline known = owner.worlds.get(world.uuid());
        if (known != null) return known;
        for (Baseline pinned : owner.worlds.values())
            if (pinned.world().name().equals(world.name())
                    || pinned.world().key().equals(world.key()))
                throw new EventFailure("WORLD_NOT_FOUND");
        if (!journals.containsKey(world.uuid())) {
            if (journals.size() >= MAX_WORLDS) throw new EventFailure("LIMIT_EXCEEDED");
            journals.put(world.uuid(), new EventJournal(sequence));
        }
        synchronized (ingressLock) {
            Baseline baseline =
                    new Baseline(world, journals.get(world.uuid()).tail(), captureOrder);
            owner.worlds.put(world.uuid(), baseline);
            captureWorlds = Set.copyOf(journals.keySet());
            return baseline;
        }
    }

    private void pruneWorlds() {
        HashSet<UUID> used = new HashSet<>();
        for (Owner owner : owners.values()) used.addAll(owner.worlds.keySet());
        journals.keySet().retainAll(used);
        synchronized (ingressLock) {
            captureWorlds = Set.copyOf(used);
            captureLosses.keySet().retainAll(used);
            ingress.removeIf(input -> !used.contains(input.player().world().uuid()));
        }
    }

    private WorldContext resolveWorld(WorldContext context, String selected) throws EventFailure {
        if (selected == null || selected.isBlank()) throw new EventFailure("INVALID_PARAMS");
        WorldContext found = worlds.find(selected);
        if (found == null) throw new EventFailure("WORLD_NOT_FOUND");
        if ((selected.equals(context.name()) || selected.equals(context.key()))
                && !context.equals(found)) throw new EventFailure("WORLD_NOT_FOUND");
        return found;
    }

    private Set<UUID> filter(Object value, Object executor) throws EventFailure {
        if (value == null || value.equals("@a")) return null;
        if (value instanceof String text) {
            if (text.equals("@s")) {
                if (executor == null) throw new EventFailure("MISSING_CONTEXT");
                return Set.of(uuid(executor));
            }
            if (text.startsWith("@")) throw new EventFailure("INVALID_SELECTOR");
            UUID explicit = maybeUuid(text);
            if (explicit != null) return Set.of(explicit);
            UUID player = players.findOnline(text);
            if (player == null) throw new EventFailure("PLAYER_NOT_FOUND");
            return Set.of(player);
        }
        if (value instanceof List<?> list && list.size() <= 1024) {
            HashSet<UUID> result = new HashSet<>();
            for (Object player : list) result.add(uuid(player));
            return Set.copyOf(result);
        }
        throw new EventFailure("INVALID_TARGET");
    }

    private SubscriptionRegistry.RegionBox region(Object value, WorldContext selected, String type)
            throws EventFailure {
        if (value == null) return null;
        if (List.of(CHAT_MESSAGE, "player.join", "player.quit").contains(type)
                || !(value instanceof Map<?, ?> map)
                || !map.keySet().equals(Set.of("world", "min", "max"))
                || !selected.uuid().equals(maybeUuid(map.get("world"))))
            throw new EventFailure("INVALID_PARAMS");
        List<Integer> min = blockPosition(map.get("min")), max = blockPosition(map.get("max"));
        for (int i = 0; i < 3; i++)
            if (min.get(i) > max.get(i)) throw new EventFailure("INVALID_PARAMS");
        return new SubscriptionRegistry.RegionBox(selected.uuid(), min, max);
    }

    private List<Integer> blockPosition(Object value) throws EventFailure {
        if (!(value instanceof List<?> values) || values.size() != 3)
            throw new EventFailure("INVALID_PARAMS");
        ArrayList<Integer> result = new ArrayList<>();
        for (Object item : values) {
            if (!(item instanceof JsonNumber n) || !n.text().matches("-?(0|[1-9][0-9]{0,9})"))
                throw new EventFailure("INVALID_PARAMS");
            try {
                long parsed = Long.parseLong(n.text());
                if (parsed < Integer.MIN_VALUE || parsed > Integer.MAX_VALUE)
                    throw new EventFailure("INVALID_PARAMS");
                result.add((int) parsed);
            } catch (NumberFormatException invalid) {
                throw new EventFailure("INVALID_PARAMS");
            }
        }
        return List.copyOf(result);
    }

    private Set<String> blocks(Object value, String type) throws EventFailure {
        if (value == null) return null;
        if (!type.startsWith("block.") || !(value instanceof List<?> list) || list.size() > 256)
            throw new EventFailure("INVALID_PARAMS");
        HashSet<String> keys = new HashSet<>();
        for (Object key : list)
            if (key instanceof String text && text.matches("[a-z0-9_.-]+:[a-z0-9/._-]+"))
                keys.add(text);
            else throw new EventFailure("INVALID_PARAMS");
        if (keys.size() != list.size()) throw new EventFailure("INVALID_PARAMS");
        return Set.copyOf(keys);
    }

    private long cursor(Object value, Baseline baseline, EventJournal journal) throws EventFailure {
        if (value == null) return baseline.sequence();
        if (!(value instanceof Map<?, ?> object)
                || !object.keySet().equals(Set.of("epoch", "world", "sequence"))
                || !epoch.equals(maybeUuid(object.get("epoch")))
                || !baseline.world().uuid().equals(maybeUuid(object.get("world"))))
            throw new EventFailure("INVALID_PARAMS");
        long sequence = number(object.get("sequence"));
        if (sequence < baseline.sequence() || sequence > journal.tail())
            throw new EventFailure("INVALID_PARAMS");
        return sequence;
    }

    private Map<String, Object> page(EventJournal.Page page, UUID world) {
        return Map.of(
                "events",
                page.events(),
                "nextCursor",
                cursor(world, page.nextSequence()),
                "upperBound",
                page.upperBound(),
                "availableFrom",
                page.availableFrom(),
                "hasMore",
                page.hasMore());
    }

    private Map<String, Object> cursor(UUID world, long sequence) {
        return Map.of("epoch", epoch.toString(), "world", world.toString(), "sequence", sequence);
    }

    private static long number(Object value) throws EventFailure {
        if (!(value instanceof JsonNumber number)
                || !number.text().matches("-0|0|[1-9][0-9]{0,15}"))
            throw new EventFailure("INVALID_PARAMS");
        try {
            long parsed = Long.parseLong(number.text());
            if (parsed > JsonRpcCodec.MAX_REQUEST_ID) throw new EventFailure("INVALID_PARAMS");
            return parsed;
        } catch (NumberFormatException invalid) {
            throw new EventFailure("INVALID_PARAMS");
        }
    }

    private static int limit(Object value) throws EventFailure {
        long limit = number(value);
        if (limit < 1 || limit > 1000) throw new EventFailure("INVALID_PARAMS");
        return (int) limit;
    }

    private static UUID uuid(Object value) throws EventFailure {
        UUID uuid = maybeUuid(value);
        if (uuid == null) throw new EventFailure("INVALID_PARAMS");
        return uuid;
    }

    private static UUID maybeUuid(Object value) {
        if (!(value instanceof String text)
                || !text.matches(
                        "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"))
            return null;
        return UUID.fromString(text);
    }

    private static void validateType(String value) throws EventFailure {
        if (TYPES.contains(value)) return;
        throw new EventFailure("INVALID_EVENT_TYPE");
    }

    @Override
    public void close() {
        requireGameThread.run();
        closed = true;
        subscriptions.close();
        owners.clear();
        journals.clear();
        currentPlayers = Map.of();
        synchronized (ingressLock) {
            captureWorlds = Set.of();
            ingress.clear();
            captureLosses.clear();
        }
    }
}
