package dev.minebridge.protocol;

import org.junit.jupiter.api.Test;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class EventNotificationTest {
    private static final String ID = "00000000-0000-4000-8000-000000000001";
    private static final String WORLD = "00000000-0000-4000-8000-000000000002";
    private static Map<String, Object> record() {
        return Map.of("eventId", ID, "serverEpoch", ID, "sequence", 1, "serverTick", 10,
                "eventType", "chat.message", "world", Map.of("uuid", WORLD, "name", "world", "key", "minecraft:overworld"),
                "data", Map.of("player", Map.of("uuid", ID, "name", "Alice", "entityId", 2),
                        "message", "hello", "cancelled", false, "truncated", false));
    }
    private static byte[] payload(Map<String, Object> value) {
        byte[] frame = JsonRpcCodec.encodeFrame(value);
        return java.util.Arrays.copyOf(frame, frame.length - 1);
    }
    private static Map<String, Object> envelope(String method, Map<String, Object> params) {
        return Map.of("jsonrpc", "2.0", "method", method, "params", params);
    }
    private static void invalid(Map<String, Object> value) {
        CodecException failure = assertThrows(CodecException.class, () -> JsonRpcCodec.decodeEventNotification(payload(value)));
        assertEquals("INVALID_RESPONSE", failure.code());
    }
    @Test void typedLiveSnapshotAndSeparateOverflowAreValidWithoutRequestId() {
        var event = envelope("events.event", Map.of("subscriptionId", ID, "deliverySequence", 1, "event", record()));
        assertEquals("events.event", JsonRpcCodec.decodeEventNotification(payload(event)).get("method"));
        var overflow = envelope("events.overflow", Map.of("subscriptionIds", List.of(ID), "source", "capture", "lostCount", 3));
        assertEquals("events.overflow", JsonRpcCodec.decodeEventNotification(payload(overflow)).get("method"));
    }
    @Test void notificationCannotPretendToBeRpcAndDeliveryCounterMustBePositiveSafeInteger() {
        var params = new LinkedHashMap<String, Object>(Map.of("subscriptionId", ID, "deliverySequence", 1, "event", record()));
        var withId = new LinkedHashMap<>(envelope("events.event", params)); withId.put("id", 1);
        invalid(withId);
        for (Object counter : List.of(0, -1, 1.0, true, 9007199254740992L)) {
            params.put("deliverySequence", counter); invalid(envelope("events.event", params));
        }
        invalid(envelope("future.notification", params));
    }
    @Test void overflowRejectsDuplicateUnknownSourceAndUnboundedSubscriptions() {
        invalid(envelope("events.overflow", Map.of("subscriptionIds", List.of(ID, ID), "source", "server", "lostCount", 1)));
        invalid(envelope("events.overflow", Map.of("subscriptionIds", List.of(), "source", "server", "lostCount", 1)));
        invalid(envelope("events.overflow", Map.of("subscriptionIds", List.of(ID), "source", "python", "lostCount", 1)));
        invalid(envelope("events.overflow", Map.of("subscriptionIds", List.of(ID), "source", "capture", "lostCount", -1)));
    }
    @Test void cancelledOrOversizeSnapshotIsRejected() {
        var event = new LinkedHashMap<>(record());
        event.put("data", Map.of("player", Map.of("uuid", ID, "name", "Alice", "entityId", 2),
                "message", "hello", "cancelled", true, "truncated", false));
        invalid(envelope("events.event", Map.of("subscriptionId", ID, "deliverySequence", 1, "event", event)));
        event.put("data", Map.of("player", Map.of("uuid", ID, "name", "Alice", "entityId", 2),
                "message", "a".repeat(4097), "cancelled", false, "truncated", true));
        invalid(envelope("events.event", Map.of("subscriptionId", ID, "deliverySequence", 1, "event", event)));
    }
    @Test void historyErrorEncodesOnlyWhitelistedDiagnosticDetails() {
        String encoded = new String(JsonRpcCodec.errorFrame(1L, "EVENT_HISTORY_LOST", "not-applied",
                Map.of("reason", "capture-overflow", "availableFrom", 2, "tail", 9,
                        "eventType", "chat.message", "token", "not-for-output")), StandardCharsets.UTF_8);
        assertTrue(encoded.contains("\"reason\":\"capture-overflow\""));
        assertTrue(encoded.contains("\"availableFrom\":2"));
        assertFalse(encoded.contains("not-for-output"));
        assertEquals("EVENT_HISTORY_LOST", JsonRpcCodec.decodeResponse(encoded.strip().getBytes(StandardCharsets.UTF_8),
                1L, "events.pollEvents").error().code());
    }
}
