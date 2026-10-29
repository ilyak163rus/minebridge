"""Public item/effect/spawn behavior over actual controlled TCP connections."""

from dataclasses import FrozenInstanceError
import select
import threading
import unittest
from uuid import UUID

from minebridge import Minecraft, block, effects, entity, errors, items, selector
from minebridge.models import (
    EffectKey, EntityRef, EntityTypeKey, InventoryResult, ItemKey, ItemStack,
    LivingEntityRef, PlayerRef, TargetOutcome, TargetResult,
)
from test_client import send_hello
from test_players import ALICE, BOB, respond, serve
from test_transport import peer, read_request
from minebridge._protocol import encode_frame


def item_value(key="minecraft:diamond", amount=1, *, name=None, lore=None):
    return {"key": key, "amount": amount, "name": name, "lore": lore}


def inventory_value(*, requested=1, given=1, leftovers=None, dropped=0):
    return {"matched": 1, "applied": 1, "targets": [{
        "uuid": ALICE["uuid"], "applied": True, "code": None,
        "requested": requested, "given": given,
        "leftovers": [] if leftovers is None else leftovers, "dropped": dropped,
    }]}


def entity_value(key="minecraft:zombie", *, living=True):
    return {"entity": {"uuid": ALICE["uuid"], "entityId": 42,
                       "key": key, "living": living}}


