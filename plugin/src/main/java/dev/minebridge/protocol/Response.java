package dev.minebridge.protocol;

import java.util.Map;

/** Exactly one of result and error is non-null after decoding. */
public record Response(Long id, Map<String, Object> result, RpcError error) {
    @Override public String toString() { return "Response[id=" + id + ", result=redacted, error=redacted]"; }
}
