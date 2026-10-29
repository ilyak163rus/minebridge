package dev.minebridge.protocol;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;
import com.fasterxml.jackson.core.StreamReadConstraints;
import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.core.exc.StreamConstraintsException;
import com.fasterxml.jackson.core.json.JsonWriteFeature;

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

/** Pure protocol 2.0 codec. It deliberately has no transport, session or Paper API. */
public final class JsonRpcCodec {
    public static final int MAX_FRAME_BYTES = 65_536;
    public static final int MAX_JSON_DEPTH = 16;
    public static final long MAX_REQUEST_ID = 9_007_199_254_740_991L;

    private static final Pattern INTEGER = Pattern.compile("-?(?:0|[1-9][0-9]*)");
    private static final Pattern BLOCK_KEY = Pattern.compile("[a-z0-9_.-]+:[a-z0-9/._-]+");
    private static final Pattern UUID = Pattern.compile("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}");
    private static final Set<String> EVENT_TYPES = Set.of("chat.message", "block.interact", "block.break", "block.place",
            "entity.attack", "entity.damage", "player.damage", "player.enter_lava", "player.join", "player.quit",
            "player.death", "player.respawn", "projectile.shot", "projectile.hit");
    private static final JsonFactory JSON = JsonFactory.builder()
            .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
            .enable(JsonWriteFeature.COMBINE_UNICODE_SURROGATES_IN_UTF8)
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
            Map.entry("-32024", "INVALID_BLOCK"), Map.entry("-32025", "UNSUPPORTED_FEATURE"),
            Map.entry("-32026", "REGION_BUSY"), Map.entry("-32027", "CHUNK_LOAD_FAILED"),
            Map.entry("-32028", "PLAYER_NOT_FOUND"), Map.entry("-32029", "INVALID_SELECTOR"),
            Map.entry("-32030", "MISSING_CONTEXT"), Map.entry("-32031", "INVALID_TARGET"),
            Map.entry("-32032", "CONTEXT_WORLD_MISMATCH"), Map.entry("-32033", "INVALID_ITEM"),
            Map.entry("-32034", "INVALID_EFFECT"), Map.entry("-32035", "INVALID_ENTITY_TYPE"),
            Map.entry("-32036", "UNSUPPORTED_ENTITY_TYPE"), Map.entry("-32037", "ENTITY_NOT_FOUND"),
            Map.entry("-32038", "INVALID_GAME_MODE"), Map.entry("-32039", "INVALID_GAME_RULE"),
            Map.entry("-32040", "INVALID_RULE_VALUE"), Map.entry("-32041", "INVALID_PLAYER_VALUE"),
            Map.entry("-32042", "INVALID_WEATHER"), Map.entry("-32043", "WORLD_CHANGE_REJECTED"),
            Map.entry("-32044", "INVALID_EVENT_TYPE"), Map.entry("-32045", "SUBSCRIPTION_NOT_FOUND"),
            Map.entry("-32046", "EVENT_HISTORY_LOST"), Map.entry("-32047", "EVENT_QUEUE_OVERFLOW"),
            Map.entry("-32048", "INVENTORY_NOT_FOUND"), Map.entry("-32049", "INVENTORY_CHANGED"),
            Map.entry("-32050", "INVALID_SLOT"), Map.entry("-32051", "INVALID_ITEM_AMOUNT"),
            Map.entry("-32052", "INVENTORY_WRITE_REJECTED"), Map.entry("-32053", "PEACEFUL_SPAWN_BLOCKED"));
    private static final List<String> COUNT_LIMITS = List.of("maxFrameBytes", "maxJsonDepth", "maxSessions",
            "maxQueuedRequests", "maxOutputFrames", "maxOperationsPerTick", "maxOperationsPerSessionPerTick");
    private static final List<String> TIME_LIMITS = List.of("handshakeTimeoutSeconds", "frameAssemblyTimeoutSeconds",
            "writeTimeoutSeconds", "executorBudgetMillis");

    private JsonRpcCodec() { }

    /** Builds only known error envelopes with a fixed, non-sensitive message. */
    public static byte[] errorFrame(Long id, String code, String outcome) {
        return errorFrame(id, code, outcome, Map.of());
    }

    public static byte[] errorFrame(Long id, String code, String outcome, Map<String, Object> details) {
        if (!("not-applied".equals(outcome) || "unknown".equals(outcome))) throw encodingError();
        String numeric = null;
        for (Map.Entry<String, String> entry : ERROR_CODES.entrySet()) {
            if (entry.getValue().equals(code)) { numeric = entry.getKey(); break; }
        }
        if (numeric == null || (id != null && (id <= 0 || id > MAX_REQUEST_ID))) throw encodingError();
        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("jsonrpc", "2.0");
        envelope.put("id", id);
        Map<String, Object> data = new LinkedHashMap<>(Map.of("code", code, "outcome", outcome));
        if ("EVENT_HISTORY_LOST".equals(code)) {
            Object reason = details.get("reason");
            if ("retention".equals(reason) || "capture-overflow".equals(reason)) data.put("reason", reason);
            for (String key : List.of("availableFrom", "tail")) {
                Object value = details.get(key);
                if (value instanceof Number number && number.longValue() >= 0 && number.longValue() <= MAX_REQUEST_ID)
                    data.put(key, number.longValue());
            }
            if (eventType(details.get("eventType"))) data.put("eventType", details.get("eventType"));
        }
        envelope.put("error", Map.of("code", new JsonNumber(numeric), "message", "Request rejected", "data", data));
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
            case "blocks.get" -> {
                requireKeys(request.params(), Set.of("world", "position"), request.id());
                validatePositionRequest(request.params(), request.id());
            }
            case "blocks.setRegion", "blocks.getRegion" -> validateRegionRequest(request);
            case "players.get", "players.list", "players.getPos", "players.teleport" -> validatePlayerRequest(request);
            case "players.giveItem", "effects.add", "entities.spawn" -> validateGameplayRequest(request);
            case "players.getGameMode", "players.setGameMode", "players.getHealth", "players.setHealth",
                    "players.getFoodLevel", "players.setFoodLevel", "effects.remove", "effects.clear" -> validateControlRequest(request);
            case "worlds.getTime", "worlds.setTime", "worlds.getWeather", "worlds.setWeather",
                    "worlds.getGameRule", "worlds.setGameRule" -> validateWorldRequest(request);
            case "events.subscribe", "events.unsubscribe", "events.pollEvents", "events.getRecent",
                    "events.clearPending" -> validateEventRequest(request);
            case "inventories.ofBlock", "inventories.ofPlayer", "inventories.getItem", "inventories.getContents",
                    "inventories.setItem", "inventories.clear", "players.setItem" -> validateSlotRequest(request);
            case "chat.post" -> {
                requireKeys(request.params(), Set.of("message"), request.id());
                if (!(request.params().get("message") instanceof String text) || text.isEmpty()
                        || text.codePointCount(0, text.length()) > 4096) throw invalidParams(request.id());
            }
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
            case "blocks.set", "blocks.setRegion", "chat.post" -> { if (!Boolean.TRUE.equals(value.get("applied"))) throw invalidResponse(); }
            case "blocks.get" -> validateBlockResult(value.get("block"));
            case "blocks.getRegion" -> {
                if (!(value.get("blocks") instanceof List<?> blocks) || blocks.size() > 64
                        || !positiveInteger(value.get("total"))
                        || !(value.get("nextOffset") == null || nonnegativeInteger(value.get("nextOffset")))) throw invalidResponse();
                for (Object item : blocks) {
                    if (!(item instanceof Map<?, ?> entry) || !(entry.get("position") instanceof List<?> position)
                            || position.size() != 3 || position.stream().anyMatch(coordinate -> !int32(coordinate))) throw invalidResponse();
                    validateBlockResult(entry.get("block"));
                }
            }
            case "system.hello" -> validateHelloResult(value);
            case "events.subscribe" -> {
                if (!value.keySet().equals(Set.of("subscriptionId", "eventType", "world"))
                        || !uuid(value.get("subscriptionId")) || !eventType(value.get("eventType"))
                        || !uuid(value.get("world"))) throw invalidResponse();
            }
            case "events.unsubscribe" -> {
                if (!value.keySet().equals(Set.of("subscriptionId", "unsubscribed"))
                        || !uuid(value.get("subscriptionId")) || !Boolean.TRUE.equals(value.get("unsubscribed"))) throw invalidResponse();
            }
            case "events.pollEvents", "events.getRecent" -> validateEventBatch(value, method.equals("events.getRecent"));
            case "events.clearPending" -> {
                if (!value.keySet().equals(Set.of("cursor"))) throw invalidResponse();
                validateCursorResult(value.get("cursor"));
            }
            case "players.get" -> {
                if (!value.keySet().equals(Set.of("player"))) throw invalidResponse();
                validatePlayerResult(value.get("player"));
            }
            case "players.list" -> {
                if (!value.keySet().equals(Set.of("players")) || !(value.get("players") instanceof List<?> values)) throw invalidResponse();
                java.util.HashSet<String> seen = new java.util.HashSet<>();
                for (Object player : values) {
                    validatePlayerResult(player);
                    if (!seen.add(((String) object(player).get("uuid")).toLowerCase(java.util.Locale.ROOT))) throw invalidResponse();
                }
            }
            case "players.getPos" -> validateLocationResult(value);
            case "players.teleport", "effects.add", "effects.remove", "effects.clear",
                    "players.setGameMode", "players.setHealth", "players.setFoodLevel", "players.setItem" -> validateTargetResult(value);
            case "players.getGameMode" -> {
                if (!value.keySet().equals(Set.of("mode")) || !(value.get("mode") instanceof String)
                        || !List.of("survival", "creative", "adventure", "spectator").contains(value.get("mode"))) throw invalidResponse();
            }
            case "players.getHealth" -> {
                if (!value.keySet().equals(Set.of("value")) || !finiteNumber(value.get("value"))
                        || Double.parseDouble(((JsonNumber) value.get("value")).text()) < 0) throw invalidResponse();
            }
            case "players.getFoodLevel" -> {
                if (!value.keySet().equals(Set.of("value")) || !range(value.get("value"), 0, 20)) throw invalidResponse();
            }
            case "worlds.getTime" -> {
                if (!value.keySet().equals(Set.of("time")) || !range(value.get("time"), 0, 23999)) throw invalidResponse();
            }
            case "worlds.getWeather" -> {
                if (!value.keySet().equals(Set.of("weather")) || !(value.get("weather") instanceof String)
                        || !List.of("clear", "rain", "thunder").contains(value.get("weather"))) throw invalidResponse();
            }
            case "worlds.getGameRule" -> {
                if (!value.keySet().equals(Set.of("rule", "value")) || !nonblank(value.get("rule"))
                        || ((String) value.get("rule")).codePointCount(0, ((String) value.get("rule")).length()) > 256
                        || !ruleValue(value.get("value"))) throw invalidResponse();
            }
            case "worlds.setTime", "worlds.setWeather", "worlds.setGameRule" -> {
                if (!value.keySet().equals(Set.of("applied")) || !Boolean.TRUE.equals(value.get("applied"))) throw invalidResponse();
            }
            case "players.giveItem" -> validateInventoryResult(value);
            case "inventories.ofBlock", "inventories.ofPlayer" -> {
                if (!value.keySet().equals(Set.of("inventory")) || !inventoryDescriptor(value.get("inventory"))) throw invalidResponse();
                boolean player = "player".equals(object(value.get("inventory")).get("kind"));
                if (player != method.equals("inventories.ofPlayer")) throw invalidResponse();
            }
            case "inventories.getItem" -> {
                if (!value.keySet().equals(Set.of("slot", "item")) || !slot(value.get("slot"), false, 54)) throw invalidResponse();
                validateItemView(value.get("item"));
            }
            case "inventories.setItem" -> {
                if (!value.keySet().equals(Set.of("applied", "slot", "previous", "current"))
                        || !Boolean.TRUE.equals(value.get("applied")) || !slot(value.get("slot"), false, 54)) throw invalidResponse();
                validateItemView(value.get("previous")); validateItemView(value.get("current"));
            }
            case "inventories.clear" -> {
                if (!value.keySet().equals(Set.of("applied", "slots")) || !Boolean.TRUE.equals(value.get("applied"))
                        || !slotList(value.get("slots"))) throw invalidResponse();
            }
            case "inventories.getContents" -> {
                if (!value.keySet().equals(Set.of("items", "nextOffset", "total"))
                        || !(integerEquals(value.get("total"), "27") || integerEquals(value.get("total"), "41") || integerEquals(value.get("total"), "54"))
                        || !(value.get("items") instanceof List<?> items) || items.isEmpty() || items.size() > sequence(value.get("total"))
                        || !(value.get("nextOffset") == null || range(value.get("nextOffset"), 1, (int) sequence(value.get("total")) - 1))) throw invalidResponse();
                java.util.HashSet<String> seen = new java.util.HashSet<>();
                boolean player = integerEquals(value.get("total"), "41");
                for (Object item : items) {
                    if (!(item instanceof Map<?, ?> row) || !row.keySet().equals(Set.of("slot", "item"))
                            || !slot(row.get("slot"), player, (int) sequence(value.get("total")))
                            || !player && row.get("slot") instanceof String
                            || !seen.add(slotKey(row.get("slot")))) throw invalidResponse();
                    validateItemView(row.get("item"));
                }
            }
            case "entities.spawn" -> {
                if (!value.keySet().equals(Set.of("entity")) || !(value.get("entity") instanceof Map<?, ?>)) throw invalidResponse();
                Map<String, Object> entity = object(value.get("entity"));
                if (!entity.keySet().equals(Set.of("uuid", "entityId", "key", "living")) || !uuid(entity.get("uuid"))
                        || !nonnegativeInteger(entity.get("entityId")) || !int32(entity.get("entityId"))
                        || !(entity.get("key") instanceof String key) || !BLOCK_KEY.matcher(key).matches()
                        || !(entity.get("living") instanceof Boolean)) throw invalidResponse();
            }
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
        requireKeys(params, params.containsKey("logging")
                ? Set.of("protocol", "token", "world", "coordinates", "logging")
                : Set.of("protocol", "token", "world", "coordinates"), id);
        if (params.containsKey("logging") && !(params.get("logging") instanceof Boolean)) throw invalidParams(id);
        if (!(params.get("protocol") instanceof Map<?, ?>)
                || !(params.get("token") == null || params.get("token") instanceof String)
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

    private static void validatePlayerRequest(Request request) {
        Map<String, Object> params = request.params(); Long id = request.id();
        boolean get = request.method().equals("players.get"), teleport = request.method().equals("players.teleport");
        requireKeys(params, get ? Set.of("world", "executor", "target")
                : teleport ? Set.of("world", "executor", "targets", "position", "destinationWorld")
                : Set.of("world", "executor", "targets"), id);
        if (!nonblank(params.get("world")) || !(params.get("executor") == null || uuid(params.get("executor")))) throw invalidParams(id);
        Object target = params.get(get ? "target" : "targets");
        if (target instanceof String text) {
            if (!nonblank(text) || text.codePointCount(0, text.length()) > 2048 || get && text.startsWith("@")) throw invalidParams(id);
        } else if (!get && target instanceof List<?> uuids) {
            if (uuids.size() > 1024 || uuids.stream().anyMatch(value -> !uuid(value))) throw invalidParams(id);
        } else throw invalidParams(id);
        if (teleport) {
            if (!(params.get("destinationWorld") == null || nonblank(params.get("destinationWorld")))
                    || !(params.get("position") instanceof List<?> position) || position.size() != 3
                    || position.stream().anyMatch(value -> !coordinate(value))) throw invalidParams(id);
        }
    }

    private static void validateControlRequest(Request request) {
        Map<String, Object> p = request.params(); Long id = request.id(); String method = request.method();
        java.util.HashSet<String> keys = new java.util.HashSet<>(Set.of("world", "executor", "targets"));
        if (method.equals("players.setGameMode")) keys.add("mode");
        if (method.equals("players.setHealth") || method.equals("players.setFoodLevel")) keys.add("value");
        if (method.equals("effects.remove")) keys.add("effect");
        requireKeys(p, keys, id);
        if (!nonblank(p.get("world")) || !(p.get("executor") == null || uuid(p.get("executor")))) throw invalidParams(id);
        Object targets = p.get("targets");
        if (targets instanceof String text) { if (!nonblank(text) || text.codePointCount(0, text.length()) > 2048) throw invalidParams(id); }
        else if (targets instanceof List<?> uuids) { if (uuids.size() > 1024 || uuids.stream().anyMatch(value -> !uuid(value))) throw invalidParams(id); }
        else throw invalidParams(id);
        if (keys.contains("mode")) {
            if (!(p.get("mode") instanceof String)) throw invalidParams(id);
            if (!List.of("survival", "creative", "adventure", "spectator").contains(p.get("mode"))) throw new CodecException("INVALID_GAME_MODE", id, true, false);
        }
        if (keys.contains("value")) {
            Object value = p.get("value");
            if (method.equals("players.setFoodLevel") ? !integer(value) : !(value instanceof JsonNumber)) throw invalidParams(id);
            boolean valid = method.equals("players.setFoodLevel") ? range(value, 0, 20)
                    : finiteNumber(value) && Double.parseDouble(((JsonNumber) value).text()) >= 0;
            if (!valid) throw new CodecException("INVALID_PLAYER_VALUE", id, true, false);
        }
        if (keys.contains("effect")) {
            if (!(p.get("effect") instanceof Map<?, ?>)) throw invalidParams(id);
            Map<String, Object> effect = object(p.get("effect")); requireKeys(effect, Set.of("key"), id);
            validateKey(effect.get("key"), "INVALID_EFFECT", id);
        }
    }

    private static void validateWorldRequest(Request request) {
        Map<String, Object> p = request.params(); Long id = request.id(); String method = request.method();
        java.util.HashSet<String> keys = new java.util.HashSet<>(Set.of("world"));
        if (method.equals("worlds.setTime")) keys.add("time");
        if (method.equals("worlds.setWeather")) keys.add("weather");
        if (method.endsWith("GameRule")) keys.add("rule");
        if (method.equals("worlds.setGameRule")) keys.add("value");
        requireKeys(p, keys, id);
        if (!nonblank(p.get("world"))) throw invalidParams(id);
        if (keys.contains("time") && !range(p.get("time"), 0, 23999)) throw invalidParams(id);
        if (keys.contains("weather")) {
            if (!(p.get("weather") instanceof String)) throw invalidParams(id);
            if (!List.of("clear", "rain", "thunder").contains(p.get("weather"))) throw new CodecException("INVALID_WEATHER", id, true, false);
        }
        if (keys.contains("rule") && (!nonblank(p.get("rule")) || ((String) p.get("rule")).codePointCount(0, ((String) p.get("rule")).length()) > 256)) throw invalidParams(id);
        if (keys.contains("value") && !ruleValue(p.get("value"))) throw new CodecException("INVALID_RULE_VALUE", id, true, false);
    }

    private static boolean ruleValue(Object value) { return value instanceof Boolean || int32(value); }

    private static final List<String> EQUIPMENT_SLOTS = List.of("head", "chest", "legs", "feet", "off_hand");
    private static boolean slot(Object value, boolean player, int size) {
        return value instanceof String text ? EQUIPMENT_SLOTS.contains(text)
                : range(value, 0, player ? 35 : size - 1);
    }
    private static String slotKey(Object value) {
        return value instanceof String text ? text : Long.toString(sequence(value));
    }
    private static boolean slotList(Object value) {
        if (!(value instanceof List<?> list) || list.isEmpty() || list.size() > 54) return false;
        java.util.HashSet<String> seen = new java.util.HashSet<>();
        for (Object item : list) if (!slot(item, false, 54) || !seen.add(slotKey(item))) return false;
        return true;
    }
    private static boolean samePosition(Object one, Object two) {
        List<?> a = (List<?>) one, b = (List<?>) two;
        for (int i = 0; i < 3; i++) if (sequence(a.get(i)) != sequence(b.get(i))) return false;
        return true;
    }
    private static boolean inventoryDescriptor(Object value) {
        if (!(value instanceof Map<?, ?> ref) || !(ref.get("kind") instanceof String kind)) return false;
        boolean player = kind.equals("player");
        int size;
        if (player) {
            if (!ref.keySet().equals(Set.of("kind", "player", "size", "slots")) || !uuid(ref.get("player")) || !integerEquals(ref.get("size"), "41")) return false;
            size = 41;
        } else if (kind.equals("chest")) {
            if (!ref.keySet().equals(Set.of("kind", "world", "position", "combined", "size", "slots", "layout"))
                    || !uuid(ref.get("world")) || !position(ref.get("position"), true) || !(ref.get("combined") instanceof Boolean combined)
                    || !(integerEquals(ref.get("size"), "27") || combined && integerEquals(ref.get("size"), "54"))) return false;
            size = (int) sequence(ref.get("size"));
            if (!(ref.get("layout") instanceof List<?> parts) || parts.size() != size / 27) return false;
            String material = null; boolean anchored = false; List<?> previousPosition = null;
            for (int index = 0; index < parts.size(); index++) {
                if (!(parts.get(index) instanceof Map<?, ?> part) || !part.keySet().equals(Set.of("position", "offset", "size", "key"))
                        || !position(part.get("position"), true) || !integerEquals(part.get("size"), "27")
                        || !integerEquals(part.get("offset"), Integer.toString(27 * index))
                        || !("minecraft:chest".equals(part.get("key")) || "minecraft:trapped_chest".equals(part.get("key")))) return false;
                if (material != null && !material.equals(part.get("key"))) return false;
                material = (String) part.get("key");
                if (samePosition(part.get("position"), ref.get("position"))) anchored = true;
                List<?> at = (List<?>) part.get("position");
                if (previousPosition != null && (sequence(at.get(1)) != sequence(previousPosition.get(1))
                        || Math.abs(sequence(at.get(0)) - sequence(previousPosition.get(0)))
                        + Math.abs(sequence(at.get(2)) - sequence(previousPosition.get(2))) != 1)) return false;
                previousPosition = at;
            }
            if (!anchored) return false;
        } else return false;
        if (!(ref.get("slots") instanceof List<?> slots) || slots.size() != size) return false;
        for (int index = 0; index < size; index++) {
            if (player && index >= 36) {
                if (!EQUIPMENT_SLOTS.get(index - 36).equals(slots.get(index))) return false;
            } else if (!integerEquals(slots.get(index), Integer.toString(index))) return false;
        }
        return true;
    }
    private static void validateItemView(Object value) {
        if (value == null) return;
        if (!(value instanceof Map<?, ?> item) || !item.keySet().equals(Set.of("key", "amount", "name", "lore", "hasAdditionalData", "truncated"))
                || !key(item.get("key")) || !range(item.get("amount"), 1, Integer.MAX_VALUE)
                || !(item.get("name") == null || boundedText(item.get("name"), 256))
                || !(item.get("hasAdditionalData") instanceof Boolean) || !(item.get("truncated") instanceof Boolean)) throw invalidResponse();
        if (item.get("lore") != null && (!(item.get("lore") instanceof List<?> lines) || lines.size() > 16
                || lines.stream().anyMatch(line -> !boundedText(line, 256)))) throw invalidResponse();
    }
    private static boolean boundedText(Object value, int maximum) {
        return value instanceof String text && text.codePointCount(0, text.length()) <= maximum;
    }
    private static void validateInventorySelection(Map<String, Object> p, Long id) {
        if (!nonblank(p.get("world")) || !(p.get("executor") == null || uuid(p.get("executor")))) throw invalidParams(id);
        Object targets = p.get("targets");
        if (targets instanceof String text) {
            if (!nonblank(text) || text.codePointCount(0, text.length()) > 2048) throw invalidParams(id);
        } else if (!(targets instanceof List<?> list) || list.size() > 1024 || list.stream().anyMatch(target -> !uuid(target))) throw invalidParams(id);
    }
    private static void requireSlot(Object value, boolean player, int size, Long id) {
        if (!(value instanceof String) && !integer(value)) throw invalidParams(id);
        if (!slot(value, player, size) || !player && value instanceof String) throw new CodecException("INVALID_SLOT", id, true, false);
    }
    private static void validateSlotRequest(Request request) {
        Map<String, Object> p = request.params(); Long id = request.id(); String method = request.method();
        if (method.equals("inventories.ofBlock")) {
            requireKeys(p, Set.of("world", "destinationWorld", "position", "combined"), id);
            if (!nonblank(p.get("world")) || !(p.get("destinationWorld") == null || nonblank(p.get("destinationWorld")))
                    || !position(p.get("position"), true) || !(p.get("combined") instanceof Boolean)) throw invalidParams(id);
        } else if (method.equals("inventories.ofPlayer")) {
            requireKeys(p, Set.of("world", "executor", "targets"), id); validateInventorySelection(p, id);
        } else if (method.equals("players.setItem")) {
            requireKeys(p, Set.of("world", "executor", "targets", "slot", "item"), id); validateInventorySelection(p, id);
            requireSlot(p.get("slot"), true, 41, id); validateItem(p.get("item"), id);
        } else {
            requireKeys(p, method.equals("inventories.getContents") ? Set.of("inventory", "offset", "limit")
                    : method.equals("inventories.setItem") ? Set.of("inventory", "slot", "item") : Set.of("inventory", "slot"), id);
            if (!inventoryDescriptor(p.get("inventory"))) throw invalidParams(id);
            Map<String, Object> ref = object(p.get("inventory")); int size = (int) sequence(ref.get("size"));
            if (method.equals("inventories.getContents")) {
                if (!range(p.get("offset"), 0, size - 1) || !range(p.get("limit"), 1, 54)) throw invalidParams(id);
            } else {
                if (!(method.equals("inventories.clear") && p.get("slot") == null))
                    requireSlot(p.get("slot"), "player".equals(ref.get("kind")), size, id);
                if (method.equals("inventories.setItem")) validateItem(p.get("item"), id);
            }
        }
    }

    private static void validateEventRequest(Request request) {
        Map<String, Object> p = request.params(); Long id = request.id();
        String method = request.method();
        if (method.equals("events.unsubscribe")) {
            requireKeys(p, Set.of("subscriptionId"), id);
            if (!uuid(p.get("subscriptionId"))) throw invalidParams(id);
            return;
        }
        if (method.equals("events.subscribe")) {
            var keys = new java.util.HashSet<>(Set.of("subscriptionId", "eventType", "world", "executor", "players"));
            if (p.containsKey("region")) keys.add("region");
            if (p.containsKey("blocks")) keys.add("blocks");
            requireKeys(p, keys, id);
            if (!uuid(p.get("subscriptionId")) || !(p.get("executor") == null || uuid(p.get("executor")))) throw invalidParams(id);
            Object players = p.get("players");
            if (players instanceof String text) {
                if (!nonblank(text) || text.codePointCount(0, text.length()) > 2048) throw invalidParams(id);
            } else if (players instanceof List<?> values) {
                if (values.size() > 1024 || values.stream().anyMatch(value -> !uuid(value))) throw invalidParams(id);
            } else if (players != null) throw invalidParams(id);
            if (p.containsKey("region")) {
                if (!(p.get("region") instanceof Map<?, ?> region) || !region.keySet().equals(Set.of("world", "min", "max"))
                        || !uuid(region.get("world")) || !position(region.get("min"), true) || !position(region.get("max"), true)) throw invalidParams(id);
                var min = (List<?>) region.get("min"); var max = (List<?>) region.get("max");
                for (int i = 0; i < 3; i++) if (sequence(min.get(i)) > sequence(max.get(i))) throw invalidParams(id);
                if (!(p.get("eventType") instanceof String type) || Set.of("chat.message", "player.join", "player.quit").contains(type)) throw invalidParams(id);
            }
            if (p.containsKey("blocks")) {
                if (!(p.get("blocks") instanceof List<?> blocks) || blocks.size() > 256
                        || blocks.stream().anyMatch(value -> !key(value)) || new java.util.HashSet<>(blocks).size() != blocks.size()
                        || !(p.get("eventType") instanceof String type)
                        || !Set.of("block.interact", "block.break", "block.place").contains(type)) throw invalidParams(id);
            }
        } else if (method.equals("events.clearPending")) {
            requireKeys(p, Set.of("eventType", "world"), id);
        } else {
            boolean recent = method.equals("events.getRecent");
            requireKeys(p, recent ? Set.of("eventType", "world", "cursor", "upperBound", "limit")
                    : Set.of("eventType", "world", "cursor", "limit"), id);
            if (!range(p.get("limit"), 1, 1000)) throw invalidParams(id);
            if (p.get("cursor") != null && !cursor(p.get("cursor"))) throw invalidParams(id);
            if (recent && (!(p.get("upperBound") == null || safeSequence(p.get("upperBound")))
                    || (p.get("cursor") == null) != (p.get("upperBound") == null))) throw invalidParams(id);
        }
        if (!nonblank(p.get("world"))) throw invalidParams(id);
        Object type = p.get("eventType");
        if (!(type instanceof String) && !(method.equals("events.clearPending") && type == null)) throw invalidParams(id);
        if (type != null && !eventType(type)) throw new CodecException("INVALID_EVENT_TYPE", id, true, false);
    }

    private static boolean safeSequence(Object value) {
        if (!nonnegativeInteger(value)) return false;
        String text = ((JsonNumber) value).text();
        return text.length() <= 16 && Long.parseLong(text) <= MAX_REQUEST_ID;
    }

    private static boolean cursor(Object value) {
        return value instanceof Map<?, ?> map && map.keySet().equals(Set.of("epoch", "world", "sequence"))
                && uuid(map.get("epoch")) && uuid(map.get("world")) && safeSequence(map.get("sequence"));
    }

    private static void validateCursorResult(Object value) {
        if (!cursor(value)) throw invalidResponse();
    }

    private static long sequence(Object value) { return Long.parseLong(((JsonNumber) value).text()); }

    private static boolean eventType(Object value) { return value instanceof String && EVENT_TYPES.contains(value); }
    private static boolean key(Object value) { return value instanceof String text && BLOCK_KEY.matcher(text).matches(); }
    private static boolean position(Object value, boolean block) {
        return value instanceof List<?> list && list.size() == 3
                && list.stream().allMatch(item -> block ? int32(item) : finiteNumber(item));
    }
    private static boolean eventWorld(Object value) {
        return value instanceof Map<?, ?> world && world.keySet().equals(Set.of("uuid", "name", "key"))
                && uuid(world.get("uuid")) && nonblank(world.get("name")) && key(world.get("key"));
    }
    private static boolean eventEntity(Object value, boolean nullable, boolean player) {
        if (value == null) return nullable;
        if (!(value instanceof Map<?, ?> entity) || !entity.keySet().equals(Set.of("uuid", "entityId", "key", "living", "name"))
                || !uuid(entity.get("uuid")) || !int32(entity.get("entityId")) || !nonnegativeInteger(entity.get("entityId"))
                || !key(entity.get("key")) || !(entity.get("living") instanceof Boolean)) return false;
        boolean isPlayer = "minecraft:player".equals(entity.get("key"));
        return (!player || isPlayer) && (isPlayer ? Boolean.TRUE.equals(entity.get("living")) && nonblank(entity.get("name")) : entity.get("name") == null);
    }
    private static boolean blockView(Object value) {
        if (value == null) return true;
        if (!(value instanceof Map<?, ?> block) || !block.keySet().equals(Set.of("position", "block")) || !position(block.get("position"), true)) return false;
        validateBlockResult(block.get("block")); return true;
    }
    private static boolean nullableKey(Object value) { return value == null || key(value); }
    private static boolean hand(Object value) { return "HAND".equals(value) || "OFF_HAND".equals(value); }
    private static boolean nonnegativeNumber(Object value) {
        return finiteNumber(value) && Double.parseDouble(((JsonNumber) value).text()) >= 0;
    }
    private static boolean nativeName(Object value) { return value instanceof String text && text.matches("[A-Z][A-Z0-9_]{0,63}"); }
    private static boolean face(Object value) { return value == null || nativeName(value); }

    private static void validateEventRecord(Object value) {
        if (!(value instanceof Map<?, ?> record) || !record.keySet().equals(Set.of("eventId", "serverEpoch", "sequence",
                "serverTick", "eventType", "world", "data")) || !uuid(record.get("eventId")) || !uuid(record.get("serverEpoch"))
                || !safeSequence(record.get("sequence")) || sequence(record.get("sequence")) < 1
                || !safeSequence(record.get("serverTick")) || !eventType(record.get("eventType"))
                || !eventWorld(record.get("world")) || !(record.get("data") instanceof Map<?, ?> data)) throw invalidResponse();
        validateEventData((String) record.get("eventType"), object(data));
    }

    private static void validateEventData(String type, Map<String, Object> d) {
        boolean valid = switch (type) {
            case "chat.message" -> d.keySet().equals(Set.of("player", "message", "cancelled", "truncated"))
                    && d.get("message") instanceof String message && message.codePointCount(0, message.length()) <= 4096
                    && Boolean.FALSE.equals(d.get("cancelled")) && d.get("truncated") instanceof Boolean;
            case "block.break", "block.place" -> d.keySet().equals(type.equals("block.break")
                    ? Set.of("player", "position", "block", "cancelled") : Set.of("player", "position", "block", "replacedBlock", "cancelled"))
                    && eventEntity(d.get("player"), false, true) && position(d.get("position"), true) && Boolean.FALSE.equals(d.get("cancelled"));
            case "block.interact" -> d.keySet().equals(Set.of("player", "position", "block", "face", "action", "hand", "item", "useInteractedBlock", "useItemInHand", "cancelled"))
                    && eventEntity(d.get("player"), false, true) && position(d.get("position"), true) && face(d.get("face"))
                    && ("LEFT_CLICK_BLOCK".equals(d.get("action")) || "RIGHT_CLICK_BLOCK".equals(d.get("action"))) && hand(d.get("hand"))
                    && nullableKey(d.get("item")) && resultFlag(d.get("useInteractedBlock")) && resultFlag(d.get("useItemInHand")) && d.get("cancelled") instanceof Boolean;
            case "entity.attack" -> d.keySet().equals(Set.of("player", "target", "willAttack", "cancelled"))
                    && eventEntity(d.get("player"), false, true) && eventEntity(d.get("target"), false, false)
                    && d.get("willAttack") instanceof Boolean && d.get("cancelled") instanceof Boolean;
            case "entity.damage", "player.damage" -> d.keySet().equals(Set.of("victim", "directSource", "causingEntity", "cause", "rawDamage", "finalDamage", "cancelled"))
                    && eventEntity(d.get("victim"), false, type.equals("player.damage")) && eventEntity(d.get("directSource"), true, false)
                    && eventEntity(d.get("causingEntity"), true, false) && nativeName(d.get("cause"))
                    && nonnegativeNumber(d.get("rawDamage")) && nonnegativeNumber(d.get("finalDamage")) && Boolean.FALSE.equals(d.get("cancelled"));
            case "player.join", "player.quit" -> d.keySet().equals(Set.of("player")) && eventEntity(d.get("player"), false, true);
            case "player.enter_lava", "player.death" -> d.keySet().equals(Set.of("player", "position"))
                    && eventEntity(d.get("player"), false, true) && position(d.get("position"), false);
            case "player.respawn" -> d.keySet().equals(Set.of("player", "reason", "respawnLocation"))
                    && eventEntity(d.get("player"), false, true) && nativeName(d.get("reason")) && eventLocation(d.get("respawnLocation"));
            case "projectile.shot" -> d.keySet().equals(Set.of("projectile", "shooter", "sourceBlock", "position", "velocity", "weapon", "hand", "force", "cancelled"))
                    && projectileBase(d) && position(d.get("velocity"), false) && nullableKey(d.get("weapon"))
                    && (d.get("hand") == null || hand(d.get("hand"))) && (d.get("force") == null || finiteNumber(d.get("force"))) && Boolean.FALSE.equals(d.get("cancelled"));
            case "projectile.hit" -> d.keySet().equals(Set.of("projectile", "shooter", "sourceBlock", "position", "hitEntity", "hitBlock", "hitFace", "cancelled"))
                    && projectileBase(d) && eventEntity(d.get("hitEntity"), true, false) && blockView(d.get("hitBlock"))
                    && face(d.get("hitFace")) && d.get("cancelled") instanceof Boolean;
            default -> false;
        };
        if (!valid) throw invalidResponse();
        if (type.equals("chat.message")) validatePlayerResult(d.get("player"));
        if (type.startsWith("block.")) {
            validateBlockResult(d.get("block"));
            if (type.equals("block.place")) validateBlockResult(d.get("replacedBlock"));
        }
    }
    private static boolean resultFlag(Object value) { return "DEFAULT".equals(value) || "ALLOW".equals(value) || "DENY".equals(value); }
    private static boolean projectileBase(Map<String, Object> d) {
        return eventEntity(d.get("projectile"), false, false) && eventEntity(d.get("shooter"), true, false)
                && blockView(d.get("sourceBlock")) && position(d.get("position"), false);
    }
    private static boolean eventLocation(Object value) {
        return value instanceof Map<?, ?> at && at.keySet().equals(Set.of("world", "position", "yaw", "pitch"))
                && eventWorld(at.get("world")) && position(at.get("position"), false) && finiteNumber(at.get("yaw")) && finiteNumber(at.get("pitch"));
    }

    private static void validateEventBatch(Map<String, Object> value, boolean recent) {
        if (!value.keySet().equals(recent ? Set.of("events", "nextCursor", "upperBound", "availableFrom", "hasMore", "sessionStart", "windowLimited")
                : Set.of("events", "nextCursor", "upperBound", "availableFrom", "hasMore"))
                || !(value.get("events") instanceof List<?> records) || records.size() > 1000
                || !cursor(value.get("nextCursor")) || !safeSequence(value.get("upperBound"))
                || !safeSequence(value.get("availableFrom")) || !(value.get("hasMore") instanceof Boolean more)) throw invalidResponse();
        Map<?, ?> next = (Map<?, ?>) value.get("nextCursor");
        long end = sequence(next.get("sequence")), upper = sequence(value.get("upperBound"));
        if (end > upper || more != (end < upper) || sequence(value.get("availableFrom")) > upper + 1) throw invalidResponse();
        if (recent && (!safeSequence(value.get("sessionStart")) || sequence(value.get("sessionStart")) > upper
                || !(value.get("windowLimited") instanceof Boolean))) throw invalidResponse();
        long previous = 0;
        for (Object item : records) {
            validateEventRecord(item);
            Map<?, ?> record = (Map<?, ?>) item;
            long number = sequence(record.get("sequence"));
            if (number <= previous || number > end || !record.get("serverEpoch").equals(next.get("epoch"))
                    || !((Map<?, ?>) record.get("world")).get("uuid").equals(next.get("world"))) throw invalidResponse();
            previous = number;
        }
    }

    /** Pure validation for server notifications; useful for cross-runtime fixtures. */
    public static Map<String, Object> decodeEventNotification(byte[] payload) {
        Object root = parse(payload);
        if (!(root instanceof Map<?, ?> envelope) || !envelope.keySet().equals(Set.of("jsonrpc", "method", "params"))
                || !"2.0".equals(envelope.get("jsonrpc")) || !(envelope.get("params") instanceof Map<?, ?> params)) throw invalidResponse();
        if ("events.event".equals(envelope.get("method"))) {
            if (!params.keySet().equals(Set.of("subscriptionId", "deliverySequence", "event")) || !uuid(params.get("subscriptionId"))
                    || !safeSequence(params.get("deliverySequence")) || sequence(params.get("deliverySequence")) < 1) throw invalidResponse();
            validateEventRecord(params.get("event"));
        } else if ("events.overflow".equals(envelope.get("method"))) {
            if (!params.keySet().equals(Set.of("subscriptionIds", "source", "lostCount"))
                    || !(params.get("subscriptionIds") instanceof List<?> ids) || ids.isEmpty() || ids.size() > 32
                    || ids.stream().anyMatch(id -> !uuid(id)) || new java.util.HashSet<>(ids).size() != ids.size()
                    || !("server".equals(params.get("source")) || "capture".equals(params.get("source")))
                    || !safeSequence(params.get("lostCount"))) throw invalidResponse();
        } else throw invalidResponse();
        return object(root);
    }

    private static boolean coordinate(Object value) {
        if (!(value instanceof JsonNumber number)) return false;
        double parsed = Double.parseDouble(number.text());
        return Double.isFinite(parsed) && parsed >= Integer.MIN_VALUE && parsed <= Integer.MAX_VALUE;
    }

    private static void validateGameplayRequest(Request request) {
        Map<String, Object> p = request.params(); Long id = request.id();
        boolean give = request.method().equals("players.giveItem"), spawn = request.method().equals("entities.spawn");
        requireKeys(p, give ? Set.of("world", "executor", "targets", "item", "overflow")
                : spawn ? Set.of("world", "destinationWorld", "position", "entity", "options")
                : Set.of("world", "executor", "targets", "effect"), id);
        if (!nonblank(p.get("world"))) throw invalidParams(id);
        if (!spawn) {
            if (!(p.get("executor") == null || uuid(p.get("executor")))) throw invalidParams(id);
            Object targets = p.get("targets");
            if (targets instanceof String text) { if (!nonblank(text) || text.codePointCount(0, text.length()) > 2048) throw invalidParams(id); }
            else if (targets instanceof List<?> uuids) { if (uuids.size() > 1024 || uuids.stream().anyMatch(value -> !uuid(value))) throw invalidParams(id); }
            else throw invalidParams(id);
        }
        if (give) {
            validateItem(p.get("item"), id);
            if (!("return".equals(p.get("overflow")) || "drop".equals(p.get("overflow")))) throw invalidParams(id);
        } else if (!spawn) {
            if (!(p.get("effect") instanceof Map<?, ?>)) throw invalidParams(id);
            Map<String, Object> effect = object(p.get("effect")); requireKeys(effect, Set.of("key", "durationTicks", "level", "particles"), id);
            validateKey(effect.get("key"), "INVALID_EFFECT", id);
            if (!range(effect.get("durationTicks"), 1, Integer.MAX_VALUE) || !range(effect.get("level"), 1, 256)
                    || !(effect.get("particles") instanceof Boolean)) throw invalidParams(id);
        } else {
            if (!(p.get("destinationWorld") == null || nonblank(p.get("destinationWorld")))
                    || !(p.get("position") instanceof List<?> position) || position.size() != 3
                    || position.stream().anyMatch(value -> !coordinate(value)) || !(p.get("entity") instanceof Map<?, ?>)
                    || !(p.get("options") instanceof Map<?, ?>)) throw invalidParams(id);
            Map<String, Object> entity = object(p.get("entity")); requireKeys(entity, Set.of("key"), id);
            validateKey(entity.get("key"), "INVALID_ENTITY_TYPE", id);
            Map<String, Object> options = object(p.get("options")); requireKeys(options, Set.of("item", "block", "face", "owner"), id);
            if (options.get("item") != null) validateItem(options.get("item"), id);
            if (options.get("block") != null) validateBlockSpecification(options.get("block"), id);
            if (!(options.get("face") == null || List.of("north", "south", "east", "west", "up", "down").contains(options.get("face")))) throw invalidParams(id);
            if (options.get("owner") != null && (!(options.get("owner") instanceof String text) || !nonblank(text)
                    || text.startsWith("@") || text.codePointCount(0, text.length()) > 2048)) throw invalidParams(id);
        }
    }
    private static void validateKey(Object value, String code, Long id) {
        if (!(value instanceof String key)) throw invalidParams(id);
        if (!BLOCK_KEY.matcher(key).matches()) throw new CodecException(code, id, true, false);
    }
    private static boolean range(Object value, int minimum, int maximum) {
        if (!int32(value)) return false;
        int amount = Integer.parseInt(((JsonNumber) value).text()); return amount >= minimum && amount <= maximum;
    }
    private static void validateItem(Object value, Long id) {
        if (!(value instanceof Map<?, ?>)) throw invalidParams(id);
        Map<String, Object> item = object(value); requireKeys(item, Set.of("key", "amount", "name", "lore"), id);
        validateKey(item.get("key"), "INVALID_ITEM", id);
        if (!range(item.get("amount"), 1, 2304) || !(item.get("name") == null || item.get("name") instanceof String text && text.codePointCount(0, text.length()) <= 256)) throw invalidParams(id);
        if (item.get("lore") != null && (!(item.get("lore") instanceof List<?> lore) || lore.size() > 16
                || lore.stream().anyMatch(line -> !(line instanceof String text) || text.codePointCount(0, text.length()) > 256))) throw invalidParams(id);
    }
    private static void validateInventoryResult(Map<String, Object> result) {
        if (!result.keySet().equals(Set.of("matched", "applied", "targets")) || !(result.get("targets") instanceof List<?> targets)
                || !integerEquals(result.get("matched"), Integer.toString(targets.size()))) throw invalidResponse();
        int applied = 0; java.util.HashSet<String> seen = new java.util.HashSet<>();
        for (Object value : targets) {
            if (!(value instanceof Map<?, ?>)) throw invalidResponse(); Map<String, Object> row = object(value);
            if (!row.keySet().equals(Set.of("uuid", "applied", "code", "requested", "given", "leftovers", "dropped"))
                    || !uuid(row.get("uuid")) || !seen.add(((String) row.get("uuid")).toLowerCase(java.util.Locale.ROOT))
                    || !(row.get("applied") instanceof Boolean success) || (success ? row.get("code") != null : !nonblank(row.get("code")))
                    || !range(row.get("requested"), 1, 2304) || !range(row.get("given"), 0, 2304) || !range(row.get("dropped"), 0, 2304)
                    || !(row.get("leftovers") instanceof List<?> leftovers)) throw invalidResponse();
            int total = Integer.parseInt(((JsonNumber) row.get("given")).text()) + Integer.parseInt(((JsonNumber) row.get("dropped")).text());
            for (Object rest : leftovers) {
                try { validateItem(rest, null); } catch (CodecException failure) { throw invalidResponse(); }
                total += Integer.parseInt(((JsonNumber) object(rest).get("amount")).text());
            }
            if (!integerEquals(row.get("requested"), Integer.toString(total))) throw invalidResponse();
            if (success) applied++;
        }
        if (!integerEquals(result.get("applied"), Integer.toString(applied))) throw invalidResponse();
    }
    private static boolean finiteNumber(Object value) {
        return value instanceof JsonNumber number && Double.isFinite(Double.parseDouble(number.text()));
    }
    private static void validatePlayerResult(Object value) {
        if (!(value instanceof Map<?, ?>)) throw invalidResponse();
        Map<String, Object> player = object(value);
        if (!player.keySet().equals(Set.of("uuid", "name", "entityId")) || !uuid(player.get("uuid"))
                || !nonblank(player.get("name")) || !int32(player.get("entityId"))
                || !nonnegativeInteger(player.get("entityId"))) throw invalidResponse();
    }
    private static void validateLocationResult(Map<String, Object> result) {
        if (!result.keySet().equals(Set.of("location")) || !(result.get("location") instanceof Map<?, ?>)) throw invalidResponse();
        Map<String, Object> at = object(result.get("location"));
        if (!at.keySet().equals(Set.of("world", "x", "y", "z", "yaw", "pitch")) || !nonblank(at.get("world"))) throw invalidResponse();
        for (String axis : List.of("x", "y", "z", "yaw", "pitch")) if (!finiteNumber(at.get(axis))) throw invalidResponse();
    }
    private static void validateTargetResult(Map<String, Object> result) {
        if (!result.keySet().equals(Set.of("matched", "applied", "targets")) || !nonnegativeInteger(result.get("matched"))
                || !nonnegativeInteger(result.get("applied")) || !(result.get("targets") instanceof List<?> targets)) throw invalidResponse();
        if (!integerEquals(result.get("matched"), Integer.toString(targets.size()))) throw invalidResponse();
        int applied = 0; java.util.HashSet<String> seen = new java.util.HashSet<>();
        for (Object value : targets) {
            if (!(value instanceof Map<?, ?>)) throw invalidResponse();
            Map<String, Object> target = object(value);
            if (!target.keySet().equals(Set.of("uuid", "applied", "code")) || !uuid(target.get("uuid"))
                    || !seen.add(((String) target.get("uuid")).toLowerCase(java.util.Locale.ROOT)) || !(target.get("applied") instanceof Boolean success)
                    || (success ? target.get("code") != null : !nonblank(target.get("code")))) throw invalidResponse();
            if ((Boolean) target.get("applied")) applied++;
        }
        if (!integerEquals(result.get("applied"), Integer.toString(applied))) throw invalidResponse();
    }

    private static void validateBlockRequest(Map<String, Object> params, Long id) {
        requireKeys(params, Set.of("world", "position", "block"), id);
        validatePositionRequest(params, id);
        validateBlockSpecification(params.get("block"), id);
    }

    private static void validatePositionRequest(Map<String, Object> params, Long id) {
        if (!(params.get("world") instanceof String) || !(params.get("position") instanceof List<?> position)
                || position.size() != 3) throw invalidParams(id);
        for (Object coordinate : (List<?>) params.get("position")) {
            if (!int32(coordinate)) throw invalidParams(id);
        }
    }

    private static void validateRegionRequest(Request request) {
        Map<String, Object> params = request.params();
        Long id = request.id();
        boolean mutation = "blocks.setRegion".equals(request.method());
        requireKeys(params, mutation ? Set.of("world", "from", "to", "block")
                : Set.of("world", "from", "to", "offset", "limit"), id);
        if (!(params.get("world") instanceof String)) throw invalidParams(id);
        for (String corner : List.of("from", "to")) {
            if (!(params.get(corner) instanceof List<?> position) || position.size() != 3
                    || position.stream().anyMatch(coordinate -> !int32(coordinate))) throw invalidParams(id);
        }
        if (mutation) validateBlockSpecification(params.get("block"), id);
        else {
            if (!int32(params.get("offset")) || !nonnegativeInteger(params.get("offset"))
                    || !int32(params.get("limit")) || !positiveInteger(params.get("limit"))
                    || Integer.parseInt(((JsonNumber) params.get("limit")).text()) > 64) throw invalidParams(id);
        }
    }

    private static void validateBlockSpecification(Object value, Long id) {
        if (!(value instanceof Map<?, ?>)) throw invalidParams(id);
        Map<String, Object> block = object(value);
        requireKeys(block, Set.of("key", "states"), id);
        if (!(block.get("key") instanceof String key) || !(block.get("states") instanceof Map<?, ?>)) {
            throw invalidParams(id);
        }
        if (!BLOCK_KEY.matcher((String) block.get("key")).matches()) {
            throw new CodecException("INVALID_BLOCK", id, true, false);
        }
        Map<String, Object> states = object(block.get("states"));
        if (states.size() > 64) throw new CodecException("INVALID_BLOCK", id, true, false);
        for (Map.Entry<String, Object> state : states.entrySet()) {
            if (!state.getKey().matches("[a-z0-9_]{1,64}") || !(state.getValue() instanceof String text)
                    || !text.matches("[a-z0-9_-]{1,128}")) throw new CodecException("INVALID_BLOCK", id, true, false);
        }
    }

    private static void validateBlockResult(Object value) {
        try { validateBlockSpecification(value, null); }
        catch (CodecException failure) { throw invalidResponse(); }
    }

    private static void validateHelloResult(Map<String, Object> result) {
        if (!(result.get("protocol") instanceof Map<?, ?>) || !(result.get("world") instanceof Map<?, ?>)
                || !(result.get("limits") instanceof Map<?, ?>) || !uuid(result.get("sessionId"))
                || !nonblank(result.get("pluginVersion")) || !nonblank(result.get("serverVersion"))
                || !"absolute".equals(result.get("coordinates"))
                || !("loaded-only".equals(result.get("chunkPolicy")) || "load-generate".equals(result.get("chunkPolicy")))
                || !Boolean.TRUE.equals(result.get("applyPhysics"))
                || !(result.get("capabilities") instanceof List<?>)) throw invalidResponse();
        Map<String, Object> protocol = object(result.get("protocol"));
        if (!integerEquals(protocol.get("major"), "2") || !integerEquals(protocol.get("minor"), "0")) {
            throw invalidResponse();
        }
        Map<String, Object> world = object(result.get("world"));
        if (!nonblank(world.get("name")) || !(world.get("key") instanceof String key)
                || !BLOCK_KEY.matcher(key).matches() || !uuid(world.get("uuid"))
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
        if (result.containsKey("eventHistory")) {
            if (!(result.get("eventHistory") instanceof Map<?, ?> history)
                    || !history.keySet().equals(Set.of("epoch", "world", "startSequence", "retention", "maxSubscriptions", "maxLiveEvents"))
                    || !uuid(history.get("epoch")) || !world.get("uuid").equals(history.get("world"))
                    || !safeSequence(history.get("startSequence")) || !range(history.get("maxSubscriptions"), 1, 32)
                    || !range(history.get("maxLiveEvents"), 1, 512) || !(history.get("retention") instanceof Map<?, ?> retention)
                    || !retention.keySet().equals(Set.of("maxRecords", "maxBytes", "maxAgeTicks"))
                    || !range(retention.get("maxRecords"), 1, 4096) || !range(retention.get("maxBytes"), 1, 4194304)
                    || !range(retention.get("maxAgeTicks"), 1, 2400)) throw invalidResponse();
        }
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
