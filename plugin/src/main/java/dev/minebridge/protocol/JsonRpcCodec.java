package dev.minebridge.protocol;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;
import com.fasterxml.jackson.core.StreamReadConstraints;
import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.core.exc.StreamConstraintsException;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/** Pure protocol 1.0 codec. It deliberately has no transport, session or Paper API. */
public final class JsonRpcCodec {
    public static final int MAX_FRAME_BYTES = 65_536;
    public static final int MAX_JSON_DEPTH = 16;
    public static final long MAX_REQUEST_ID = 9_007_199_254_740_991L;

    private static final Pattern INTEGER = Pattern.compile("-?(?:0|[1-9][0-9]*)");
    private static final Pattern BLOCK_KEY = Pattern.compile("[a-z0-9_.-]+:[a-z0-9/._-]+");
    private static final Pattern UUID = Pattern.compile("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}");
    private static final JsonFactory JSON = JsonFactory.builder()
            .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
            .disable(StreamReadFeature.INCLUDE_SOURCE_IN_LOCATION)
            .streamReadConstraints(StreamReadConstraints.builder()
                    .maxNestingDepth(MAX_JSON_DEPTH)
                    .maxNumberLength(MAX_FRAME_BYTES)
                    .maxStringLength(MAX_FRAME_BYTES)
                    .maxNameLength(MAX_FRAME_BYTES).build())
            .build();

    private static final Map<String, String> ERROR_CODES = Map.ofEntries(
            Map.entry("-32700", "PARSE_ERROR"), Map.entry("-32600", "INVALID_REQUEST"),
            Map.entry("-32601", "METHOD_NOT_FOUND"), Map.entry("-32602", "INVALID_PARAMS"),
            Map.entry("-32603", "INTERNAL_ERROR"), Map.entry("-32001", "AUTH_FAILED"),
            Map.entry("-32002", "PROTOCOL_VERSION"), Map.entry("-32003", "NOT_READY"),
            Map.entry("-32004", "INVALID_STATE"), Map.entry("-32010", "LIMIT_EXCEEDED"),
            Map.entry("-32020", "WORLD_NOT_FOUND"), Map.entry("-32021", "PERMISSION_DENIED"),
            Map.entry("-32022", "COORDINATE_OUT_OF_BOUNDS"), Map.entry("-32023", "CHUNK_NOT_LOADED"),
            Map.entry("-32024", "INVALID_BLOCK"), Map.entry("-32025", "UNSUPPORTED_FEATURE"));
    private static final List<String> COUNT_LIMITS = List.of("maxFrameBytes", "maxJsonDepth", "maxSessions",
            "maxQueuedRequests", "maxOutputFrames", "maxOperationsPerTick", "maxOperationsPerSessionPerTick");
    private static final List<String> TIME_LIMITS = List.of("handshakeTimeoutSeconds", "frameAssemblyTimeoutSeconds",
            "writeTimeoutSeconds", "executorBudgetMillis");

    private JsonRpcCodec() { }

    /** Builds only known error envelopes with a fixed, non-sensitive message. */
    public static byte[] errorFrame(Long id, String code, String outcome) {
        if (!("not-applied".equals(outcome) || "unknown".equals(outcome))) throw encodingError();
        String numeric = null;
        for (Map.Entry<String, String> entry : ERROR_CODES.entrySet()) {
            if (entry.getValue().equals(code)) { numeric = entry.getKey(); break; }
        }
        if (numeric == null || (id != null && (id <= 0 || id > MAX_REQUEST_ID))) throw encodingError();
        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("jsonrpc", "2.0");
        envelope.put("id", id);
        envelope.put("error", Map.of("code", new JsonNumber(numeric), "message", "Request rejected",
                "data", Map.of("code", code, "outcome", outcome)));
        return encodeFrame(envelope);
    }

    public static Request decodeRequest(byte[] payload) {
        Request request = decodeEnvelope(payload);
        validateRequestParameters(request);
        return request;
    }

