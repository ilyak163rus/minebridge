package dev.minebridge.session;

import dev.minebridge.protocol.JsonNumber;
import dev.minebridge.protocol.Request;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Consumer;

/** Opt-in session activity. Producers only queue bounded lines; a separate task performs log IO. */
public final class SessionActivityLog {
    private static final int CAPACITY = 4096;
    private static final Set<String> METHODS = Set.of("blocks.set", "blocks.get", "blocks.setRegion", "blocks.getRegion",
            "players.get", "players.list", "players.getPos", "players.teleport", "chat.post",
            "players.giveItem", "effects.add", "entities.spawn", "effects.remove", "effects.clear",
            "players.getGameMode", "players.setGameMode", "players.getHealth", "players.setHealth",
            "players.getFoodLevel", "players.setFoodLevel", "worlds.getTime", "worlds.setTime",
            "worlds.getWeather", "worlds.setWeather", "worlds.getGameRule", "worlds.setGameRule",
            "events.subscribe", "events.unsubscribe", "events.pollEvents", "events.getRecent", "events.clearPending",
            "inventories.ofBlock", "inventories.ofPlayer", "inventories.getItem", "inventories.getContents",
            "inventories.setItem", "inventories.clear", "players.setItem");
    private final ArrayDeque<String> pending = new ArrayDeque<>();
    private long dropped;

    public void received(Session session, Request request) { record(session, request, "received", null); }
    public void completed(Session session, Request request, Map<String, Object> result, boolean ackQueued) {
        record(session, request, "completed", "ackQueued=" + ackQueued + " result=" + summary(result, 0));
    }
    public void failed(Session session, Request request, String code, String outcome) {
        record(session, request, "error", "code=" + safe(code) + " outcome=" + safe(outcome));
    }
    public void disconnected(Session session) {
        append("ACTION session=" + session.id() + " phase=disconnected activeRequest="
                + session.activeRequestId() + " queuedRequests=" + session.queuedRequests());
    }

    /** Queueing evidence only; it never claims a Python callback has run. */
    public void event(Session session, java.util.UUID subscriptionId, String phase, long sequence) {
        if (!("queued".equals(phase) || "overflow".equals(phase))) return;
        append("ACTION session=" + session.id() + " method=events.event phase=" + phase
                + " subscription=" + subscriptionId + " sequence=" + sequence);
    }

    private void record(Session session, Request request, String phase, String result) {
        WorldContext world = session.worldContext();
        String line = "ACTION session=" + session.id() + " request=" + request.id()
                + " method=" + safe(request.method()) + " phase=" + phase
                + " world=" + (world == null ? "pending" : safe(world.name()));
        // Never dump hello/token or unknown-method payloads. Only known API parameters are shown.
        if (METHODS.contains(request.method())) line += " params=" + summary(request.params(), 0);
        if (result != null) line += " " + result;
        append(line);
    }

    private synchronized void append(String line) {
        if (pending.size() == CAPACITY) { dropped++; return; }
        pending.addLast(line.length() <= 2048 ? line : line.substring(0, 2048) + "...");
    }

    /** No Paper API calls; safe on an asynchronous scheduler task and during shutdown. */
    public void drain(Consumer<String> sink) {
        List<String> lines;
        synchronized (this) {
            lines = new ArrayList<>(pending);
            pending.clear();
            if (dropped != 0) {
                lines.add("ACTION logging buffer full; omitted=" + dropped);
                dropped = 0;
            }
        }
        for (String line : lines) {
            try { sink.accept(line); }
            catch (RuntimeException ignored) { /* Diagnostics cannot change execution or ACK delivery. */ }
        }
    }

    private static String summary(Object value, int depth) {
        if (value == null) return "null";
        if (value instanceof JsonNumber number) return safe(number.text());
        if (value instanceof String text) return "\"" + safe(text) + "\"";
        if (value instanceof Number || value instanceof Boolean) return value.toString();
        if (depth >= 4) return "...";
        if (value instanceof List<?> list) {
            List<String> fields = new ArrayList<>();
            for (int i = 0; i < Math.min(6, list.size()); i++) fields.add(summary(list.get(i), depth + 1));
            if (list.size() > 6) fields.add("... count=" + list.size());
            return "[" + String.join(",", fields) + "]";
        }
        if (value instanceof Map<?, ?> map) {
            List<String> fields = new ArrayList<>();
            for (var entry : map.entrySet()) {
                if (fields.size() == 12) { fields.add("..."); break; }
                if ("token".equals(entry.getKey())) continue;
                fields.add(safe(String.valueOf(entry.getKey())) + "=" + summary(entry.getValue(), depth + 1));
            }
            return "{" + String.join(",", fields) + "}";
        }
        return "...";
    }

    private static String safe(String text) {
        if (text == null) return "null";
        StringBuilder result = new StringBuilder();
        int count = 0;
        for (int cp : text.codePoints().limit(161).toArray()) {
            if (count++ == 160) { result.append("..."); break; }
            if (cp == '\\') result.append("\\\\");
            else if (cp == '"') result.append("\\\"");
            else if (Character.isISOControl(cp) || cp == 0x2028 || cp == 0x2029) result.append(String.format("\\u%04x", cp));
            else result.appendCodePoint(cp);
        }
        return result.toString();
    }
}
