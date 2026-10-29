package dev.minebridge.players;

import dev.minebridge.blocks.ChunkService;
import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.protocol.Response;
import dev.minebridge.session.Session;
import dev.minebridge.transport.TransportLimits;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Arrays;
import java.util.concurrent.CompletableFuture;

import static org.junit.jupiter.api.Assertions.*;

class PlayerJobManagerTest {
    static Session session() { Session session = new Session(128, 128, () -> {}); session.markReady(); return session; }
    static Request request(long id, String method, String targets, String position) {
        String params = "{\"world\":\"lesson\",\"executor\":null,\"targets\":" + targets
                + (position == null ? "" : ",\"position\":" + position + ",\"destinationWorld\":null") + "}";
        return JsonRpcCodec.decodeRequest(("{\"jsonrpc\":\"2.0\",\"id\":" + id + ",\"method\":\"" + method + "\",\"params\":" + params + "}").getBytes(StandardCharsets.UTF_8));
    }
    static Response response(Session session, long id, String method) {
        java.nio.ByteBuffer head = session.reactorOutputHead(); assertNotNull(head);
        byte[] frame = new byte[head.remaining() - 1]; head.get(frame); head.get(); session.reactorRemoveOutputHead(head);
        return JsonRpcCodec.decodeResponse(frame, id, method);
    }
    @Test void asyncTeleportHoldsFifoUntilActualCompletionAndSharesTicketReferences() {
        PlayerServiceTest.Harness h = new PlayerServiceTest.Harness(); ChunkService chunks = new ChunkService();
        PlayerJobManager jobs = new PlayerJobManager(h.service, chunks); Session a = session(), b = session();
        h.a.pending = new CompletableFuture<>(); h.b.pending = new CompletableFuture<>();
        jobs.submit(a, request(1, "players.teleport", "\"Alpha\"", "[12.25,80.5,-20.75]"), PlayerServiceTest.CONTEXT);
        jobs.submit(b, request(1, "players.teleport", "\"Beta\"", "[12.25,80.5,-20.75]"), PlayerServiceTest.CONTEXT);
        assertTrue(a.hasActiveOperation()); assertTrue(b.hasActiveOperation()); assertEquals(1, h.world.tickets); assertEquals(1, chunks.retainedChunks());
        h.a.pending.complete(true); jobs.tick();
        assertFalse(a.hasActiveOperation()); assertTrue(b.hasActiveOperation()); assertEquals(1, h.world.tickets);
        assertEquals("1", ((dev.minebridge.protocol.JsonNumber) response(a, 1, "players.teleport").result().get("applied")).text());
        h.b.pending.complete(false); jobs.tick();
        Response result = response(b, 1, "players.teleport"); assertNull(result.error());
        assertEquals(0, h.world.tickets); assertEquals(0, chunks.retainedChunks()); assertEquals(0, jobs.activeJobs());
        assertEquals(12.25, h.a.x); assertEquals(80.5, h.a.y); assertEquals(-20.75, h.a.z);
    }
    @Test void validationBeforeAnyMutationAndEmptyGroupProducesZero() {
        PlayerServiceTest.Harness h = new PlayerServiceTest.Harness(); ChunkService chunks = new ChunkService();
        PlayerJobManager jobs = new PlayerJobManager(h.service, chunks); Session a = session();
        jobs.submit(a, request(1, "players.teleport", "[\"" + h.a.uuid + "\",\"" + java.util.UUID.randomUUID() + "\"]", "[1,70,1]"), PlayerServiceTest.CONTEXT);
        assertEquals("PLAYER_NOT_FOUND", response(a, 1, "players.teleport").error().code()); assertEquals(0, h.a.teleports);
        jobs.submit(a, request(2, "players.teleport", "[]", "[1,70,1]"), PlayerServiceTest.CONTEXT);
        assertNull(response(a, 2, "players.teleport").error()); assertEquals(0, h.world.tickets);
    }
    @Test void disconnectBeforeChunkCompletionNeverTeleportsOrAddsLateTicket() {
        PlayerServiceTest.Harness h = new PlayerServiceTest.Harness(); h.world.loaded = false;
        ChunkService chunks = new ChunkService(); PlayerJobManager jobs = new PlayerJobManager(h.service, chunks); Session session = session();
        jobs.submit(session, request(1, "players.teleport", "\"Alpha\"", "[16000,80,16000]"), PlayerServiceTest.CONTEXT);
        assertEquals(1, h.world.loads); assertEquals(0, h.a.teleports);
        session.close(); jobs.tick(); h.world.loaded = true; h.world.loading.complete(true); jobs.tick();
        assertEquals(0, h.a.teleports); assertEquals(0, h.world.tickets); assertEquals(0, chunks.retainedChunks());
    }
    @Test void shutdownReleasesTicketAndDoesNotWaitForPendingTeleports() {
        PlayerServiceTest.Harness h = new PlayerServiceTest.Harness(); h.a.pending = new CompletableFuture<>();
        ChunkService chunks = new ChunkService(); PlayerJobManager jobs = new PlayerJobManager(h.service, chunks); Session session = session();
        jobs.submit(session, request(1, "players.teleport", "\"Alpha\"", "[10,80,10]"), PlayerServiceTest.CONTEXT);
        assertEquals(1, h.world.tickets);
        assertTimeout(Duration.ofMillis(200), jobs::close);
        assertEquals(0, h.world.tickets); assertFalse(session.hasActiveOperation()); assertFalse(h.a.pending.isDone());
        h.a.pending.complete(true); jobs.tick(); assertNull(session.reactorOutputHead());
    }
}