    /** Transport-level validation only; session state must precede method parameter checks. */
    public static Request decodeEnvelope(byte[] payload) {
        Object root = parse(payload);
        if (!(root instanceof Map<?, ?>)) throw invalidRequest(null);
        Map<String, Object> envelope = object(root);
        Long id = validId(envelope.get("id"));
        if (!"2.0".equals(envelope.get("jsonrpc"))
                || !(envelope.get("method") instanceof String)
                || !(envelope.get("params") instanceof Map<?, ?>)
                || (envelope.containsKey("id") && id == null)) {
            throw invalidRequest(id);
        }
        String method = (String) envelope.get("method");
        Map<String, Object> params = object(envelope.get("params"));
        return new Request(id, method, params);
    }

    /** Pure method schema checks; the future router invokes these after its session policy. */
    public static void validateRequestParameters(Request request) {
        if (request.notification()) return;
        switch (request.method()) {
            case "system.hello" -> validateHelloRequest(request.params(), request.id());
            case "blocks.set" -> validateBlockRequest(request.params(), request.id());
            default -> { /* Method routing belongs to T05. */ }
        }
    }

    public static Response decodeResponse(byte[] payload, Long expectedId, String method) {
        Object root = parse(payload);
        if (!(root instanceof Map<?, ?>)) throw invalidResponse();
        Map<String, Object> envelope = object(root);
        boolean error = envelope.containsKey("error");
        boolean result = envelope.containsKey("result");
        Long id = validId(envelope.get("id"));
        if (!"2.0".equals(envelope.get("jsonrpc")) || !envelope.containsKey("id") || error == result
                || (expectedId == null ? !(error && envelope.get("id") == null) : !expectedId.equals(id))) {
            throw invalidResponse();
        }
        if (error) return new Response(id, null, validateError(envelope.get("error")));
        if (!(envelope.get("result") instanceof Map<?, ?>)) throw invalidResponse();
        Map<String, Object> value = object(envelope.get("result"));
        switch (method) {
            case "blocks.set" -> { if (!Boolean.TRUE.equals(value.get("applied"))) throw invalidResponse(); }
            case "system.hello" -> validateHelloResult(value);
            default -> throw invalidResponse();
        }
        return new Response(id, value, null);
    }

    /** Encode a JSON object plus LF; unsafe local values fail without retaining their text. */
    public static byte[] encodeFrame(Map<String, Object> envelope) {
        if (envelope == null) throw encodingError();
        ByteArrayOutputStream output = new BoundedOutput();
        try (JsonGenerator generator = JSON.createGenerator(output)) {
            writeValue(generator, envelope, 0, new IdentityHashMap<>());
        } catch (CodecException failure) {
            if ("PARSE_ERROR".equals(failure.code())) throw encodingError();
            throw failure;
        } catch (IOException | IllegalArgumentException failure) {
            throw encodingError();
        }
        byte[] payload = output.toByteArray();
        // This also verifies strict Unicode and all read constraints on generated data.
        try {
            parse(payload);
        } catch (CodecException failure) {
            throw encodingError();
        }
        byte[] frame = Arrays.copyOf(payload, payload.length + 1);
        frame[payload.length] = '\n';
        return frame;
    }

