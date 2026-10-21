package dev.minebridge.session;

import java.util.HashMap;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

/** Main-game-thread ownership of connection contexts, bounded by the listener session limit. */
public final class SessionManager implements AutoCloseable {
    private final int maxSessions;
    private final Map<Session, WorldContext> contexts = new HashMap<>();
    private boolean closed;

    public SessionManager(int maxSessions) {
        if (maxSessions < 1 || maxSessions > 1024) throw new IllegalArgumentException("Invalid session capacity");
        this.maxSessions = maxSessions;
    }

    public Optional<WorldContext> context(Session session) {
        Objects.requireNonNull(session);
        return session.isReady() ? Optional.ofNullable(contexts.get(session)) : Optional.empty();
    }

    /** Publish a context only if its successful hello can atomically enter the output queue. */
    public boolean completeHandshake(Session session, WorldContext world, byte[] frame) {
        Objects.requireNonNull(session);
        Objects.requireNonNull(world);
        if (closed) return false;
        pruneClosed();
        if (contexts.size() >= maxSessions || contexts.containsKey(session)) return false;
        synchronized (session) {
            if (!session.completeHandshake(frame, world)) return false;
            contexts.put(session, world);
            return true;
        }
    }

    public void pruneClosed() { contexts.keySet().removeIf(session -> !session.isReady()); }

    public int readyCount() {
        pruneClosed();
        return contexts.size();
    }

    @Override public void close() {
        closed = true;
        contexts.keySet().forEach(Session::close);
        contexts.clear();
    }

    @Override public String toString() { return "SessionManager[contexts=redacted]"; }
}