class GameplayApiTests(unittest.TestCase):
    def connect(self, server, **options):
        options.setdefault("timeout", 1)
        return Minecraft.create("127.0.0.1", server.port, **options)

    def test_item_and_reference_models_are_frozen_with_distinct_key_types(self):
        lore = ["Line one"]
        stack = ItemStack(items.DIAMOND, 3, "Prize", lore)
        lore.append("Mutated input")
        self.assertEqual(stack.key, "minecraft:diamond")
        self.assertEqual(stack.lore, ("Line one",))
        with self.assertRaises(FrozenInstanceError):
            stack.amount = 4
        for key in (effects.SPEED, entity.ZOMBIE):
            with self.subTest(key=key), self.assertRaises(TypeError):
                ItemStack(key)
        self.assertIsInstance(items.IRON_SWORD, ItemKey)
        self.assertIsInstance(effects.SPEED, EffectKey)
        self.assertIsInstance(entity.LIGHTNING_BOLT, EntityTypeKey)
        player = PlayerRef(UUID(ALICE["uuid"]), 17, "Alice")
        self.assertIsInstance(player, LivingEntityRef)
        self.assertEqual(player.key, "minecraft:player")
        self.assertEqual(EntityRef(UUID(ALICE["uuid"]), 42, key="minecraft:lightning_bolt").key,
                         "minecraft:lightning_bolt")

    def test_give_item_reports_full_inventory_without_losing_metadata(self):
        requests = []
        leftover = item_value(amount=2, name="Lesson prize", lore=["Earned in Python"])
        with peer(serve(requests, lambda _: inventory_value(
            requested=2, given=0, leftovers=[leftover]))) as server:
            client = self.connect(server)
            try:
                result = client.players.giveItem(selector.ALL_PLAYERS, ItemStack(
                    items.DIAMOND, 2, "Lesson prize", ["Earned in Python"]))
                self.assertIsInstance(result, InventoryResult)
                self.assertEqual((result.matched, result.applied), (1, 1))
                outcome = result.targets[0]
                self.assertTrue(outcome.applied)
                self.assertEqual((outcome.requested, outcome.given, outcome.dropped), (2, 0, 0))
                self.assertEqual(outcome.leftovers, (ItemStack(
                    items.DIAMOND, 2, "Lesson prize", ("Earned in Python",)),))
                self.assertEqual(requests[1]["params"], {
                    "world": "lesson-world", "executor": None, "targets": "@a",
                    "item": leftover, "overflow": "return"})
            finally:
                client.close()

    def test_give_item_override_and_drop_account_for_both_destinations(self):
        requests = []
        with peer(serve(requests, lambda _: inventory_value(
            requested=70, given=64, dropped=6))) as server:
            client = self.connect(server)
            try:
                result = client.players.giveItem("Alice", ItemStack(items.DIAMOND, 1),
                                                 70, overflow="drop")
                outcome = result.targets[0]
                self.assertEqual((outcome.requested, outcome.given, outcome.dropped,
                                  outcome.leftovers), (70, 64, 6, ()))
                self.assertEqual(requests[1]["params"]["item"], item_value(amount=70))
                self.assertEqual(requests[1]["params"]["overflow"], "drop")
            finally:
                client.close()

    def test_empty_groups_and_empty_lore_are_valid_results(self):
        requests = []

        def answer(request):
            if request["params"]["targets"] == []:
                return {"matched": 0, "applied": 0, "targets": []}
            return inventory_value(given=0, leftovers=[item_value(lore=[])])

        with peer(serve(requests, answer)) as server:
            client = self.connect(server)
            try:
                self.assertEqual(client.players.giveItem([], items.DIAMOND),
                                 InventoryResult(0, 0, ()))
                self.assertEqual(client.effects.add([], effects.SPEED, duration=1),
                                 TargetResult(0, 0, ()))
                self.assertEqual(client.players.giveItem("Alice", items.DIAMOND)
                                 .targets[0].leftovers[0].lore, ())
            finally:
                client.close()

    def test_effect_duration_and_level_remain_student_facing_values(self):
        requests = []
        outcome = {"matched": 2, "applied": 1, "targets": [
            {"uuid": ALICE["uuid"], "applied": True, "code": None},
            {"uuid": BOB["uuid"], "applied": False, "code": "ENTITY_NOT_FOUND"},
        ]}
        with peer(serve(requests, lambda _: outcome)) as server:
            client = self.connect(server)
            try:
                result = client.effects.add(selector.ALL_ENTITIES, effects.SPEED,
                                            duration=0.051, level=2, particles=False)
                self.assertEqual(result, TargetResult(2, 1, (
                    TargetOutcome(UUID(ALICE["uuid"]), True, None),
                    TargetOutcome(UUID(BOB["uuid"]), False, "ENTITY_NOT_FOUND"))))
                self.assertEqual(requests[1]["params"], {
                    "world": "lesson-world", "executor": None, "targets": "@e",
                    "effect": {"key": "minecraft:speed", "durationTicks": 2,
                               "level": 2, "particles": False}})
            finally:
                client.close()

    def test_spawn_facades_preserve_fractional_coordinates_and_special_options(self):
        requests = []

        def answer(request):
            key = request["params"]["entity"]["key"]
            return entity_value(key, living=key == "minecraft:zombie")

        with peer(serve(requests, answer)) as server:
            client = self.connect(server)
            try:
                zombie = client.spawnEntity(-0.25, 80.5, 12, entity.ZOMBIE)
                self.assertIsInstance(zombie, LivingEntityRef)
                self.assertEqual(zombie.key, "minecraft:zombie")
                lightning = client.entities.spawn(entity.LIGHTNING_BOLT, 0, 80, 0)
                self.assertIsInstance(lightning, EntityRef)
                self.assertNotIsInstance(lightning, LivingEntityRef)
                client.entities.spawn(entity.FALLING_BLOCK, 1, 80, 2,
                                      block=block.OAK_LOG.withStates(axis="x"), world="other")
                client.entities.spawn(entity.ITEM_FRAME, 2, 80, 2, item=items.DIAMOND,
                                      face="east")
                client.entities.spawn(entity.FISHING_BOBBER, 2, 80, 2,
                                      owner=PlayerRef(UUID(ALICE["uuid"]), 17, "Alice"))
                self.assertEqual(requests[1]["params"], {
                    "world": "lesson-world", "destinationWorld": None,
                    "position": [-0.25, 80.5, 12.0], "entity": {"key": "minecraft:zombie"},
                    "options": {"item": None, "block": None, "face": None, "owner": None}})
                self.assertEqual(requests[3]["params"]["options"]["block"],
                                 {"key": "minecraft:oak_log", "states": {"axis": "x"}})
                self.assertEqual(requests[3]["params"]["destinationWorld"], "other")
                self.assertEqual(requests[4]["params"]["options"]["item"], item_value())
                self.assertEqual(requests[4]["params"]["options"]["face"], "east")
                self.assertEqual(requests[5]["params"]["options"]["owner"], ALICE["uuid"])
            finally:
                client.close()

    def test_peaceful_spawn_has_clear_typed_error_and_does_not_break_connection(self):
        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            request = read_request(connection)
            self.assertEqual(request["params"]["entity"]["key"], "minecraft:giant")
            connection.sendall(encode_frame({"jsonrpc": "2.0", "id": request["id"], "error": {
                "code": -32053, "message": "Untrusted peer text", "data": {
                    "code": "PEACEFUL_SPAWN_BLOCKED", "outcome": "not-applied"}}}))
            request = read_request(connection)
            self.assertEqual(request["params"]["entity"]["key"], "minecraft:cow")
            respond(connection, request, entity_value("minecraft:cow"))
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            client = self.connect(server)
            try:
                with self.assertRaises(errors.PeacefulSpawnError) as caught:
                    client.spawnEntity(0, 1, 0, entity.GIANT)
                failure = caught.exception
                self.assertEqual(failure.code, "PEACEFUL_SPAWN_BLOCKED")
                self.assertEqual(failure.outcome, "not-applied")
                self.assertEqual(failure.method, "entities.spawn")
                self.assertEqual(failure.request_id, 2)
                self.assertIn("Peaceful", str(failure))
                self.assertNotIn("Untrusted peer text", str(failure))
                cow = client.spawnEntity(0, 1, 0, entity.COW)
                self.assertEqual(cow.key, "minecraft:cow")
            finally:
                client.close()

    def test_new_services_inherit_context_without_rebinding_original_and_share_close(self):
        requests = []

        def answer(request):
            if request["method"] == "players.get":
                return {"player": ALICE}
            if request["method"] == "players.giveItem":
                return inventory_value()
            return {"matched": 0, "applied": 0, "targets": []}

        with peer(serve(requests, answer)) as server:
            original = self.connect(server)
            bound = original.withContext(player="Alice")
            try:
                bound.players.giveItem(selector.SELF, items.DIAMOND)
                bound.effects.add(selector.SELF, effects.SPEED, duration=1)
                original.effects.add(selector.ALL_PLAYERS, effects.SPEED, duration=1)
                self.assertEqual([row["params"]["executor"] for row in requests[2:]],
                                 [ALICE["uuid"], ALICE["uuid"], None])
                bound.close()
                for operation in (lambda: original.players.giveItem("Alice", items.DIAMOND),
                                  lambda: original.effects.add("Alice", effects.SPEED, duration=1),
                                  lambda: original.spawnEntity(0, 80, 0, entity.ZOMBIE)):
                    with self.assertRaises(errors.ConnectionError):
                        operation()
            finally:
                original.close()

    def test_invalid_local_arguments_never_send_a_mutation_or_consume_request_ids(self):
        requests = []
        with peer(serve(requests, lambda _: {"applied": True})) as server:
            client = self.connect(server, writeMode="sync")
            try:
                invalid = [
                    lambda: client.players.giveItem("Alice", effects.SPEED),
                    lambda: client.players.giveItem("Alice", items.DIAMOND, True),
                    lambda: client.players.giveItem("Alice", items.DIAMOND, 0),
                    lambda: client.players.giveItem("Alice", items.DIAMOND, 2305),
                    lambda: client.players.giveItem("Alice", items.DIAMOND, overflow="ignore"),
                    lambda: client.players.giveItem("Alice", items.DIAMOND, overflow=True),
                    lambda: ItemStack(items.DIAMOND, name="x" * 257),
                    lambda: ItemStack(items.DIAMOND, lore=["x"] * 17),
                    lambda: ItemStack(items.DIAMOND, lore=["x" * 257]),
                    lambda: client.effects.add("Alice", items.DIAMOND, duration=1),
                    lambda: client.effects.add("Alice", effects.SPEED, duration=True),
                    lambda: client.effects.add("Alice", effects.SPEED, duration=0),
                    lambda: client.effects.add("Alice", effects.SPEED, duration=float("nan")),
                    lambda: client.effects.add("Alice", effects.SPEED, duration=float("inf")),
                    lambda: client.effects.add("Alice", effects.SPEED, duration=10**1000),
                    lambda: client.effects.add("Alice", effects.SPEED, duration=1, level=True),
                    lambda: client.effects.add("Alice", effects.SPEED, duration=1, level=0),
                    lambda: client.effects.add("Alice", effects.SPEED, duration=1, level=257),
                    lambda: client.effects.add("Alice", effects.SPEED, duration=1, particles=1),
                    lambda: client.spawnEntity(0, 80, 0, items.DIAMOND),
                    lambda: client.spawnEntity(True, 80, 0, entity.ZOMBIE),
                    lambda: client.spawnEntity(0, float("nan"), 0, entity.ZOMBIE),
                    lambda: client.spawnEntity(0, 80, 2**31, entity.ZOMBIE),
                    lambda: client.spawnEntity(0, 80, 0, entity.ZOMBIE, world=""),
                    lambda: client.spawnEntity(0, 80, 0, entity.ITEM_FRAME, face="NORTH"),
                    lambda: client.spawnEntity(0, 80, 0, entity.ITEM_FRAME, face=True),
                    lambda: client.spawnEntity(0, 80, 0, entity.FISHING_BOBBER, owner="@s"),
                ]
                for index, operation in enumerate(invalid):
                    with self.subTest(index=index), self.assertRaises((TypeError, ValueError)):
                        operation()
                client.postToChat("Arguments rejected locally")
                self.assertEqual([row["id"] for row in requests], [1, 2])
            finally:
                client.close()

    def test_result_operations_drain_buffered_writes_before_sending(self):
        write_received, release, completed = threading.Event(), threading.Event(), threading.Event()
        attempting = threading.Event()
        requests, failures = [], []

        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            request = read_request(connection)
            requests.append(request)
            write_received.set()
            if not attempting.wait(2):
                raise AssertionError("The result operation was not attempted")
            readable, _, _ = select.select([connection], [], [], 0.05)
            self.assertEqual(readable, [], "The result request was sent before the buffered ACK")
            if not release.wait(2):
                raise AssertionError("ACK was not released")
            respond(connection, request, {"applied": True})
            request = read_request(connection)
            requests.append(request)
            respond(connection, request, inventory_value())
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            client = self.connect(server)

            def give():
                try:
                    attempting.set()
                    client.players.giveItem("Alice", items.DIAMOND)
                except Exception as error:
                    failures.append(error)
                finally:
                    completed.set()

            worker = threading.Thread(target=give)
            try:
                client.setBlock(0, 80, 0, block.COBBLESTONE)
                self.assertTrue(write_received.wait(1))
                worker.start()
                self.assertFalse(completed.wait(0.05))
                self.assertEqual([row["method"] for row in requests], ["blocks.set"])
            finally:
                release.set()
                if worker.ident is not None:
                    worker.join(2)
                client.close()
            self.assertFalse(worker.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual([row["method"] for row in requests], ["blocks.set", "players.giveItem"])

    def test_deferred_error_surfaces_before_effect_and_is_not_repeated(self):
        requests = []
        write_returned = threading.Event()

        def handle(connection, stopping):
            send_hello(connection, read_request(connection))
            request = read_request(connection)
            requests.append(request)
            if not write_returned.wait(2):
                raise AssertionError("The buffered call did not return")
            connection.sendall(encode_frame({"jsonrpc": "2.0", "id": request["id"], "error": {
                "code": -32024, "message": "Untrusted", "data": {
                    "code": "INVALID_BLOCK", "outcome": "not-applied"}}}))
            request = read_request(connection)
            requests.append(request)
            respond(connection, request, {"matched": 0, "applied": 0, "targets": []})
            self.assertIsNone(read_request(connection))

        with peer(handle) as server:
            client = self.connect(server)
            try:
                client.setBlock(0, 80, 0, "minecraft:future_block")
                write_returned.set()
                with self.assertRaises(errors.InvalidBlockError) as caught:
                    client.effects.add("@a", effects.SPEED, duration=1)
                self.assertEqual(caught.exception.method, "blocks.set")
                self.assertEqual(client.effects.add("@a", effects.SPEED, duration=1),
                                 TargetResult(0, 0, ()))
                self.assertEqual([row["method"] for row in requests], ["blocks.set", "effects.add"])
                self.assertEqual([row["id"] for row in requests], [2, 3])
            finally:
                client.close()

    def test_request_specific_inventory_mismatch_closes_without_retry(self):
        cases = [
            inventory_value(requested=3, given=3),
            inventory_value(requested=2, given=0, leftovers=[item_value("minecraft:emerald", 2)]),
            inventory_value(requested=2, given=0, leftovers=[item_value(amount=2, name="Other")]),
            inventory_value(requested=2, given=0, leftovers=[item_value(amount=2, lore=["Other"])]),
            inventory_value(requested=2, given=1, dropped=1),
        ]
        for response in cases:
            with self.subTest(response=response):
                requests = []
                with peer(serve(requests, lambda _: response)) as server:
                    client = self.connect(server)
                    try:
                        with self.assertRaises(errors.ProtocolError) as caught:
                            client.players.giveItem("Alice", items.DIAMOND, 2)
                        self.assertEqual(caught.exception.outcome, "unknown")
                        self.assertEqual(caught.exception.method, "players.giveItem")
                        self.assertEqual(caught.exception.request_id, 2)
                        with self.assertRaises(errors.ConnectionError):
                            client.players.giveItem("Alice", items.DIAMOND)
                        self.assertEqual(len(requests), 2)
                    finally:
                        client.close()

    def test_spawn_result_type_mismatch_closes_without_retry(self):
        requests = []
        with peer(serve(requests, lambda _: entity_value("minecraft:cow"))) as server:
            client = self.connect(server)
            try:
                with self.assertRaises(errors.ProtocolError) as caught:
                    client.spawnEntity(0, 80, 0, entity.ZOMBIE)
                self.assertEqual(caught.exception.outcome, "unknown")
                self.assertEqual(caught.exception.method, "entities.spawn")
                self.assertEqual(caught.exception.request_id, 2)
                with self.assertRaises(errors.ConnectionError):
                    client.spawnEntity(0, 80, 0, entity.ZOMBIE)
                self.assertEqual(len(requests), 2)
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