    private static Object parse(byte[] payload) {
        if (payload.length > MAX_FRAME_BYTES) throw new CodecException("FRAME_TOO_LARGE", null, false, true);
        String text;
        try {
            text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(payload)).toString();
        } catch (CharacterCodingException failure) {
            throw new CodecException("INVALID_UTF8", null, false, true);
        }
        if (text.startsWith("\uFEFF")) throw parseError();
        preflightDepth(text);
        try (JsonParser parser = JSON.createParser(text)) {
            JsonToken first = parser.nextToken();
            if (first == null) throw parseError();
            Object value = readValue(parser, first, 0);
            if (parser.nextToken() != null) throw parseError();
            return value;
        } catch (StreamConstraintsException failure) {
            throw new CodecException("JSON_TOO_DEEP", null, false, true);
        } catch (IOException | IllegalArgumentException failure) {
            throw parseError();
        }
    }

    // Resource limits have precedence over JSON syntax errors on both runtimes.
    private static void preflightDepth(String text) {
        int depth = 0;
        boolean inString = false;
        boolean escaped = false;
        for (int i = 0; i < text.length(); i++) {
            char unit = text.charAt(i);
            if (inString) {
                if (escaped) escaped = false;
                else if (unit == '\\') escaped = true;
                else if (unit == '"') inString = false;
            } else if (unit == '"') inString = true;
            else if (unit == '{' || unit == '[') checkDepth(++depth);
            else if (unit == '}' || unit == ']') depth--;
        }
    }

    private static Object readValue(JsonParser parser, JsonToken token, int depth) throws IOException {
        return switch (token) {
            case START_OBJECT -> {
                checkDepth(depth + 1);
                Map<String, Object> value = new LinkedHashMap<>();
                JsonToken next;
                while ((next = parser.nextToken()) != JsonToken.END_OBJECT) {
                    if (next != JsonToken.FIELD_NAME) throw parseError();
                    String key = parser.currentName();
                    validUnicode(key);
                    JsonToken member = parser.nextToken();
                    if (member == null) throw parseError();
                    value.put(key, readValue(parser, member, depth + 1));
                }
                yield Collections.unmodifiableMap(value);
            }
            case START_ARRAY -> {
                checkDepth(depth + 1);
                List<Object> value = new ArrayList<>();
                JsonToken next;
                while ((next = parser.nextToken()) != JsonToken.END_ARRAY) {
                    if (next == null) throw parseError();
                    value.add(readValue(parser, next, depth + 1));
                }
                yield Collections.unmodifiableList(value);
            }
            case VALUE_STRING -> {
                String value = parser.getText();
                validUnicode(value);
                yield value;
            }
            case VALUE_NUMBER_INT, VALUE_NUMBER_FLOAT -> new JsonNumber(parser.getText());
            case VALUE_TRUE -> Boolean.TRUE;
            case VALUE_FALSE -> Boolean.FALSE;
            case VALUE_NULL -> null;
            default -> throw parseError();
        };
    }

    private static void validUnicode(String value) {
        for (int i = 0; i < value.length(); i++) {
            char unit = value.charAt(i);
            if (Character.isHighSurrogate(unit)) {
                if (++i >= value.length() || !Character.isLowSurrogate(value.charAt(i))) throw parseError();
            } else if (Character.isLowSurrogate(unit)) throw parseError();
        }
    }

    private static void validateHelloRequest(Map<String, Object> params, Long id) {
        requireKeys(params, Set.of("protocol", "token", "world", "coordinates"), id);
        if (!(params.get("protocol") instanceof Map<?, ?>) || !(params.get("token") instanceof String)
                || !(params.get("world") == null || params.get("world") instanceof String)
                || !(params.get("coordinates") instanceof String)) throw invalidParams(id);
        Map<String, Object> protocol = object(params.get("protocol"));
        requireKeys(protocol, Set.of("major", "minor"), id);
        if (!nonnegativeInteger(protocol.get("major")) || !nonnegativeInteger(protocol.get("minor"))) {
            throw invalidParams(id);
        }
        if (!"absolute".equals(params.get("coordinates"))) {
            throw new CodecException("UNSUPPORTED_FEATURE", id, true, false);
        }
    }

    private static void validateBlockRequest(Map<String, Object> params, Long id) {
        requireKeys(params, Set.of("world", "position", "block"), id);
        if (!(params.get("world") instanceof String) || !(params.get("position") instanceof List<?> position)
                || position.size() != 3 || !(params.get("block") instanceof Map<?, ?>)) throw invalidParams(id);
        for (Object coordinate : (List<?>) params.get("position")) {
            if (!int32(coordinate)) throw invalidParams(id);
        }
        Map<String, Object> block = object(params.get("block"));
        requireKeys(block, Set.of("key", "states"), id);
        if (!(block.get("key") instanceof String key) || !(block.get("states") instanceof Map<?, ?>)) {
            throw invalidParams(id);
        }
        if (!BLOCK_KEY.matcher((String) block.get("key")).matches()) {
            throw new CodecException("INVALID_BLOCK", id, true, false);
        }
        if (!object(block.get("states")).isEmpty()) {
            throw new CodecException("UNSUPPORTED_FEATURE", id, true, false);
        }
    }

    private static void validateHelloResult(Map<String, Object> result) {
        if (!(result.get("protocol") instanceof Map<?, ?>) || !(result.get("world") instanceof Map<?, ?>)
                || !(result.get("limits") instanceof Map<?, ?>) || !uuid(result.get("sessionId"))
                || !nonblank(result.get("pluginVersion")) || !nonblank(result.get("serverVersion"))
                || !"absolute".equals(result.get("coordinates")) || !"loaded-only".equals(result.get("chunkPolicy"))
                || !Boolean.TRUE.equals(result.get("applyPhysics"))
                || !(result.get("capabilities") instanceof List<?>)) throw invalidResponse();
        Map<String, Object> protocol = object(result.get("protocol"));
        if (!integerEquals(protocol.get("major"), "1") || !integerEquals(protocol.get("minor"), "0")) {
            throw invalidResponse();
        }
        Map<String, Object> world = object(result.get("world"));
        if (!nonblank(world.get("name")) || !uuid(world.get("uuid"))
                || !int32(world.get("minY")) || !int32(world.get("maxYExclusive"))
                || Long.parseLong(((JsonNumber) world.get("minY")).text())
                   >= Long.parseLong(((JsonNumber) world.get("maxYExclusive")).text())) throw invalidResponse();
        List<?> capabilities = (List<?>) result.get("capabilities");
        if (!capabilities.contains("blocks.set") || capabilities.stream().anyMatch(value -> !(value instanceof String))) {
            throw invalidResponse();
        }
        Map<String, Object> limits = object(result.get("limits"));
        for (String name : COUNT_LIMITS) if (!positiveInteger(limits.get(name))) throw invalidResponse();
        for (String name : TIME_LIMITS) if (!positiveNumber(limits.get(name))) throw invalidResponse();
    }

    private static RpcError validateError(Object value) {
        if (!(value instanceof Map<?, ?>)) throw invalidResponse();
        Map<String, Object> error = object(value);
        if (!(error.get("code") instanceof JsonNumber code) || !integer(code)
                || !(error.get("message") instanceof String) || !(error.get("data") instanceof Map<?, ?>)) {
            throw invalidResponse();
        }
        Map<String, Object> data = object(error.get("data"));
        if (!(data.get("code") instanceof String name) || name.isEmpty()
                || !("not-applied".equals(data.get("outcome")) || "unknown".equals(data.get("outcome")))) {
            throw invalidResponse();
        }
        String known = ERROR_CODES.get(((JsonNumber) error.get("code")).text());
        if (known != null && !known.equals(data.get("code"))) throw invalidResponse();
        return new RpcError((JsonNumber) error.get("code"), (String) error.get("message"),
                (String) data.get("code"), (String) data.get("outcome"));
    }

    private static void requireKeys(Map<String, Object> value, Set<String> keys, Long id) {
        if (!value.keySet().equals(keys)) throw invalidParams(id);
    }

    private static boolean integer(Object value) {
        return value instanceof JsonNumber number && INTEGER.matcher(number.text()).matches();
    }

    private static boolean nonnegativeInteger(Object value) {
        return integer(value) && (!((JsonNumber) value).text().startsWith("-") || "-0".equals(((JsonNumber) value).text()));
    }

    private static boolean positiveInteger(Object value) {
        return nonnegativeInteger(value) && !integerEquals(value, "0");
    }

    private static boolean integerEquals(Object value, String expected) {
        return integer(value) && (expected.equals(((JsonNumber) value).text())
                || ("0".equals(expected) && "-0".equals(((JsonNumber) value).text())));
    }

    private static boolean positiveNumber(Object value) {
        if (!(value instanceof JsonNumber number) || number.text().startsWith("-")) return false;
        String text = number.text();
        int exponent = Math.max(text.indexOf('e'), text.indexOf('E'));
        int end = exponent < 0 ? text.length() : exponent;
        for (int i = 0; i < end; i++) if (text.charAt(i) >= '1' && text.charAt(i) <= '9') return true;
        return false;
    }

    private static boolean int32(Object value) {
        if (!integer(value)) return false;
        String text = ((JsonNumber) value).text();
        if (text.length() > 11) return false;
        long number = Long.parseLong(text);
        return number >= Integer.MIN_VALUE && number <= Integer.MAX_VALUE;
    }

    private static Long validId(Object value) {
        if (!positiveInteger(value)) return null;
        String text = ((JsonNumber) value).text();
        if (text.length() > 16) return null;
        long id = Long.parseLong(text);
        return id <= MAX_REQUEST_ID ? id : null;
    }

    private static boolean nonblank(Object value) {
        return value instanceof String text && text.codePoints().anyMatch(point ->
                !(Character.isWhitespace(point) || Character.isSpaceChar(point) || point == 0x85));
    }
    private static boolean uuid(Object value) { return value instanceof String text && UUID.matcher(text).matches(); }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> object(Object value) { return (Map<String, Object>) value; }

    private static void checkDepth(int depth) {
        if (depth > MAX_JSON_DEPTH) throw new CodecException("JSON_TOO_DEEP", null, false, true);
    }

    private static void writeValue(JsonGenerator generator, Object value, int depth,
                                   IdentityHashMap<Object, Boolean> active) throws IOException {
        if (value == null) { generator.writeNull(); return; }
        if (value instanceof String text) { validUnicode(text); generator.writeString(text); return; }
        if (value instanceof Boolean bool) { generator.writeBoolean(bool); return; }
        if (value instanceof JsonNumber number) { generator.writeNumber(number.text()); return; }
        if (value instanceof Byte || value instanceof Short || value instanceof Integer || value instanceof Long
                || value instanceof BigInteger || value instanceof BigDecimal) {
            generator.writeNumber(value.toString()); return;
        }
        if (value instanceof Float number) {
            if (!Float.isFinite(number)) throw encodingError();
            generator.writeNumber(number); return;
        }
        if (value instanceof Double number) {
            if (!Double.isFinite(number)) throw encodingError();
            generator.writeNumber(number); return;
        }
        if (!(value instanceof Map<?, ?> || value instanceof List<?>)) throw encodingError();
        checkDepth(depth + 1);
        if (active.put(value, Boolean.TRUE) != null) throw encodingError();
        try {
            if (value instanceof Map<?, ?> map) {
                generator.writeStartObject();
                for (Map.Entry<?, ?> entry : map.entrySet()) {
                    if (!(entry.getKey() instanceof String key)) throw encodingError();
                    validUnicode(key);
                    generator.writeFieldName(key);
                    writeValue(generator, entry.getValue(), depth + 1, active);
                }
                generator.writeEndObject();
            } else {
                generator.writeStartArray();
                for (Object item : (List<?>) value) writeValue(generator, item, depth + 1, active);
                generator.writeEndArray();
            }
        } finally { active.remove(value); }
    }

    private static CodecException parseError() { return new CodecException("PARSE_ERROR", null, true, true); }
    private static CodecException invalidRequest(Long id) { return new CodecException("INVALID_REQUEST", id, true, true); }
    private static CodecException invalidParams(Long id) { return new CodecException("INVALID_PARAMS", id, true, false); }
    private static CodecException invalidResponse() { return new CodecException("INVALID_RESPONSE", null, false, true); }
    private static CodecException encodingError() { return new CodecException("ENCODING_ERROR", null, false, true); }

    private static final class BoundedOutput extends ByteArrayOutputStream {
        @Override public synchronized void write(int value) {
            if (count == MAX_FRAME_BYTES) throw new CodecException("FRAME_TOO_LARGE", null, false, true);
            super.write(value);
        }

        @Override public synchronized void write(byte[] bytes, int offset, int length) {
            if (length > MAX_FRAME_BYTES - count) throw new CodecException("FRAME_TOO_LARGE", null, false, true);
            super.write(bytes, offset, length);
        }
    }
}
