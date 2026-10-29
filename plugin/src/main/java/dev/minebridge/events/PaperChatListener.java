package dev.minebridge.events;

import dev.minebridge.session.WorldContext;

import io.papermc.paper.event.player.AsyncChatEvent;

import net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer;

import org.bukkit.Server;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerChangedWorldEvent;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerQuitEvent;

import java.util.ArrayList;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Map;

/**
 * Native chat adapter. The async path never reads live entity/world state or retains a Java event.
 */
public final class PaperChatListener implements Listener, AutoCloseable {
    private final Server server;
    private final EventsService events;
    // IdentityHashMap lookup uses == and System.identityHashCode: even Player#getUniqueId/hashCode
    // is avoided async.
    private volatile Map<Player, EventsService.PlayerSnapshot> identities = Map.of();

    public PaperChatListener(Server server, EventsService events) {
        this.server = server;
        this.events = events;
    }

    public void refreshPlayers() {
        if (!server.isPrimaryThread()) throw new IllegalStateException("Game thread required");
        IdentityHashMap<Player, EventsService.PlayerSnapshot> next = new IdentityHashMap<>();
        ArrayList<EventsService.PlayerSnapshot> snapshots = new ArrayList<>();
        for (Player player : server.getOnlinePlayers()) {
            org.bukkit.World world = player.getWorld();
            EventsService.PlayerSnapshot snapshot =
                    new EventsService.PlayerSnapshot(
                            player.getUniqueId(),
                            player.getName(),
                            player.getEntityId(),
                            new WorldContext(
                                    world.getName(),
                                    world.getKey().toString(),
                                    world.getUID(),
                                    world.getMinHeight(),
                                    world.getMaxHeight()));
            next.put(player, snapshot);
            snapshots.add(snapshot);
        }
        identities = Collections.unmodifiableMap(next);
        events.replacePlayers(snapshots);
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onChat(AsyncChatEvent event) {
        EventsService.PlayerSnapshot identity = identities.get(event.getPlayer());
        if (identity == null) return;
        try {
            events.captureChat(
                    identity,
                    PlainTextComponentSerializer.plainText().serialize(event.message()),
                    event.isCancelled());
        } catch (RuntimeException invalidForeignMessage) {
            // No source snippets or Bukkit exception text cross the boundary. Readers must see that
            // capture failed.
            events.captureFailed(identity);
        }
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onJoin(PlayerJoinEvent event) {
        refreshPlayers();
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onQuit(PlayerQuitEvent event) {
        refreshPlayers();
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onWorldChanged(PlayerChangedWorldEvent event) {
        refreshPlayers();
    }

    @Override
    public void close() {
        identities = Map.of();
    }
}
