package dev.minebridge.protocol;

/** Remote error fields are data; callers must not log the untrusted message. */
public record RpcError(JsonNumber numericCode, String message, String code, String outcome) {
    @Override public String toString() { return "RpcError[redacted]"; }
}
