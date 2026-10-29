"""I03 DTO validation protects public models from malformed peer results."""

import copy
import unittest

from minebridge import errors
from minebridge._protocol import (
    CodecError, JsonNumber, RpcError, decode_request, decode_response,
    encode_frame, server_error_exception,
)

ALICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BOB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PLAYER = {"uuid": ALICE, "name": "Alice", "entityId": 12}


def response(method, result):
    return decode_response(encode_frame({
        "jsonrpc": "2.0", "id": 7, "result": result,
    }).rstrip(b"\n"), 7, method)


class PlayerProtocolTests(unittest.TestCase):
    def test_valid_public_results_preserve_numbers_and_empty_groups(self):
        cases = [
            ("players.get", {"player": PLAYER}),
            ("players.list", {"players": [PLAYER]}),
            ("players.list", {"players": []}),
            ("players.getPos", {"location": {
                "world": "world", "x": -1.25, "y": 80, "z": 0.5, "yaw": 90, "pitch": 0,
            }}),
            ("players.teleport", {"matched": 0, "applied": 0, "targets": []}),
            ("players.teleport", {"matched": 2, "applied": 1, "targets": [
                {"uuid": ALICE, "applied": True, "code": None},
                {"uuid": BOB, "applied": False, "code": "PLAYER_NOT_FOUND"},
            ]}),
            ("chat.post", {"applied": True}),
        ]
        for method, result in cases:
            with self.subTest(method=method, result=result):
                self.assertIsNone(response(method, result).error)

    def test_malformed_player_and_location_results_are_protocol_errors(self):
        for field, value in (("uuid", "Alice"), ("name", ""), ("entityId", True),
                             ("entityId", -1), ("entityId", 1.5)):
            player = dict(PLAYER, **{field: value})
            with self.subTest(field=field, value=value), self.assertRaises(CodecError):
                response("players.get", {"player": player})
        for value in (True, "1", JsonNumber("1e99999")):
            location = {"world": "world", "x": value, "y": 80, "z": 0, "yaw": 0, "pitch": 0}
            with self.subTest(value=value), self.assertRaises(CodecError):
                response("players.getPos", {"location": location})
        with self.assertRaises(CodecError):
            response("players.list", {"players": [PLAYER, PLAYER]})

    def test_partial_result_counts_and_uuid_outcomes_must_agree(self):
        good = {"matched": 1, "applied": 1, "targets": [
            {"uuid": ALICE, "applied": True, "code": None},
        ]}
        for path, value in (("matched", 2), ("applied", 0), ("applied", True),
                            ("uuid", "bad"), ("success", "true"), ("code", "FAILED")):
            result = copy.deepcopy(good)
            if path in ("matched", "applied"):
                result[path] = value
            else:
                result["targets"][0]["applied" if path == "success" else path] = value
            with self.subTest(path=path), self.assertRaises(CodecError):
                response("players.teleport", result)
        with self.assertRaises(CodecError):
            response("players.teleport", {"matched": 2, "applied": 2,
                                          "targets": good["targets"] * 2})

    def test_request_shapes_reject_unusable_executor_and_nonfinite_coordinates(self):
        base = {"world": "world", "executor": None, "targets": "@a",
                "position": [0.25, 80.5, -1.25], "destinationWorld": None}
        for field, value in (("executor", "Alice"), ("targets", ["Alice"]),
                             ("position", [True, 80, 0]),
                             ("position", [JsonNumber("1e99999"), 80, 0]),
                             ("position", [2147483648, 80, 0]),
                             ("destinationWorld", "")):
            params = dict(base, **{field: value})
            with self.subTest(field=field), self.assertRaises(CodecError) as raised:
                decode_request(encode_frame({"jsonrpc": "2.0", "id": 7,
                                             "method": "players.teleport", "params": params}))
            self.assertEqual(raised.exception.code, "INVALID_PARAMS")

    def test_new_error_codes_map_to_typed_fixed_local_messages(self):
        for number, code, exception in (
            (-32028, "PLAYER_NOT_FOUND", errors.PlayerNotFoundError),
            (-32029, "INVALID_SELECTOR", errors.InvalidSelectorError),
            (-32030, "MISSING_CONTEXT", errors.MissingContextError),
            (-32031, "INVALID_TARGET", errors.InvalidTargetError),
            (-32032, "CONTEXT_WORLD_MISMATCH", errors.ContextWorldMismatchError),
        ):
            with self.subTest(code=code):
                result = server_error_exception(RpcError(
                    JsonNumber(str(number)), "UNTRUSTED-TEXT", code, "not-applied",
                ))
                self.assertIsInstance(result, exception)
                self.assertNotIn("UNTRUSTED-TEXT", str(result))


if __name__ == "__main__":
    unittest.main()
