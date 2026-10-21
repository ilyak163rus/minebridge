package dev.minebridge.protocol;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Incremental bounded LF framing. No knowledge of sockets or RPC execution. */
public final class FrameDecoder {
    private final ByteArrayOutputStream pending = new ByteArrayOutputStream();
    private boolean finished;

    /** Bytes in the incomplete tail; used by the transport's absolute deadline. */
    public int pendingBytes() { return pending.size(); }

    public List<byte[]> feed(byte[] chunk) {
        if (finished) throw new CodecException("DECODER_CLOSED", null, false, true);
        List<byte[]> frames = new ArrayList<>();
        for (byte value : chunk) {
            if (value == '\n') {
                byte[] payload = pending.toByteArray();
                pending.reset();
                if (payload.length > 0 && payload[payload.length - 1] == '\r') {
                    payload = Arrays.copyOf(payload, payload.length - 1);
                }
                frames.add(payload);
            } else {
                if (pending.size() == JsonRpcCodec.MAX_FRAME_BYTES) {
                    finished = true;
                    pending.reset();
                    throw new CodecException("FRAME_TOO_LARGE", null, false, true);
                }
                pending.write(value);
            }
        }
        return frames;
    }

    public void finish() {
        if (finished) throw new CodecException("DECODER_CLOSED", null, false, true);
        finished = true;
        if (pending.size() != 0) {
            pending.reset();
            throw new CodecException("EOF_PARTIAL", null, false, true);
        }
    }
}
