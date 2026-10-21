package dev.minebridge.protocol;

/** A safe protocol failure: never retains parser causes or untrusted payload text. */
public final class CodecException extends RuntimeException {
    private final String code;
    private final Long requestId;
    private final boolean reply;
    private final boolean close;

    public CodecException(String code, Long requestId, boolean reply, boolean close) {
        super("Protocol codec rejected a message: " + code, null, false, false);
        this.code = code;
        this.requestId = requestId;
        this.reply = reply;
        this.close = close;
    }

    public String code() { return code; }
    public Long requestId() { return requestId; }
    public boolean reply() { return reply; }
    public boolean close() { return close; }
}
