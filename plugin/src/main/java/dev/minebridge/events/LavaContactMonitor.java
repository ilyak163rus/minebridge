package dev.minebridge.events;

import dev.minebridge.session.WorldContext;

import java.util.*;

/** Per-world-contact edge detection, independent of damage and individual subscriptions. */
public final class LavaContactMonitor implements AutoCloseable {
    public record Sample(
            UUID player,
            WorldContext world,
            boolean inLava,
            boolean dead,
            List<Double> position,
            Map<String, Object> playerSnapshot) {}

    private record State(UUID world, boolean inLava) {}

    private final Map<UUID, State> state = new HashMap<>();
    private final Set<UUID> reset = new HashSet<>(), dead = new HashSet<>();
    private final EventsService events;

    public LavaContactMonitor(EventsService events) {
        this.events = events;
    }

    public void join(UUID id) {
        state.remove(id);
        reset.remove(id);
        dead.remove(id);
    }

    public void quit(UUID id) {
        join(id);
    }

    public void died(UUID id) {
        state.remove(id);
        reset.remove(id);
        dead.add(id);
    }

    public void moved(UUID id) {
        reset.add(id);
    }

    public void respawn(UUID id) {
        dead.remove(id);
        reset.add(id);
    }

    public void tick(List<Sample> samples, Set<UUID> interested) {
        Set<UUID> retained = new HashSet<>();
        for (Sample sample : samples) {
            if (!interested.contains(sample.world().uuid())) continue;
            retained.add(sample.player());
            if (sample.dead() || dead.contains(sample.player())) continue;
            State previous = state.get(sample.player());
            boolean newContact =
                    reset.remove(sample.player())
                            || previous != null && !previous.world().equals(sample.world().uuid());
            boolean entered =
                    sample.inLava() && (newContact || previous != null && !previous.inLava());
            state.put(sample.player(), new State(sample.world().uuid(), sample.inLava()));
            if (entered)
                events.captureGame(
                        "player.enter_lava",
                        sample.world(),
                        Map.of("player", sample.playerSnapshot(), "position", sample.position()),
                        sample.player(),
                        sample.position(),
                        null);
        }
        state.keySet().retainAll(retained);
        reset.retainAll(retained);
        dead.retainAll(retained);
    }

    int retainedPlayers() {
        return state.size() + dead.size();
    }

    @Override
    public void close() {
        state.clear();
        reset.clear();
        dead.clear();
    }
}
