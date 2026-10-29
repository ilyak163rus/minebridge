"""Exact-slot API, descriptor correlation and bounded paginated inventory views."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import select
import threading
import unittest
from uuid import UUID

from minebridge import Minecraft, errors, items, selector, slots
from minebridge._protocol import CodecError, decode_request, decode_response, encode_frame
from minebridge.models import InventoryRef, ItemStack, ItemView
from test_i01_controls import FakeTransport as BaseTransport
from test_events_v03 import ack, event_hello
from test_transport import peer, read_request


PLAYER = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
WORLD = "00000000-0000-4000-8000-000000000003"
CAPS = ("inventories.ofBlock", "inventories.ofPlayer", "inventories.getItem", "inventories.getContents",
        "inventories.setItem", "inventories.clear", "players.setItem")
PLAYER_SLOTS = list(range(36)) + ["head", "chest", "legs", "feet", "off_hand"]


def player_ref(identity=PLAYER):
    return {"kind": "player", "player": identity, "size": 41, "slots": list(PLAYER_SLOTS)}


def chest_ref(*, combined=False, double=False, position=(1, 80, -1), world=WORLD):
    layout = [{"position": list(position), "offset": 0, "size": 27, "key": "minecraft:chest"}]
    if double:
        layout.append({"position": [position[0] + 1, position[1], position[2]], "offset": 27,
                       "size": 27, "key": "minecraft:chest"})
    size = 54 if double else 27
    return {"kind": "chest", "world": world, "position": list(position), "combined": combined,
            "size": size, "slots": list(range(size)), "layout": layout}


def view(key="minecraft:diamond", amount=1, *, name=None, lore=None, extra=False, truncated=False):
    return {"key": key, "amount": amount, "name": name, "lore": lore,
            "hasAdditionalData": extra, "truncated": truncated}


class Transport(BaseTransport):
    def __init__(self, answer=None, *, capabilities=CAPS):
        super().__init__(answer=answer, capabilities=capabilities)

    def exchange(self, method, params, *, mutation=False):
        self.calls.append((method, deepcopy(params), mutation))
        if method == "players.get":
            value = {"player": {"uuid": PLAYER, "name": "Alice", "entityId": 7}}
        elif self.answer:
            value = self.answer(method, params)
        else:
            raise AssertionError(method)
        frame = encode_frame({"jsonrpc": "2.0", "id": len(self.calls) + 1, "result": value})
        return decode_response(frame[:-1], len(self.calls) + 1, method)


def valid_answer(method, params):
    if method == "inventories.ofPlayer":
        return {"inventory": player_ref()}
    if method == "inventories.getItem":
        return {"slot": params["slot"], "item": view()}
    if method == "inventories.setItem":
        return {"applied": True, "slot": params["slot"], "previous": None,
                "current": view(params["item"]["key"], params["item"]["amount"],
                                name=params["item"]["name"], lore=params["item"]["lore"])}
    if method == "inventories.clear":
        return {"applied": True, "slots": PLAYER_SLOTS if params["slot"] is None else [params["slot"]]}
    if method == "players.setItem":
        return {"matched": 1, "applied": 1, "targets": [{"uuid": PLAYER, "applied": True, "code": None}]}
    raise AssertionError(method)


class InventoryApiTests(unittest.TestCase):
    def test_offline_slots_and_models_are_immutable_and_metadata_does_not_call_server(self):
        transport = Transport(valid_answer)
        ref = Minecraft(transport).inventories.ofPlayer("Alice")
        self.assertIsInstance(ref, InventoryRef)
        self.assertEqual((ref.kind, ref.size, ref.player), ("player", 41, UUID(PLAYER)))
        self.assertEqual(ref.slots, tuple(range(36)) + tuple(slots.EquipmentSlot))
        self.assertEqual((ref.world, ref.position, ref.combined, ref.layout), (None, None, None, ()))
        self.assertEqual(len(transport.calls), 1)
        with self.assertRaises((FrozenInstanceError, TypeError)):
            ref.size = 2
        with self.assertRaises(FrozenInstanceError):
            ref._info.size = 2
        item = ref.getItem(0)
        self.assertIsInstance(item, ItemView)
        with self.assertRaises(FrozenInstanceError):
            item.amount = 2

    def test_ofblock_rounds_like_existing_block_api_and_pins_world_uuid_and_layout(self):
        transport = Transport(lambda method, params: {"inventory": chest_ref(
            combined=params["combined"], double=True, position=tuple(params["position"]),
            world=transport.context.world.uuid)})
        ref = Minecraft(transport).inventories.ofBlock(1.9, 80.1, -.1, combined=True)
        self.assertEqual(ref.position, (1, 80, -1))
        self.assertEqual(ref.world, UUID(transport.context.world.uuid))
        self.assertEqual((ref.size, ref.combined), (54, True))
        self.assertEqual(tuple(part.offset for part in ref.layout), (0, 27))
        self.assertEqual(transport.calls[0][1], {"world": "lesson", "destinationWorld": None,
                                               "position": [1, 80, -1], "combined": True})

    def test_unsupported_capabilities_fail_before_rpc_including_existing_ref_methods(self):
        transport = Transport(valid_answer, capabilities=())
        mc = Minecraft(transport)
        for action in (lambda: mc.inventories.ofPlayer("Alice"), lambda: mc.inventories.ofBlock(1, 2, 3),
                       lambda: mc.players.setItem(selector.ALL_PLAYERS, 0, items.DIAMOND)):
            with self.subTest(action=action):
                with self.assertRaises(errors.UnsupportedFeatureError):
                    action()
        self.assertEqual(transport.calls, [])
        full = Transport(valid_answer)
        ref = Minecraft(full).inventories.ofPlayer("Alice")
        object.__setattr__(ref, "_transport", transport)
        with self.assertRaises(errors.UnsupportedFeatureError):
            ref.getItem(0)
        self.assertEqual(transport.calls, [])

    def test_invalid_slots_amount_and_itemview_never_reach_transport(self):
        transport = Transport(valid_answer)
        ref = Minecraft(transport).inventories.ofPlayer("Alice")
        for slot in (True, 0.0, None, [], {}):
            with self.subTest(slot=slot), self.assertRaises(TypeError):
                ref.getItem(slot)
        for slot in (-1, 36, 40, 54, "BODY", "saddle", "unknown"):
            with self.subTest(slot=slot), self.assertRaises(errors.InvalidSlotError):
                ref.getItem(slot)
        for amount in (0, -1, 2305, True, 1.0):
            with self.subTest(amount=amount), self.assertRaises((TypeError, ValueError)):
                ref.setItem(0, items.DIAMOND, amount)
        with self.assertRaises(TypeError):
            ref.setItem(0, ItemView(items.DIAMOND, 1, None, None, False, False))
        self.assertEqual(len(transport.calls), 1)

    def test_exact_setter_preserves_request_spec_and_current_previous_are_readonly(self):
        previous = view("minecraft:enchanted_book", 1, name="Existing", extra=True)
        def answer(method, params):
            result = valid_answer(method, params)
            if method == "inventories.setItem": result["previous"] = previous
            return result
        transport = Transport(answer)
        mc = Minecraft(transport, "buffered")
        ref = mc.inventories.ofPlayer("Alice")
        result = ref.setItem(slots.OFF_HAND, ItemStack(items.DIAMOND, 3, "Prize", ("Line",)))
        self.assertEqual((result.applied, result.slot, result.previous.key.key, result.current.amount),
                         (True, slots.OFF_HAND, "minecraft:enchanted_book", 3))
        self.assertTrue(result.previous.hasAdditionalData)
        self.assertEqual(transport.calls[-1], ("inventories.setItem", {
            "inventory": player_ref(), "slot": "off_hand", "item": {
                "key": "minecraft:diamond", "amount": 3, "name": "Prize", "lore": ["Line"]}}, True))
        with self.assertRaises(FrozenInstanceError): result.current.amount = 1

    def test_both_write_modes_use_synchronous_inventory_rpc_and_clear_scope_excludes_hidden_slots(self):
        for mode in ("buffered", "sync"):
            with self.subTest(mode=mode):
                transport = Transport(valid_answer)
                ref = Minecraft(transport, mode).inventories.ofPlayer("Alice")
                one = ref.clear(slots.HEAD)
                all_slots = ref.clear()
                self.assertEqual(one.slots, (slots.HEAD,))
                self.assertEqual(all_slots.slots, ref.slots)
                self.assertTrue(all(call[2] for call in transport.calls[1:]))
                self.assertNotIn("body", all_slots.slots)
                self.assertNotIn("saddle", all_slots.slots)

    def test_getcontents_collects_short_byte_pages_with_empty_slots_and_equipment_keys(self):
        def answer(method, params):
            if method == "inventories.ofPlayer": return {"inventory": player_ref()}
            offset = params["offset"]
            end = min(41, offset + 7)
            return {"items": [{"slot": slot, "item": view(amount=2) if index == 36 else None}
                              for index, slot in enumerate(PLAYER_SLOTS[offset:end], offset)],
                    "total": 41, "nextOffset": end if end < 41 else None}
        transport = Transport(answer)
        result = Minecraft(transport).inventories.ofPlayer("Alice").getContents()
        self.assertEqual(tuple(result), tuple(range(36)) + tuple(slots.EquipmentSlot))
        self.assertIsNone(result[0])
        self.assertEqual(result[slots.HEAD].amount, 2)
        self.assertEqual([call[1]["offset"] for call in transport.calls[1:]], [0, 7, 14, 21, 28, 35])
        self.assertTrue(all(call[2] is False for call in transport.calls))

    def test_layout_error_on_later_page_never_returns_partial_dict(self):
        def answer(method, params):
            if method == "inventories.ofPlayer": return {"inventory": player_ref()}
            if params["offset"]:
                raise errors.InventoryChangedError("Fixture layout changed")
            return {"items": [{"slot": 0, "item": None}], "total": 41, "nextOffset": 1}
        transport = Transport(answer)
        ref = Minecraft(transport).inventories.ofPlayer("Alice")
        with self.assertRaises(errors.InventoryChangedError): ref.getContents()
        self.assertEqual(len(transport.calls), 3)
        self.assertFalse(transport.closed)

    def test_wrong_pagination_total_order_and_progress_are_protocol_errors(self):
        pages = [
            {"items": [{"slot": 1, "item": None}], "total": 41, "nextOffset": 1},
            {"items": [{"slot": 0, "item": None}], "total": 41, "nextOffset": 2},
            {"items": [{"slot": 0, "item": None}], "total": 27, "nextOffset": 1},
            {"items": [{"slot": 0, "item": None}], "total": 41, "nextOffset": None},
        ]
        for page in pages:
            with self.subTest(page=page):
                transport = Transport(lambda m, p: {"inventory": player_ref()} if m == "inventories.ofPlayer" else page)
                ref = Minecraft(transport).inventories.ofPlayer("Alice")
                with self.assertRaises(errors.ProtocolError) as raised: ref.getContents()
                self.assertEqual(raised.exception.outcome, "not-applied")
                self.assertTrue(transport.closed)

    def test_wrong_resolved_player_world_position_or_combined_never_becomes_reference(self):
        for identity in (OTHER,):
            transport = Transport(lambda m, p: {"inventory": player_ref(identity)})
            with self.assertRaises(errors.ProtocolError): Minecraft(transport).inventories.ofPlayer(UUID(PLAYER))
            self.assertTrue(transport.closed)
        for change in ("world", "position", "combined"):
            def answer(method, params):
                descriptor = chest_ref(world=transport.context.world.uuid)
                if change == "world": descriptor["world"] = OTHER
                if change == "position":
                    descriptor["position"] = [2, 80, -1]
                    descriptor["layout"][0]["position"] = [2, 80, -1]
                if change == "combined": descriptor["combined"] = True
                return {"inventory": descriptor}
            transport = Transport(answer)
            with self.subTest(change=change), self.assertRaises(errors.ProtocolError):
                Minecraft(transport).inventories.ofBlock(1, 80, -1)
            self.assertTrue(transport.closed)

    def test_wrong_read_or_mutation_slot_content_or_clear_confirmation_closes_connection(self):
        cases = [
            ("inventories.getItem", lambda p: {"slot": 1, "item": None}),
            ("inventories.setItem", lambda p: {"applied": True, "slot": 1, "previous": None, "current": view()}),
            ("inventories.setItem", lambda p: {"applied": True, "slot": 0, "previous": None, "current": view(amount=2)}),
            ("inventories.setItem", lambda p: {"applied": True, "slot": 0, "previous": None, "current": None}),
            ("inventories.clear", lambda p: {"applied": True, "slots": [1]}),
        ]
        for method, bad in cases:
            transport = Transport(lambda m, p: bad(p) if m == method else valid_answer(m, p))
            ref = Minecraft(transport).inventories.ofPlayer("Alice")
            with self.subTest(method=method), self.assertRaises(errors.ProtocolError) as raised:
                if method.endswith("getItem"): ref.getItem(0)
                elif method.endswith("setItem"): ref.setItem(0, items.DIAMOND)
                else: ref.clear(0)
            self.assertEqual(raised.exception.outcome, "not-applied" if method.endswith("getItem") else "unknown")
            self.assertTrue(transport.closed)

    def test_bulk_target_uuid_correlation_and_withcontext_share_connection_but_pin_self(self):
        transport = Transport(valid_answer)
        mc = Minecraft(transport)
        derived = mc.withContext(player="Alice")
        ref = derived.inventories.ofPlayer(selector.SELF)
        self.assertEqual(ref.player, UUID(PLAYER))
        self.assertEqual(transport.calls[-1][1]["executor"], PLAYER)
        result = derived.players.setItem(selector.SELF, slots.OFF_HAND, items.SHIELD, 1)
        self.assertEqual(result.targets[0].uuid, UUID(PLAYER))
        self.assertEqual(transport.calls[-1][1]["slot"], "off_hand")
        self.assertTrue(transport.calls[-1][2])
        def mismatch(method, params):
            return {"matched": 1, "applied": 1, "targets": [{"uuid": OTHER, "applied": True, "code": None}]}
        transport.answer = mismatch
        with self.assertRaises(errors.ProtocolError): mc.players.setItem(UUID(PLAYER), 0, items.DIAMOND)
        self.assertTrue(transport.closed)

    def test_strict_views_refs_and_pages_reject_malformed_peer_shapes(self):
        invalid = []
        for change in (dict(extra=1), dict(slots=list(range(41))), dict(size=40)):
            invalid.append(("inventories.ofPlayer", {"inventory": dict(player_ref(), **change)}))
        invalid += [("inventories.getItem", {"slot": 0, "item": dict(view(), **change)}) for change in (
            {"amount": 0}, {"amount": True}, {"name": "a" * 257}, {"lore": [""] * 17}, {"truncated": 1}, {"extra": 2})]
        invalid += [("inventories.getContents", {"items": [], "total": 41, "nextOffset": None}),
                    ("inventories.getContents", {"items": [{"slot": 0, "item": None}] * 2, "total": 41, "nextOffset": 2}),
                    ("inventories.getContents", {"items": [{"slot": 0, "item": None}], "total": 41, "nextOffset": 41})]
        for method, result in invalid:
            with self.subTest(method=method, result=result), self.assertRaises(CodecError):
                decode_response(encode_frame({"jsonrpc": "2.0", "id": 1, "result": result})[:-1], 1, method)

    def test_chest_layout_geometry_is_strict_and_armor_numeric_ids_are_not_storage(self):
        for change in (dict(combined=False), dict(layout=list(reversed(chest_ref(combined=True, double=True)["layout"]))),
                       dict(position=[100, 80, 100])):
            descriptor = dict(chest_ref(combined=True, double=True), **change)
            request = {"jsonrpc": "2.0", "id": 1, "method": "inventories.getItem", "params": {"inventory": descriptor, "slot": 0}}
            with self.subTest(change=change), self.assertRaises(CodecError) as raised:
                decode_request(encode_frame(request)[:-1])
            self.assertEqual(raised.exception.code, "INVALID_PARAMS")
        for slot, code in ((36, "INVALID_SLOT"), (2147483648, "INVALID_SLOT"), ("BODY", "INVALID_SLOT"), (True, "INVALID_PARAMS"), (1.0, "INVALID_PARAMS")):
            request = {"jsonrpc": "2.0", "id": 1, "method": "inventories.getItem", "params": {"inventory": player_ref(), "slot": slot}}
            with self.subTest(slot=slot), self.assertRaises(CodecError) as raised:
                decode_request(encode_frame(request)[:-1])
            self.assertEqual(raised.exception.code, code)

    def test_real_tcp_inventory_read_is_barrier_for_previous_buffered_setblock(self):
        block_waiting, release, completed = threading.Event(), threading.Event(), threading.Event()
        received, failures, inventory = [], [], []
        metadata = event_hello()
        metadata["capabilities"].extend(CAPS)
        def handler(connection, stopping):
            hello = read_request(connection); connection.sendall(ack(hello, metadata))
            first = read_request(connection); received.append(first["method"])
            block_waiting.set()
            if not release.wait(2): raise AssertionError("Fixture release deadline")
            if select.select([connection], [], [], 0)[0]: raise AssertionError("Inventory request overtook buffered ACK")
            connection.sendall(ack(first, {"applied": True}))
            second = read_request(connection); received.append(second["method"])
            connection.sendall(ack(second, {"inventory": player_ref()}))
            while not stopping.is_set() and read_request(connection) is not None: pass
        with peer(handler) as server:
            mc = Minecraft.create("127.0.0.1", server.port, timeout=2)
            try:
                mc.setBlock(0, 80, 0, 4)
                self.assertTrue(block_waiting.wait(1))
                def call():
                    try: inventory.append(mc.inventories.ofPlayer("Alice"))
                    except Exception as e: failures.append(e)
                    finally: completed.set()
                thread = threading.Thread(target=call); thread.start()
                self.assertFalse(completed.wait(.05))
                release.set(); thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertFalse(failures)
                self.assertEqual(received, ["blocks.set", "inventories.ofPlayer"])
                self.assertEqual(inventory[0].player, UUID(PLAYER))
            finally:
                release.set(); mc.close()


if __name__ == "__main__": unittest.main()
