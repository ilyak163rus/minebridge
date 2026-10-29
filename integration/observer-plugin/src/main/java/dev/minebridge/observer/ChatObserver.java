package dev.minebridge.observer;

import io.papermc.paper.event.player.AsyncChatEvent;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;
import net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;

/** Independent bounded async-chat audit and one exact-message cancellation seam.
 * Console setup/read executes on the server thread; capture stores only immutable
 * snapshots under a lock and never queries the bridge's event implementation. */
final class ChatObserver implements Listener {
    private final ObserverPlugin plugin;
    private final ArrayDeque<Map<String, Object>> captured = new ArrayDeque<>();
    private volatile String cancelledMessage;
    private long sequence;

    ChatObserver(ObserverPlugin plugin) { this.plugin = plugin; }

    Map<String, Object> execute(String[] args) {
        if (!plugin.getServer().isPrimaryThread()) throw new IllegalStateException();
        return switch (args[2]) {
            case "chatState" -> {
                if (args.length != 3) throw new IllegalArgumentException();
                synchronized (captured) {
                    yield map("events", new ArrayList<>(captured), "sequence", sequence,
                            "cancelledMessage", cancelledMessage);
                }
            }
            case "chatClear" -> {
                if (args.length != 3) throw new IllegalArgumentException();
                synchronized (captured) { captured.clear(); }
                yield map("cleared", true);
            }
            case "chatCancel" -> {
                if (args.length != 4 || args[3].length() > 256) throw new IllegalArgumentException();
                cancelledMessage = args[3].equals("$reset") ? null : args[3];
                yield map("cancelledMessage", cancelledMessage);
            }
            default -> throw new IllegalArgumentException();
        };
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void cancel(AsyncChatEvent event) {
        String wanted = cancelledMessage;
        if (wanted != null && wanted.equals(PlainTextComponentSerializer.plainText().serialize(event.message()))) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void record(AsyncChatEvent event) {
        // Player UUID/name are immutable connection identity, not mutable world
        // state. The independent oracle intentionally records cancelled events.
        String player = event.getPlayer().getUniqueId().toString();
        String name = event.getPlayer().getName();
        String message = PlainTextComponentSerializer.plainText().serialize(event.message());
        synchronized (captured) {
            if (captured.size() == 256) captured.removeFirst();
            captured.addLast(map("sequence", ++sequence, "playerUuid", player, "playerName", name,
                    "message", message, "cancelled", event.isCancelled(), "asynchronous", event.isAsynchronous(),
                    "thread", Thread.currentThread().getName()));
        }
    }

    private static Map<String, Object> map(Object... values) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int index = 0; index < values.length; index += 2) result.put((String) values[index], values[index + 1]);
        return result;
    }
}
