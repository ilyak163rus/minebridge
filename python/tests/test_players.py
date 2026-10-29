"""Player facade behavior against controlled TCP peers; Paper resolves actual selectors."""

from dataclasses import FrozenInstanceError
import threading
import unittest
from unittest import mock
from uuid import UUID

from minebridge import Minecraft, errors, selector
from minebridge._protocol import encode_frame
from minebridge.models import EntityRef, LivingEntityRef, Location, PlayerRef, TargetOutcome, TargetResult
from test_client import send_hello
from test_transport import peer, read_request


ALICE = {"uuid": "00000000-0000-0000-0000-000000000001", "name": "Alice", "entityId": 17}
BOB = {"uuid": "00000000-0000-0000-0000-000000000002", "name": "Bob", "entityId": 21}


def respond(connection, request, value):
    connection.sendall(encode_frame({"jsonrpc": "2.0", "id": request["id"], "result": value}))


def serve(requests, answer):
    def handler(connection, stopping):
        hello = read_request(connection)
        requests.append(hello)
        send_hello(connection, hello)
        while not stopping.is_set():
            request = read_request(connection)
            if request is None:
                return
            requests.append(request)
            respond(connection, request, answer(request))
    return handler


class PlayerApiTests(unittest.TestCase):
    def connect(self, server, **options):
        options.setdefault("timeout", 1)
        return Minecraft.create("127.0.0.1", server.port, **options)

    def test_selector_catalog_and_references_are_typed_frozen_values(self):
        self.assertEqual([str(getattr(selector, name)) for name in (
            "ALL_PLAYERS", "RANDOM_PLAYER", "NEAREST_PLAYER", "SELF", "ALL_ENTITIES")],
            ["@a", "@r", "@p", "@s", "@e"])
        self.assertEqual(str(selector.Selector('@a[tag="lesson"]')), '@a[tag="lesson"]')
        player = PlayerRef(UUID(ALICE["uuid"]), ALICE["entityId"], ALICE["name"])
        self.assertIsInstance(player, LivingEntityRef)
        self.assertIsInstance(player, EntityRef)
        self.assertEqual(player.key, "minecraft:player")
        with self.assertRaises(FrozenInstanceError):
            player.name = "Bob"
        with self.assertRaises(FrozenInstanceError):
            selector.SELF.expression = "@a"

    def test_create_validates_optional_current_name_before_dns(self):
        with mock.patch("socket.getaddrinfo") as resolver:
            for invalid in ("", "has space", "x" * 17, "@s", "Алиса", ALICE["uuid"]):
                with self.subTest(player=invalid), self.assertRaises(ValueError):
                    Minecraft.create(player=invalid)
            for invalid in (True, 7, UUID(ALICE["uuid"])):
                with self.subTest(player=invalid), self.assertRaises(TypeError):
                    Minecraft.create(player=invalid)
            resolver.assert_not_called()

    def test_player_binding_is_uuid_based_and_root_id_lookup_does_not_rebind(self):
        requests = []

        def answer(request):
            if request["method"] == "players.get":
                return {"player": BOB if request["params"]["target"] == "Bob" else ALICE}
            return {"players": [ALICE]}

        with peer(serve(requests, answer)) as server:
            original = self.connect(server, player="Alice")
            try:
                self.assertEqual(original.getPlayerEntityId("Bob"), 21)
                other = original.withContext(player="Bob")
                self.assertEqual(original.players.list(selector.SELF)[0].name, "Alice")
                other.players.list(selector.SELF)
                original.withContext().players.list()
                self.assertEqual([row["method"] for row in requests], [
                    "system.hello", "players.get", "players.get", "players.get",
                    "players.list", "players.list", "players.list"])
                self.assertEqual(requests[1]["params"], {
                    "world": "lesson-world", "executor": None, "target": "Alice"})
                self.assertEqual(requests[4]["params"]["executor"], ALICE["uuid"])
                self.assertEqual(requests[5]["params"]["executor"], BOB["uuid"])
                self.assertEqual(requests[6]["params"], {
                    "world": "lesson-world", "executor": None, "targets": "@a"})
                other.close()
                original.close()
                other.close()
                with self.assertRaises(errors.ConnectionError):
                    original.players.list()
            finally:
                original.close()

    def test_positions_keep_fractions_and_teleport_returns_partial_outcomes(self):
        requests = []
        location = {"world": "other-world", "x": -0.25, "y": 80.5, "z": 12,
                    "yaw": 123.75, "pitch": -45.5}
        outcomes = {"matched": 2, "applied": 1, "targets": [
            {"uuid": ALICE["uuid"], "applied": True, "code": None},
            {"uuid": BOB["uuid"], "applied": False, "code": "PLAYER_NOT_FOUND"}]}

        def answer(request):
            if request["method"] == "players.getPos":
                return {"location": location}
            if not request["params"]["targets"]:
                return {"matched": 0, "applied": 0, "targets": []}
            return outcomes

        with peer(serve(requests, answer)) as server:
            client = self.connect(server)
            try:
                self.assertEqual(client.players.getPos(UUID(ALICE["uuid"])),
                                 Location(**location))
                players = [PlayerRef(UUID(value["uuid"]), value["entityId"], value["name"])
                           for value in (ALICE, BOB)]
                self.assertEqual(client.players.teleport(players, -0.25, 80.5, 12, world="other-world"),
                                 TargetResult(2, 1, (
                                     TargetOutcome(UUID(ALICE["uuid"]), True, None),
                                     TargetOutcome(UUID(BOB["uuid"]), False, "PLAYER_NOT_FOUND"))))
                self.assertEqual(client.players.teleport([], 0, 80, 0), TargetResult(0, 0, ()))
                self.assertEqual(requests[1]["params"]["targets"], ALICE["uuid"])
                self.assertEqual(requests[2]["params"], {
                    "world": "lesson-world", "executor": None,
                    "targets": [ALICE["uuid"], BOB["uuid"]],
                    "position": [-0.25, 80.5, 12.0], "destinationWorld": "other-world"})
            finally:
                client.close()

    def test_invalid_local_arguments_do_not_consume_ids_or_send_requests(self):
        requests = []
        with peer(serve(requests, lambda _: {"applied": True})) as server:
            client = self.connect(server, writeMode="sync")
            try:
                invalid = [lambda: client.players.list(True),
                           lambda: client.players.list(["Alice"]),
                           lambda: client.players.list("x" * 2049),
                           lambda: client.players.list("  "),
                           lambda: client.players.get("@s"),
                           lambda: client.withContext(player=7),
                           lambda: client.players.teleport("Alice", True, 80, 0),
                           lambda: client.players.teleport("Alice", 0, float("nan"), 0),
                           lambda: client.players.teleport("Alice", 0, 80, float("inf")),
                           lambda: client.players.teleport("Alice", 2**31, 80, 0),
                           lambda: client.players.teleport("Alice", 0, 80, 0, world=""),
                           lambda: client.postToChat(""),
                           lambda: client.postToChat("x" * 4097),
                           lambda: client.postToChat(42)]
                for index, operation in enumerate(invalid):
                    with self.subTest(index=index), self.assertRaises((TypeError, ValueError)):
                        operation()
                client.postToChat("Привет, ученики!")
                self.assertEqual([request["id"] for request in requests], [1, 2])
                self.assertEqual(requests[1]["params"], {"message": "Привет, ученики!"})
            finally:
                client.close()

    def test_buffered_chat_sends_before_ack_and_flush_waits(self):
        received, release, flushed = threading.Event(), threading.Event(), threading.Event()

        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            requests = [read_request(connection), read_request(connection)]
            self.assertEqual([request["method"] for request in requests], ["chat.post", "chat.post"])
            received.set()
            if not release.wait(2):
                raise AssertionError("ACK release timed out")
            for request in requests:
                respond(connection, request, {"applied": True})
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            client = self.connect(server)
            failures = []

            def flush():
                try:
                    client.flush()
                except Exception as failure:
                    failures.append(failure)
                finally:
                    flushed.set()

            try:
                self.assertIsNone(client.postToChat("Один"))
                self.assertIsNone(client.postToChat("Два"))
                self.assertTrue(received.wait(1))
                worker = threading.Thread(target=flush)
                worker.start()
                try:
                    self.assertFalse(flushed.wait(0.05))
                finally:
                    release.set()
                    worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(failures, [])
            finally:
                release.set()
                client.close()

    def test_failed_initial_binding_closes_connection(self):
        closed = threading.Event()

        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            request = read_request(connection)
            self.assertEqual(request["method"], "players.get")
            connection.sendall(encode_frame({"jsonrpc": "2.0", "id": request["id"], "error": {
                "code": -32028, "message": "untrusted peer message", "data": {
                    "code": "PLAYER_NOT_FOUND", "outcome": "not-applied"}}}))
            if read_request(connection) is None:
                closed.set()

        with peer(handle) as server:
            with self.assertRaises(errors.PlayerNotFoundError):
                self.connect(server, player="Alice")
            self.assertTrue(closed.wait(1))

    def test_concurrent_sibling_close_waits_until_shared_connection_is_drained(self):
        received, release = threading.Event(), threading.Event()
        first_finished, second_finished = threading.Event(), threading.Event()
        failures = []

        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            request = read_request(connection)
            received.set()
            if not release.wait(2):
                raise AssertionError("Close ACK release timed out")
            respond(connection, request, {"applied": True})
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            client = self.connect(server)
            sibling = client.withContext()

            def close(facade, finished):
                try:
                    facade.close()
                except Exception as failure:
                    failures.append(failure)
                finally:
                    finished.set()

            client.postToChat("Wait for ACK")
            self.assertTrue(received.wait(1))
            first = threading.Thread(target=close, args=(client, first_finished))
            second = threading.Thread(target=close, args=(sibling, second_finished))
            try:
                first.start()
                self.assertFalse(first_finished.wait(0.05))
                second.start()
                self.assertFalse(second_finished.wait(0.05))
            finally:
                release.set()
                first.join(2)
                if second.ident is not None:
                    second.join(2)
                client.close()
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
