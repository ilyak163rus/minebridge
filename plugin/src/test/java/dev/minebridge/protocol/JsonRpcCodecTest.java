package dev.minebridge.protocol;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class JsonRpcCodecTest {
    private static final String BLOCK = "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"blocks.set\",\"params\":{\"world\":\"world\",\"position\":[0,80,-1],\"block\":{\"key\":\"minecraft:stone\",\"states\":{}}}}";

    @Test void requestRetainsIntegerLexemesAndIsImmutable() {
        Request request = JsonRpcCodec.decodeRequest(bytes(BLOCK));
        assertEquals(2L, request.id());
        assertEquals("-1", ((JsonNumber) ((List<?>) request.params().get("position")).get(2)).text());
        assertThrows(UnsupportedOperationException.class, () -> request.params().put("world", "other"));
        assertThrows(UnsupportedOperationException.class, () -> ((Map<?, ?>) request.params().get("block")).clear());
    }

    @Test void notificationsNeverValidateOrExecuteMethodParameters() {
        Request request = JsonRpcCodec.decodeRequest(bytes("{\"jsonrpc\":\"2.0\",\"method\":\"blocks.set\",\"params\":{}}"));
        assertTrue(request.notification());
        assertNull(request.id());
    }

    @Test void envelopeValidationCanPrecedeSessionPolicyWithoutChangingStrictDecode() {
        byte[] payload = bytes("{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"blocks.set\",\"params\":{}}");
        Request envelope = JsonRpcCodec.decodeEnvelope(payload);
        assertEquals(2L, envelope.id());
        assertEquals("blocks.set", envelope.method());
        assertTrue(envelope.params().isEmpty());
        CodecException deferred = assertThrows(CodecException.class,
                () -> JsonRpcCodec.validateRequestParameters(envelope));
        CodecException strict = assertThrows(CodecException.class, () -> JsonRpcCodec.decodeRequest(payload));
        assertEquals("INVALID_PARAMS", deferred.code());
        assertEquals(strict.code(), deferred.code());
        assertEquals(strict.requestId(), deferred.requestId());
        assertEquals(strict.reply(), deferred.reply());
        assertEquals(strict.close(), deferred.close());
    }

    @Test void rawCoordinateDecimalsAreNotRounded() {
        CodecException error = assertThrows(CodecException.class,
                () -> JsonRpcCodec.decodeRequest(bytes(BLOCK.replace("[0,80,-1]", "[0,80.0,-1]"))));
        assertEquals("INVALID_PARAMS", error.code());
        assertEquals(2L, error.requestId());
        assertTrue(error.reply());
        assertFalse(error.close());
    }

    @Test void hugeProtocolIntegerHasNoImplicitJacksonNumberLimit() {
        String request = "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"system.hello\",\"params\":{\"protocol\":{\"major\":"
                + "9".repeat(12_000) + ",\"minor\":-0},\"token\":\"\",\"world\":null,\"coordinates\":\"absolute\"}}";
        Request decoded = JsonRpcCodec.decodeRequest(bytes(request));
        assertEquals(12_000, ((JsonNumber) ((Map<?, ?>) decoded.params().get("protocol")).get("major")).text().length());
    }

    @Test void depthLimitPrecedesSyntaxButIgnoresQuotedEscapedBrackets() {
        CodecException error = assertThrows(CodecException.class,
                () -> JsonRpcCodec.decodeRequest(bytes("x" + "[".repeat(17))));
        assertEquals("JSON_TOO_DEEP", error.code());
        assertFalse(error.reply());
        assertTrue(error.close());
        byte[] frame = JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", 1, "method", "future",
                "params", Map.of("brackets", "\"\\[".repeat(64))));
        Request request = JsonRpcCodec.decodeRequest(Arrays.copyOf(frame, frame.length - 1));
        assertEquals("\"\\[".repeat(64), request.params().get("brackets"));
    }

    @Test void framingSurvivesEverySplitInMultibyteText() {
        byte[] frame = bytes(BLOCK.replace("\"world\":\"world\"", "\"world\":\"мир🌍\"") + "\r\n");
        for (int split = 0; split <= frame.length; split++) {
            FrameDecoder decoder = new FrameDecoder();
            List<byte[]> result = new ArrayList<>(decoder.feed(Arrays.copyOf(frame, split)));
            result.addAll(decoder.feed(Arrays.copyOfRange(frame, split, frame.length)));
            decoder.finish();
            assertEquals(1, result.size(), "split " + split);
            assertEquals(2L, JsonRpcCodec.decodeRequest(result.getFirst()).id());
        }
    }

    @Test void crCountsTowardsMaximumAndEofRejectsPartial() {
        FrameDecoder decoder = new FrameDecoder();
        assertEquals(1, decoder.feed(bytes("x".repeat(JsonRpcCodec.MAX_FRAME_BYTES - 1) + "\r\n")).size());
        FrameDecoder tooLarge = new FrameDecoder();
        assertEquals("FRAME_TOO_LARGE", assertThrows(CodecException.class,
                () -> tooLarge.feed(bytes("x".repeat(JsonRpcCodec.MAX_FRAME_BYTES) + "\r\n"))).code());
        FrameDecoder partial = new FrameDecoder();
        partial.feed(bytes("{}"));
        assertEquals("EOF_PARTIAL", assertThrows(CodecException.class, partial::finish).code());
    }

    @Test void knownRemoteErrorCodeMustAgreeWithMachineName() {
        String response = "{\"jsonrpc\":\"2.0\",\"id\":2,\"error\":{\"code\":-32023,\"message\":\"safe\",\"data\":{\"code\":\"CHUNK_NOT_LOADED\",\"outcome\":\"not-applied\"}}}";
        assertEquals("CHUNK_NOT_LOADED", JsonRpcCodec.decodeResponse(bytes(response), 2L, "blocks.set").error().code());
        assertEquals("INVALID_RESPONSE", assertThrows(CodecException.class,
                () -> JsonRpcCodec.decodeResponse(bytes(response.replace("CHUNK_NOT_LOADED", "OTHER")), 2L, "blocks.set")).code());
    }

    @Test void helloMetadataWhitespaceMatchesPythonStripIncludingNbspAndNel() {
        String hello = "{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"protocol\":{\"major\":2,\"minor\":0},"
                + "\"sessionId\":\"31cadb96-7a40-4f45-a068-213352f6cb26\",\"pluginVersion\":\"VERSION\","
                + "\"serverVersion\":\"26.2\",\"world\":{\"name\":\"world\",\"key\":\"minecraft:overworld\",\"uuid\":\"a1905647-deee-4732-a516-4bc34a1ed1d9\","
                + "\"minY\":-64,\"maxYExclusive\":320},\"coordinates\":\"absolute\",\"chunkPolicy\":\"loaded-only\","
                + "\"applyPhysics\":true,\"capabilities\":[\"blocks.set\"],\"limits\":{\"maxFrameBytes\":65536,\"maxJsonDepth\":16,"
                + "\"maxSessions\":8,\"maxQueuedRequests\":8,\"maxOutputFrames\":8,\"handshakeTimeoutSeconds\":5,"
                + "\"frameAssemblyTimeoutSeconds\":5,\"writeTimeoutSeconds\":5,\"maxOperationsPerTick\":32,"
                + "\"maxOperationsPerSessionPerTick\":4,\"executorBudgetMillis\":2}}}";
        for (String blank : List.of("\u00A0", "\u0085", " \u2007\u202F")) {
            assertEquals("INVALID_RESPONSE", assertThrows(CodecException.class,
                    () -> JsonRpcCodec.decodeResponse(bytes(hello.replace("VERSION", blank)), 1L, "system.hello")).code());
        }
        assertNotNull(JsonRpcCodec.decodeResponse(bytes(hello.replace("VERSION", "\u00A0v1\u0085")), 1L, "system.hello").result());
    }

    @Test void safeRepresentationsAndErrorsDoNotRevealSecrets() {
        String secret = "SECRET-TOKEN-MUST-NOT-LEAK";
        Request request = JsonRpcCodec.decodeRequest(bytes("{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"unknown\",\"params\":{\"token\":\"" + secret + "\"}}"));
        assertFalse(request.toString().contains(secret));
        Response response = JsonRpcCodec.decodeResponse(bytes("{\"jsonrpc\":\"2.0\",\"id\":1,\"error\":{\"code\":-999,\"message\":\"" + secret + "\",\"data\":{\"code\":\"FUTURE\",\"outcome\":\"unknown\"}}}"), 1L, "blocks.set");
        assertFalse(response.toString().contains(secret));
        assertFalse(response.error().toString().contains(secret));
        CodecException error = assertThrows(CodecException.class, () -> JsonRpcCodec.decodeRequest(bytes("{\"token\":\"" + secret + "\",}")));
        assertFalse(error.toString().contains(secret));
        assertNull(error.getCause());
    }

    @Test void encoderEscapesNewlineAndPreservesJsonNumbers() {
        byte[] frame = JsonRpcCodec.encodeFrame(Map.of("jsonrpc", "2.0", "id", 1L, "method", "future",
                "params", Map.of("text", "мир\n🌍", "number", new JsonNumber("1.00e+99999"))));
        assertEquals('\n', frame[frame.length - 1]);
        assertEquals(1, new FrameDecoder().feed(frame).size());
        Request request = JsonRpcCodec.decodeRequest(Arrays.copyOf(frame, frame.length - 1));
        assertEquals("мир\n🌍", request.params().get("text"));
        assertEquals("1.00e+99999", ((JsonNumber) request.params().get("number")).text());
    }

    @Test void encoderRejectsCyclesNonfiniteAndUnpairedSurrogatesSafely() {
        Map<String, Object> cycle = new LinkedHashMap<>();
        cycle.put("cycle", cycle);
        for (Map<String, Object> value : List.of(cycle, Map.<String, Object>of("x", Double.NaN),
                Map.<String, Object>of("x", "\uD800"), Map.<String, Object>of("x", new Object()))) {
            assertEquals("ENCODING_ERROR", assertThrows(CodecException.class, () -> JsonRpcCodec.encodeFrame(value)).code());
        }
        assertEquals("FRAME_TOO_LARGE", assertThrows(CodecException.class,
                () -> JsonRpcCodec.encodeFrame(Map.of("x", "x".repeat(JsonRpcCodec.MAX_FRAME_BYTES)))).code());
    }

    @Test void encoderReportsDuplicateIdentityMapKeysAsLocalEncodingFailure() {
        Map<String, Object> value = new IdentityHashMap<>();
        value.put(new String("x"), 1);
        value.put(new String("x"), 2);
        CodecException error = assertThrows(CodecException.class, () -> JsonRpcCodec.encodeFrame(value));
        assertEquals("ENCODING_ERROR", error.code());
        assertFalse(error.reply());
        assertTrue(error.close());
        assertNull(error.getCause());
    }

    private static byte[] bytes(String text) { return text.getBytes(StandardCharsets.UTF_8); }
}
