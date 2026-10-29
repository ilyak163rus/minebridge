package dev.minebridge.protocol;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;
import org.junit.jupiter.api.DynamicTest;
import org.junit.jupiter.api.TestFactory;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.*;

/** The same checked-in byte corpus is executed by Python and Java. */
class ProtocolCorpusTest {
    @TestFactory Stream<DynamicTest> sharedCorpus() throws IOException {
        Path path = Path.of(System.getProperty("minebridge.fixtures", "../protocol/v2/fixtures/corpus.json"));
        Map<String, Object> corpus;
        try (JsonParser parser = new JsonFactory().createParser(Files.readString(path, StandardCharsets.UTF_8))) {
            corpus = map(read(parser, parser.nextToken()));
        }
        assertEquals("1", ((JsonNumber) corpus.get("formatVersion")).text());
        return ((List<?>) corpus.get("cases")).stream().map(value -> {
            Map<String, Object> fixture = map(value);
            return DynamicTest.dynamicTest((String) fixture.get("name"), () -> runFixture(fixture));
        });
    }

    private static void runFixture(Map<String, Object> fixture) {
        Map<String, Object> expect = map(fixture.get("expect"));
        byte[] payload = payload(fixture);
        if ("failure".equals(expect.get("kind"))) {
            CodecException failure = assertThrows(CodecException.class, () -> decode(fixture, payload));
            assertEquals(expect.get("code"), failure.code());
            if (expect.containsKey("id")) assertEquals(id(expect.get("id")), failure.requestId());
            if (expect.containsKey("reply")) assertEquals(expect.get("reply"), failure.reply());
            if (expect.containsKey("close")) assertEquals(expect.get("close"), failure.close());
            return;
        }
        Object value = decode(fixture, payload);
        switch ((String) expect.get("kind")) {
            case "request", "notification" -> {
                Request request = assertInstanceOf(Request.class, value);
                assertEquals(id(expect.get("id")), request.id());
                assertEquals("notification".equals(expect.get("kind")), request.notification());
            }
            case "result" -> {
                Response response = assertInstanceOf(Response.class, value);
                assertEquals(id(expect.get("id")), response.id());
                assertNotNull(response.result());
                assertNull(response.error());
            }
            case "error" -> {
                Response response = assertInstanceOf(Response.class, value);
                assertEquals(id(expect.get("id")), response.id());
                assertNull(response.result());
                assertNotNull(response.error());
                assertEquals(expect.get("code"), response.error().code());
            }
            case "frames" -> assertEquals(Integer.parseInt(((JsonNumber) expect.get("frameCount")).text()), ((List<?>) value).size());
            default -> fail("Unknown fixture expectation");
        }
    }

    private static Object decode(Map<String, Object> fixture, byte[] payload) {
        return switch ((String) fixture.get("mode")) {
            case "request" -> JsonRpcCodec.decodeRequest(payload);
            case "hello-response" -> JsonRpcCodec.decodeResponse(payload, id(fixture.get("expectedId")), "system.hello");
            case "blocks-response" -> JsonRpcCodec.decodeResponse(payload, id(fixture.get("expectedId")), "blocks.set");
            case "method-response" -> JsonRpcCodec.decodeResponse(payload, id(fixture.get("expectedId")), (String) fixture.get("method"));
            case "stream" -> {
                FrameDecoder decoder = new FrameDecoder();
                List<byte[]> frames = new ArrayList<>();
                int offset = 0;
                if (fixture.get("chunkSizes") instanceof List<?> chunks) {
                    for (Object chunk : chunks) {
                        int end = Math.min(payload.length, offset + Integer.parseInt(((JsonNumber) chunk).text()));
                        frames.addAll(decoder.feed(Arrays.copyOfRange(payload, offset, end)));
                        offset = end;
                    }
                }
                if (offset < payload.length) frames.addAll(decoder.feed(Arrays.copyOfRange(payload, offset, payload.length)));
                if (Boolean.TRUE.equals(fixture.get("eof"))) decoder.finish();
                yield frames;
            }
            default -> throw new AssertionError("Unknown fixture mode");
        };
    }

    private static byte[] payload(Map<String, Object> fixture) {
        if (fixture.containsKey("text")) return ((String) fixture.get("text")).getBytes(StandardCharsets.UTF_8);
        if (fixture.containsKey("hex")) return HexFormat.of().parseHex((String) fixture.get("hex"));
        Map<String, Object> construction = map(fixture.get("construction"));
        String text = (String) construction.get("prefix") + ((String) construction.get("repeat"))
                .repeat(Integer.parseInt(((JsonNumber) construction.get("count")).text())) + construction.get("suffix");
        return text.getBytes(StandardCharsets.UTF_8);
    }

    private static Object read(JsonParser parser, JsonToken token) throws IOException {
        return switch (token) {
            case START_OBJECT -> {
                Map<String, Object> value = new LinkedHashMap<>();
                while (parser.nextToken() != JsonToken.END_OBJECT) {
                    String key = parser.currentName();
                    value.put(key, read(parser, parser.nextToken()));
                }
                yield value;
            }
            case START_ARRAY -> {
                List<Object> value = new ArrayList<>();
                JsonToken next;
                while ((next = parser.nextToken()) != JsonToken.END_ARRAY) value.add(read(parser, next));
                yield value;
            }
            case VALUE_STRING -> parser.getText();
            case VALUE_NUMBER_INT, VALUE_NUMBER_FLOAT -> new JsonNumber(parser.getText());
            case VALUE_TRUE -> Boolean.TRUE;
            case VALUE_FALSE -> Boolean.FALSE;
            case VALUE_NULL -> null;
            default -> throw new AssertionError("Invalid corpus JSON");
        };
    }

    private static Long id(Object value) { return value == null ? null : Long.valueOf(((JsonNumber) value).text()); }
    @SuppressWarnings("unchecked") private static Map<String, Object> map(Object value) { return (Map<String, Object>) value; }
}
