package dev.minebridge.players;

import dev.minebridge.protocol.CodecException;
import dev.minebridge.protocol.JsonRpcCodec;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.*;

class PlayerProtocolTest {
    static final String A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    static final String PLAYER = "{\"uuid\":\"" + A + "\",\"name\":\"Alice\",\"entityId\":5}";
    static void result(String method, String value) {
        JsonRpcCodec.decodeResponse(("{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":" + value + "}").getBytes(StandardCharsets.UTF_8), 1L, method);
    }
    @Test void playerAndListResultsRequireTypedUniqueIdentities() {
        assertDoesNotThrow(() -> result("players.get", "{\"player\":" + PLAYER + "}"));
        assertDoesNotThrow(() -> result("players.list", "{\"players\":[]}"));
        assertThrows(CodecException.class, () -> result("players.get", "{\"player\":" + PLAYER.replace("\"entityId\":5", "\"entityId\":-1") + "}"));
        assertThrows(CodecException.class, () -> result("players.list", "{\"players\":[" + PLAYER + "," + PLAYER.toUpperCase().replace("UUID", "uuid").replace("NAME", "name").replace("ENTITYID", "entityId") + "]}"));
    }
    @Test void locationRequiresExactFieldsAndFiniteNumbers() {
        String valid = "{\"location\":{\"world\":\"lesson\",\"x\":1.25,\"y\":70.5,\"z\":-2.125,\"yaw\":90,\"pitch\":0}}";
        assertDoesNotThrow(() -> result("players.getPos", valid));
        assertThrows(CodecException.class, () -> result("players.getPos", valid.replace("1.25", "1e999")));
        assertThrows(CodecException.class, () -> result("players.getPos", valid.replace(",\"pitch\":0", "")));
    }
    @Test void targetResultCountsOutcomesAndFailureReasonsMustAgree() {
        String valid = "{\"matched\":1,\"applied\":1,\"targets\":[{\"uuid\":\"" + A + "\",\"applied\":true,\"code\":null}]}";
        assertDoesNotThrow(() -> result("players.teleport", valid));
        assertThrows(CodecException.class, () -> result("players.teleport", valid.replace("\"matched\":1", "\"matched\":2")));
        assertThrows(CodecException.class, () -> result("players.teleport", valid.replace("\"applied\":1", "\"applied\":0")));
        assertThrows(CodecException.class, () -> result("players.teleport", valid.replace("true", "false")));
        assertThrows(CodecException.class, () -> result("players.teleport", valid.replace("null", "\"error\"")));
    }
    @Test void unicodeLimitUsesCodepointsAndPlayerGetDoesNotAcceptSelector() {
        String message = "\uD83D\uDE00".repeat(4096);
        assertDoesNotThrow(() -> JsonRpcCodec.decodeRequest(("{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"chat.post\",\"params\":{\"message\":\"" + message + "\"}}").getBytes(StandardCharsets.UTF_8)));
        assertThrows(CodecException.class, () -> JsonRpcCodec.decodeRequest(("{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"players.get\",\"params\":{\"world\":\"lesson\",\"executor\":null,\"target\":\"@a\"}}").getBytes(StandardCharsets.UTF_8)));
    }
}
