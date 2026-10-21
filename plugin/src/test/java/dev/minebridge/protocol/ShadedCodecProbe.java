package dev.minebridge.protocol;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/** Run with ONLY test classes and the production shaded JAR on the classpath. */
public final class ShadedCodecProbe {
    private ShadedCodecProbe() { }

    public static void main(String[] args) {
        byte[] frame = JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", 2,
                "method", "blocks.set", "params", Map.of("world", "мир", "position", List.of(0, 80, -1),
                        "block", Map.of("key", "minecraft:stone", "states", Map.of()))));
        List<byte[]> frames = new FrameDecoder().feed(frame);
        if (frames.size() != 1 || !Long.valueOf(2).equals(JsonRpcCodec.decodeRequest(frames.getFirst()).id())) {
            throw new AssertionError("Request round trip failed");
        }
        Response response = JsonRpcCodec.decodeResponse(
                "{\"jsonrpc\":\"2.0\",\"id\":2,\"result\":{\"applied\":true}}".getBytes(StandardCharsets.UTF_8),
                2L, "blocks.set");
        if (response.error() != null || !Boolean.TRUE.equals(response.result().get("applied"))) {
            throw new AssertionError("Response decode failed");
        }
        byte[] errorFrame = JsonRpcCodec.errorFrame(null, "PARSE_ERROR", "not-applied");
        Response error = JsonRpcCodec.decodeResponse(Arrays.copyOf(errorFrame, errorFrame.length - 1), null, "blocks.set");
        if (!"PARSE_ERROR".equals(error.error().code())) throw new AssertionError("Error factory failed");
        System.out.println("Shaded codec probe passed");
    }
}
