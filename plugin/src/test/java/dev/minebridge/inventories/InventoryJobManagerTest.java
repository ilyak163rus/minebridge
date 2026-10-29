package dev.minebridge.inventories;

import static dev.minebridge.inventories.InventoryServiceTest.*;

import static org.junit.jupiter.api.Assertions.*;

import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.protocol.Response;
import dev.minebridge.session.Session;

import org.junit.jupiter.api.Test;

import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

class InventoryJobManagerTest {
    static Request request(long id, String method, Map<String, Object> params) {
        byte[] frame =
                JsonRpcCodec.encodeFrame(
                        Map.of("jsonrpc", "2.0", "id", id, "method", method, "params", params));
        return JsonRpcCodec.decodeRequest(Arrays.copyOf(frame, frame.length - 1));
    }

    static Session session() {
        Session s = new Session(128, 128, () -> {});
        s.markReady();
        return s;
    }

    static Response response(Session session, long id, String method) {
        ByteBuffer head = session.reactorOutputHead();
        assertNotNull(head);
        byte[] payload = new byte[head.remaining() - 1];
        head.get(payload);
        head.get();
        session.reactorRemoveOutputHead(head);
        return JsonRpcCodec.decodeResponse(payload, id, method);
    }

    static void finish(Harness h) {
        for (int i = 0; i < 100 && h.jobs.activeJobs() != 0; i++) h.jobs.tick();
        assertEquals(0, h.jobs.activeJobs());
    }

    static Request ofBlock(long id) {
        return request(
                id,
                "inventories.ofBlock",
                InventoryService.map(
                        "world",
                        "lesson",
                        "destinationWorld",
                        null,
                        "position",
                        List.of(15, 80, 15),
                        "combined",
                        false));
    }

    static Request bulk(long id, int slot, int amount) {
        return request(
                id,
                "players.setItem",
                InventoryService.map(
                        "world",
                        "lesson",
                        "executor",
                        null,
                        "targets",
                        "@a",
                        "slot",
                        slot,
                        "item",
                        item("minecraft:diamond", amount)));
    }

    @Test
    void blockWaitsForAsyncCardinalChunksAndReleasesAllTickets() {
        Harness h = new Harness();
        h.world.loaded = false;
        Session session = session();
        h.jobs.submit(session, ofBlock(1), CONTEXT);
        assertTrue(session.hasActiveOperation());
        assertEquals(0, h.openedChests);
        assertEquals(3, h.world.loads);
        assertNull(session.reactorOutputHead());
        h.world.loaded = true;
        h.world.future.complete(true);
        finish(h);
        assertEquals(
                "chest",
                ((Map<?, ?>) response(session, 1, "inventories.ofBlock").result().get("inventory"))
                        .get("kind"));
        assertEquals(0, h.chunks.retainedChunks());
        assertEquals(3, h.world.adds);
        assertEquals(h.world.adds, h.world.removes);
        assertFalse(session.hasActiveOperation());
    }

    @Test
    void disconnectWhileChunksLoadDropsHandleAndNeverReadsOrMutatesWorld() {
        Harness h = new Harness();
        h.world.loaded = false;
        Session session = session();
        h.jobs.submit(session, ofBlock(1), CONTEXT);
        session.close();
        h.jobs.tick();
        assertEquals(0, h.jobs.activeJobs());
        assertEquals(0, h.chunks.retainedChunks());
        assertEquals(0, h.openedChests);
        h.world.loaded = true;
        h.world.future.complete(true);
        h.jobs.tick();
        assertEquals(0, h.openedChests);
    }

    @Test
    void oneNativeTicketCleanupFailureStillReleasesEveryLeaseAndDoesNotDuplicateAck() {
        Harness h = new Harness();
        h.world.failFirstRemove = true;
        Session session = session();
        h.jobs.submit(session, ofBlock(1), CONTEXT);
        finish(h);
        assertNotNull(response(session, 1, "inventories.ofBlock").result());
        assertNull(session.reactorOutputHead());
        assertFalse(session.hasActiveOperation());
        assertEquals(0, h.chunks.retainedChunks());
        assertEquals(3, h.world.removes);
    }

    @Test
    void failedAsyncLoadProducesTypedNotAppliedErrorAndReleasesLeases() {
        Harness h = new Harness();
        h.world.loaded = false;
        Session session = session();
        h.jobs.submit(session, ofBlock(1), CONTEXT);
        h.world.future.completeExceptionally(new IllegalStateException("secret"));
        finish(h);
        Response result = response(session, 1, "inventories.ofBlock");
        assertEquals("CHUNK_LOAD_FAILED", result.error().code());
        assertEquals("not-applied", result.error().outcome());
        assertEquals(0, h.chunks.retainedChunks());
        assertEquals(0, h.openedChests);
    }

    @Test
    void everyBulkTargetIsPrevalidatedBeforeFirstSetterAndSelectorResolvedOnce() {
        Harness h = new Harness();
        h.second.maximum = 1;
        Session session = session();
        h.jobs.submit(session, bulk(1, 0, 2), CONTEXT);
        finish(h);
        assertEquals("INVALID_ITEM_AMOUNT", response(session, 1, "players.setItem").error().code());
        assertEquals(1, h.selections);
        assertEquals(0, h.first.writes);
        assertEquals(0, h.second.writes);
    }

    @Test
    void logoutAfterBulkStartsIsPerUuidWithoutRollbackOrRetargeting() {
        Harness h = new Harness();
        h.first.afterWrite = () -> h.b.online = false;
        Session session = session();
        h.jobs.submit(session, bulk(1, 0, 1), CONTEXT);
        finish(h);
        var result = response(session, 1, "players.setItem").result();
        assertEquals("1", ((dev.minebridge.protocol.JsonNumber) result.get("applied")).text());
        var outcomes = (List<?>) result.get("targets");
        assertEquals("PLAYER_NOT_FOUND", ((Map<?, ?>) outcomes.get(1)).get("code"));
        assertEquals(1, h.first.writes);
        assertEquals(0, h.second.writes);
        assertEquals(1, h.selections);
    }

    @Test
    void playerReferenceRequiresExactlyOneOnlineUuidAndNoChunkLease() {
        Harness h = new Harness();
        Session session = session();
        h.jobs.submit(
                session,
                request(
                        1,
                        "inventories.ofPlayer",
                        InventoryService.map("world", "lesson", "executor", null, "targets", "@a")),
                CONTEXT);
        assertEquals("INVALID_TARGET", response(session, 1, "inventories.ofPlayer").error().code());
        h.jobs.submit(
                session,
                request(
                        2,
                        "inventories.ofPlayer",
                        InventoryService.map(
                                "world", "lesson", "executor", null, "targets", h.a.id.toString())),
                CONTEXT);
        finish(h);
        var ref =
                (Map<?, ?>) response(session, 2, "inventories.ofPlayer").result().get("inventory");
        assertEquals(h.a.id.toString(), ref.get("player"));
        assertEquals(0, h.chunks.retainedChunks());
    }

    @Test
    void emptyBulkSelectionStillValidatesPublicSlotAndNativeStackLimit() {
        Harness h = new Harness();
        h.selection.clear();
        Session session = session();
        assertEquals(
                "INVALID_SLOT",
                assertThrows(dev.minebridge.protocol.CodecException.class, () -> bulk(1, 36, 1))
                        .code());
        h.jobs.submit(session, bulk(2, 0, 1), CONTEXT);
        finish(h);
        assertEquals(
                "0",
                ((dev.minebridge.protocol.JsonNumber)
                                response(session, 2, "players.setItem").result().get("matched"))
                        .text());
    }
}
