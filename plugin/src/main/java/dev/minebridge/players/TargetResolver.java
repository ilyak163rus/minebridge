package dev.minebridge.players;

import dev.minebridge.blocks.BlockFailure;
import dev.minebridge.blocks.BlockService;
import dev.minebridge.session.WorldContext;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Shared vanilla selection boundary. Resolves once, then validates every target before mutation. */
public final class TargetResolver {
    public enum Kind { PLAYERS, LIVING }
    private final PlayerService.Backend backend;
    private final BlockService blocks;
    private final Runnable requireGameThread;
    public TargetResolver(PlayerService.Backend backend, BlockService blocks, Runnable requireGameThread) {
        this.backend = backend; this.blocks = blocks; this.requireGameThread = requireGameThread;
    }
    public List<PlayerService.Target> select(WorldContext context, String world, String executor, Object targets, Kind kind)
            throws PlayerFailure, BlockFailure {
        requireGameThread.run(); blocks.world(context, world);
        List<? extends PlayerService.Target> selected;
        if (targets instanceof List<?> uuids) {
            List<PlayerService.Target> explicit = new ArrayList<>();
            for (Object uuid : uuids) explicit.add(target((String) uuid, kind));
            selected = explicit;
        } else {
            String selector = (String) targets;
            if (!selector.startsWith("@")) selected = List.of(target(selector, kind));
            else {
                PlayerService.SelectorContext need = PlayerService.contextNeeded(selector);
                PlayerService.Player sender = null;
                if (need.executor()) {
                    if (executor == null) throw new PlayerFailure("MISSING_CONTEXT");
                    sender = player(executor);
                    if (need.origin() && !sender.position().worldUuid().equals(context.uuid())) throw new PlayerFailure("CONTEXT_WORLD_MISMATCH");
                }
                try { selected = backend.select(selector, sender); }
                catch (IllegalArgumentException invalid) { throw new PlayerFailure("INVALID_SELECTOR"); }
            }
        }
        Map<UUID, PlayerService.Target> unique = new LinkedHashMap<>();
        for (PlayerService.Target target : selected) {
            if (kind == Kind.PLAYERS && !(target instanceof PlayerService.Player) || kind == Kind.LIVING && !target.living()) {
                throw new PlayerFailure("INVALID_TARGET");
            }
            if (!target.valid()) throw new PlayerFailure(target instanceof PlayerService.Player ? "PLAYER_NOT_FOUND" : "ENTITY_NOT_FOUND");
            unique.putIfAbsent(target.uuid(), target);
        }
        return List.copyOf(unique.values());
    }
    private PlayerService.Player player(String value) throws PlayerFailure {
        PlayerService.Player player = backend.findPlayer(value);
        if (player == null || !player.online()) throw new PlayerFailure("PLAYER_NOT_FOUND");
        return player;
    }
    private PlayerService.Target target(String value, Kind kind) throws PlayerFailure {
        if (!value.matches("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")) return player(value);
        PlayerService.Target target = backend.findTarget(UUID.fromString(value));
        if (target == null) throw new PlayerFailure(kind == Kind.PLAYERS ? "PLAYER_NOT_FOUND" : "ENTITY_NOT_FOUND");
        return target;
    }
}
