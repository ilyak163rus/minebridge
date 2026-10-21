package dev.minebridge.protocol;

import java.util.Map;

/** Validated request. A null id marks a notification that must never execute. */
public record Request(Long id, String method, Map<String, Object> params) {
    public boolean notification() { return id == null; }
    @Override public String toString() { return "Request[id=" + id + ", method=redacted, params=redacted]"; }
}
