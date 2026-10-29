"""I04 wire accounting and reference validation at the client trust boundary."""

import copy
import unittest

from minebridge import errors
from minebridge._protocol import (
    CodecError, JsonNumber, RpcError, decode_response, encode_frame, server_error_exception,
)

UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ITEM = {"key": "minecraft:diamond", "amount": 4, "name": "Prize", "lore": ["Lesson"]}


def response(method, result):
    return decode_response(encode_frame({"jsonrpc": "2.0", "id": 9, "result": result}), 9, method)


class GameplayProtocolTests(unittest.TestCase):
    def test_inventory_partial_return_and_drop_account_for_every_item(self):
        for given, leftover, dropped in ((0, 4, 0), (2, 2, 0), (2, 0, 2), (4, 0, 0)):
            with self.subTest(given=given, leftover=leftover, dropped=dropped):
                result = {"matched": 1, "applied": 1, "targets": [{
                    "uuid": UUID, "applied": True, "code": None, "requested": 4, "given": given,
                    "leftovers": [dict(ITEM, amount=leftover)] if leftover else [], "dropped": dropped,
                }]}
                self.assertIsNone(response("players.giveItem", result).error)
        self.assertIsNone(response("players.giveItem", {"matched": 0, "applied": 0, "targets": []}).error)

    def test_inventory_inconsistent_quantities_and_untyped_metadata_are_rejected(self):
        good = {"matched": 1, "applied": 1, "targets": [{
            "uuid": UUID, "applied": True, "code": None, "requested": 4, "given": 0,
            "leftovers": [ITEM], "dropped": 0,
        }]}
        for field, value in (("requested", 3), ("given", True), ("dropped", -1),
                             ("leftovers", [dict(ITEM, amount=0)]),
                             ("leftovers", [dict(ITEM, name={"text": "unexpected"})]),
                             ("leftovers", [dict(ITEM, lore="unexpected")])):
            bad = copy.deepcopy(good)
            bad["targets"][0][field] = value
            with self.subTest(field=field), self.assertRaises(CodecError):
                response("players.giveItem", bad)
        bad = copy.deepcopy(good)
        bad.update(matched=2, applied=2, targets=bad["targets"] * 2)
        with self.assertRaises(CodecError):
            response("players.giveItem", bad)

    def test_entity_spawn_requires_typed_uuid_runtime_id_key_and_living_flag(self):
        entity = {"uuid": UUID, "entityId": 71, "key": "minecraft:zombie", "living": True}
        self.assertIsNone(response("entities.spawn", {"entity": entity}).error)
        for field, value in (("uuid", "bad"), ("entityId", -1), ("entityId", True),
                             ("key", "zombie"), ("living", 1)):
            with self.subTest(field=field), self.assertRaises(CodecError):
                response("entities.spawn", {"entity": dict(entity, **{field: value})})

    def test_effects_use_the_existing_per_target_success_contract(self):
        self.assertIsNone(response("effects.add", {"matched": 1, "applied": 0, "targets": [
            {"uuid": UUID, "applied": False, "code": "EFFECT_REJECTED"},
        ]}).error)
        with self.assertRaises(CodecError):
            response("effects.add", {"matched": 1, "applied": 1, "targets": [
                {"uuid": UUID, "applied": True, "code": "EFFECT_REJECTED"},
            ]})

    def test_gameplay_error_numbers_select_fixed_typed_local_diagnostics(self):
        for number, code, exception in (
            (-32033, "INVALID_ITEM", errors.InvalidItemError),
            (-32034, "INVALID_EFFECT", errors.InvalidEffectError),
            (-32035, "INVALID_ENTITY_TYPE", errors.InvalidEntityTypeError),
            (-32036, "UNSUPPORTED_ENTITY_TYPE", errors.UnsupportedEntityTypeError),
            (-32037, "ENTITY_NOT_FOUND", errors.EntityNotFoundError),
        ):
            with self.subTest(code=code):
                result = server_error_exception(RpcError(JsonNumber(str(number)), "UNTRUSTED", code, "not-applied"))
                self.assertIsInstance(result, exception)
                self.assertNotIn("UNTRUSTED", str(result))


if __name__ == "__main__":
    unittest.main()
