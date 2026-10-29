"""Exercise the installed Python codec against the shared protocol corpus.

The corpus is a repository test input, not package runtime data. No server or
socket is involved in these tests.
"""

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import traceback
import unittest

from minebridge import errors
from minebridge._protocol import (
    CodecError,
    FrameDecoder,
    JsonNumber,
    MAX_FRAME_BYTES,
    MAX_JSON_DEPTH,
    RpcError,
    decode_request,
    decode_response,
    encode_frame,
    error_frame,
    server_error_exception,
)


CORPUS_PATH = Path(__file__).resolve().parents[2] / "protocol/v2/fixtures/corpus.json"
HELLO_PARAMS = {
    "protocol": {"major": 2, "minor": 0},
    "token": "EXAMPLE-NOT-A-SECRET",
    "world": None,
    "coordinates": "absolute",
}


def hello_request(request_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "system.hello",
        "params": dict(HELLO_PARAMS),
    }


def payload_for(case: dict) -> bytes:
    """Build fixture bytes without adding transport delimiters."""
    if "hex" in case:
        return bytes.fromhex(case["hex"])
    if "construction" in case:
        construction = case["construction"]
        text = (
            construction["prefix"]
            + construction["repeat"] * construction["count"]
            + construction["suffix"]
        )
    else:
        text = case["text"]
    return text.encode("utf-8")


def run_fixture(case: dict):
    payload = payload_for(case)
    mode = case["mode"]
    if mode == "request":
        return decode_request(payload)
    if mode in ("hello-response", "blocks-response"):
        method = "system.hello" if mode == "hello-response" else "blocks.set"
        return decode_response(payload, expected_id=case["expectedId"], method=method)
    if mode == "method-response":
        return decode_response(payload, expected_id=case["expectedId"], method=case["method"])
    if mode == "stream":
        decoder = FrameDecoder()
        frames = []
        offset = 0
        for size in case.get("chunkSizes", []):
            frames.extend(decoder.feed(payload[offset : offset + size]))
            offset += size
        frames.extend(decoder.feed(payload[offset:]))
        if case.get("eof", False):
            decoder.finish()
        return frames
    raise AssertionError(f"Unknown corpus mode: {mode}")


class SharedProtocolCorpusTests(unittest.TestCase):
    def test_every_shared_fixture_has_the_expected_outcome(self) -> None:
        document = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(document["formatVersion"], 1)
        self.assertTrue(document["cases"], "The shared corpus must not be empty")
        names = [case["name"] for case in document["cases"]]
        self.assertEqual(len(names), len(set(names)), "Fixture names must be unique")
        for case in document["cases"]:
            with self.subTest(case=case["name"]):
                expected = case["expect"]
                if expected["kind"] == "failure":
                    with self.assertRaises(CodecError) as raised:
                        run_fixture(case)
                    failure = raised.exception
                    self.assertEqual(failure.code, expected["code"])
                    for field in ("reply", "close"):
                        if field in expected:
                            self.assertEqual(getattr(failure, field), expected[field])
                    if "id" in expected:
                        self.assertEqual(failure.request_id, expected["id"])
                    continue
                actual = run_fixture(case)
                kind = expected["kind"]
                if kind == "frames":
                    self.assertEqual(len(actual), expected["frameCount"])
                    self.assertTrue(all(isinstance(frame, bytes) for frame in actual))
                elif kind in ("request", "notification"):
                    self.assertEqual(actual.is_notification, kind == "notification")
                    if "id" in expected:
                        self.assertEqual(actual.request_id, expected["id"])
                    if "method" in expected:
                        self.assertEqual(actual.method, expected["method"])
                elif kind in ("result", "error"):
                    self.assertEqual(actual.request_id, expected["id"])
                    if kind == "result":
                        self.assertIsNone(actual.error)
                        self.assertIsNotNone(actual.result)
                    else:
                        self.assertIsNone(actual.result)
                        self.assertEqual(actual.error.code, expected["code"])
                else:
                    self.fail(f"Unknown expected outcome: {kind}")


class FrameDecoderTests(unittest.TestCase):
    def test_all_split_points_preserve_utf8_and_crlf(self) -> None:
        payload = json.dumps(
            {"message": "Кириллица, 世界, \U0001f600", "escaped": "first\nsecond"},
            ensure_ascii=False,
        ).encode("utf-8")
        stream = payload + b"\r\n"
        for split in range(len(stream) + 1):
            with self.subTest(split=split):
                decoder = FrameDecoder()
                actual = decoder.feed(stream[:split]) + decoder.feed(stream[split:])
                decoder.finish()
                self.assertEqual(actual, [payload])

    def test_one_byte_chunks_and_coalesced_frames_are_equivalent(self) -> None:
        stream = b'{}\n{"a":1}\r\n\n'
        decoder = FrameDecoder()
        expected = [b"{}", b'{"a":1}', b""]
        actual = []
        for byte in stream:
            actual.extend(decoder.feed(bytes((byte,))))
        decoder.finish()
        self.assertEqual(actual, expected)
        self.assertEqual(FrameDecoder().feed(stream), expected)

    def test_exact_byte_limit_is_accepted_before_lf(self) -> None:
        self.assertEqual(MAX_FRAME_BYTES, 65_536)
        payload = b"x" * MAX_FRAME_BYTES
        decoder = FrameDecoder()
        self.assertEqual(decoder.feed(payload), [])
        self.assertEqual(decoder.feed(b"\n"), [payload])
        decoder.finish()

    def test_carriage_return_counts_toward_byte_limit(self) -> None:
        payload = b"x" * (MAX_FRAME_BYTES - 1)
        self.assertEqual(FrameDecoder().feed(payload + b"\r\n"), [payload])
        decoder = FrameDecoder()
        with self.assertRaises(CodecError) as raised:
            decoder.feed(payload + b"x\r\n")
        self.assertEqual(raised.exception.code, "FRAME_TOO_LARGE")
        self.assertFalse(raised.exception.reply)
        self.assertTrue(raised.exception.close)

    def test_limit_is_per_frame_not_per_read(self) -> None:
        payload = b"x" * MAX_FRAME_BYTES
        self.assertEqual(FrameDecoder().feed((payload + b"\n") * 3), [payload] * 3)

    def test_oversized_unterminated_frame_fails_immediately_and_is_terminal(self) -> None:
        decoder = FrameDecoder()
        self.assertEqual(decoder.feed(b"x" * MAX_FRAME_BYTES), [])
        with self.assertRaises(CodecError) as raised:
            decoder.feed(b"x")
        self.assertEqual(raised.exception.code, "FRAME_TOO_LARGE")
        with self.assertRaises(CodecError) as terminal:
            decoder.feed(b"\n{}\n")
        self.assertEqual(terminal.exception.code, "DECODER_CLOSED")

    def test_partial_eof_never_emits_a_frame_and_is_terminal(self) -> None:
        for partial in (b"{", b"\r", b"\xf0\x9f"):
            with self.subTest(partial=partial):
                decoder = FrameDecoder()
                self.assertEqual(decoder.feed(partial), [])
                with self.assertRaises(CodecError) as raised:
                    decoder.finish()
                self.assertEqual(raised.exception.code, "EOF_PARTIAL")
                with self.assertRaises(CodecError) as terminal:
                    decoder.feed(b"\n")
                self.assertEqual(terminal.exception.code, "DECODER_CLOSED")

    def test_clean_eof_closes_decoder(self) -> None:
        decoder = FrameDecoder()
        decoder.finish()
        with self.assertRaises(CodecError) as raised:
            decoder.feed(b"{}\n")
        self.assertEqual(raised.exception.code, "DECODER_CLOSED")


class ProtocolEncodingTests(unittest.TestCase):
    def test_hello_roundtrip_preserves_unicode_and_escaped_linebreaks(self) -> None:
        message = hello_request()
        message["params"]["token"] = "Пример\n世界\U0001f600"
        frame = encode_frame(message)
        self.assertTrue(frame.endswith(b"\n"))
        self.assertEqual(frame.count(b"\n"), 1)
        self.assertFalse(frame.startswith(b"\xef\xbb\xbf"))
        request = decode_request(frame[:-1])
        self.assertEqual(request.request_id, 1)
        self.assertEqual(request.method, "system.hello")
        self.assertEqual(request.params["token"], message["params"]["token"])
        self.assertFalse(request.is_notification)

    def test_blocks_roundtrip_preserves_int32_boundaries(self) -> None:
        message = {
            "jsonrpc": "2.0",
            "id": 9_007_199_254_740_991,
            "method": "blocks.set",
            "params": {
                "world": "world",
                "position": [-2_147_483_648, 0, 2_147_483_647],
                "block": {"key": "minecraft:cobblestone", "states": {}},
            },
        }
        request = decode_request(encode_frame(message)[:-1])
        self.assertEqual(request.request_id, message["id"])
        self.assertEqual(
            [number.text for number in request.params["position"]],
            ["-2147483648", "0", "2147483647"],
        )

    def test_outbound_nonfinite_numbers_are_rejected(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(CodecError):
                encode_frame({"value": value})

    def test_outbound_cycles_are_rejected(self) -> None:
        cyclic = {}
        cyclic["self"] = cyclic
        with self.assertRaises(CodecError):
            encode_frame(cyclic)

    def test_outbound_custom_mapping_cannot_emit_duplicate_keys(self) -> None:
        class DuplicateItems(dict):
            def items(self):
                return (("duplicate", 1), ("duplicate", 2))

        for message in (DuplicateItems(), {"nested": DuplicateItems()}):
            with self.subTest(nested=type(message) is dict):
                with self.assertRaises(CodecError) as raised:
                    encode_frame(message)
                self.assertEqual(raised.exception.code, "ENCODING_ERROR")

    def test_integer_subclass_cannot_replace_numeric_json_with_custom_text(self) -> None:
        class MisleadingInteger(int):
            def __str__(self) -> str:
                return "NaN"

        message = {
            "jsonrpc": "2.0", "id": 1, "method": "future.operation",
            "params": {"value": MisleadingInteger(1)},
        }
        request = decode_request(encode_frame(message)[:-1])
        self.assertEqual(request.params["value"].text, "1")

    def test_outbound_unpaired_surrogates_are_rejected_in_keys_and_values(self) -> None:
        for message in ({"value": "\ud800"}, {"\udfff": "value"}):
            with self.subTest(message=ascii(message)), self.assertRaises(CodecError):
                encode_frame(message)

    def test_outbound_size_is_measured_in_utf8_bytes(self) -> None:
        frame = encode_frame({"value": "я" * 16_000})
        self.assertLessEqual(len(frame) - 1, MAX_FRAME_BYTES)
        with self.assertRaises(CodecError) as raised:
            encode_frame({"value": "я" * MAX_FRAME_BYTES})
        self.assertEqual(raised.exception.code, "FRAME_TOO_LARGE")

    def test_outbound_container_depth_counts_root_as_one(self) -> None:
        self.assertEqual(MAX_JSON_DEPTH, 16)
        message = {}
        cursor = message
        for _ in range(MAX_JSON_DEPTH - 1):
            child = {}
            cursor["nested"] = child
            cursor = child
        encode_frame(message)
        cursor["nested"] = {}
        with self.assertRaises(CodecError) as raised:
            encode_frame(message)
        self.assertEqual(raised.exception.code, "JSON_TOO_DEEP")

    def test_decoded_number_retains_lexical_form_without_float_rounding(self) -> None:
        response = decode_response(
            b'{"jsonrpc":"2.0","id":2,"result":{"applied":true,"future":1e9999}}',
            expected_id=2,
            method="blocks.set",
        )
        self.assertIsInstance(response.result["future"], JsonNumber)
        self.assertEqual(response.result["future"].text, "1e9999")

    def test_json_number_is_immutable(self) -> None:
        number = JsonNumber("1.0")
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            number.text = "2"


class ProtocolErrorMappingTests(unittest.TestCase):
    ERROR_TYPES = (
        (-32700, "PARSE_ERROR", "ProtocolError"),
        (-32600, "INVALID_REQUEST", "ProtocolError"),
        (-32601, "METHOD_NOT_FOUND", "UnsupportedFeatureError"),
        (-32602, "INVALID_PARAMS", "InvalidArgumentError"),
        (-32603, "INTERNAL_ERROR", "ServerOperationError"),
        (-32001, "AUTH_FAILED", "AuthenticationError"),
        (-32002, "PROTOCOL_VERSION", "ProtocolVersionError"),
        (-32003, "NOT_READY", "ProtocolError"),
        (-32004, "INVALID_STATE", "ProtocolError"),
        (-32010, "LIMIT_EXCEEDED", "LimitExceededError"),
        (-32020, "WORLD_NOT_FOUND", "WorldNotFoundError"),
        (-32021, "PERMISSION_DENIED", "PermissionDeniedError"),
        (-32022, "COORDINATE_OUT_OF_BOUNDS", "CoordinateOutOfBoundsError"),
        (-32023, "CHUNK_NOT_LOADED", "ChunkNotLoadedError"),
        (-32024, "INVALID_BLOCK", "InvalidBlockError"),
        (-32025, "UNSUPPORTED_FEATURE", "UnsupportedFeatureError"),
    )

    def test_known_error_frames_roundtrip_and_map_to_public_exception_classes(self) -> None:
        for numeric, machine_code, class_name in self.ERROR_TYPES:
            with self.subTest(machine_code=machine_code):
                frame = error_frame(2, machine_code)
                response = decode_response(frame[:-1], expected_id=2, method="blocks.set")
                self.assertEqual(response.error.numeric_code.text, str(numeric))
                self.assertEqual(response.error.code, machine_code)
                self.assertEqual(response.error.outcome, "not-applied")
                exception = server_error_exception(response.error)
                self.assertIs(type(exception), getattr(errors, class_name))
                self.assertIsInstance(exception, errors.MinecraftError)
                self.assertEqual(exception.code, machine_code)
                self.assertEqual(exception.outcome, "not-applied")

    def test_unknown_code_remains_classified_without_message_matching(self) -> None:
        error = RpcError(JsonNumber("-32111"), "AUTH_FAILED", "FUTURE_ERROR", "unknown")
        exception = server_error_exception(error)
        self.assertIs(type(exception), errors.MinecraftError)
        self.assertEqual(exception.code, "FUTURE_ERROR")
        self.assertEqual(exception.outcome, "unknown")

    def test_chunk_error_has_useful_fixed_message_without_peer_text(self) -> None:
        error = RpcError(JsonNumber("-32023"), "sensitive peer text", "CHUNK_NOT_LOADED", "not-applied")
        exception = server_error_exception(error)
        self.assertIn("chunk is not loaded", str(exception))
        self.assertNotIn("sensitive peer text", str(exception))

    def test_protocol_version_exception_is_a_protocol_error(self) -> None:
        self.assertTrue(issubclass(errors.ProtocolVersionError, errors.ProtocolError))

    def test_unknown_outcome_is_preserved_without_claiming_rollback(self) -> None:
        frame = error_frame(2, "INTERNAL_ERROR", outcome="unknown")
        response = decode_response(frame[:-1], expected_id=2, method="blocks.set")
        exception = server_error_exception(response.error)
        self.assertIs(type(exception), errors.ServerOperationError)
        self.assertEqual(exception.outcome, "unknown")

    def test_null_id_is_retained_for_uncorrelatable_parse_error(self) -> None:
        frame = error_frame(None, "PARSE_ERROR")
        response = decode_response(frame[:-1], expected_id=None, method="blocks.set")
        self.assertIsNone(response.request_id)
        self.assertEqual(response.error.code, "PARSE_ERROR")


class ProtocolSecretRedactionTests(unittest.TestCase):
    def test_request_representation_does_not_disclose_token(self) -> None:
        secret = "TEST-SENSITIVE-" + "token-value"
        message = hello_request()
        message["params"]["token"] = secret
        request = decode_request(encode_frame(message)[:-1])
        self.assertEqual(request.params["token"], secret)
        self.assertNotIn(secret, repr(request))
        self.assertNotIn(secret, str(request))

    def test_remote_error_message_and_result_are_not_in_representations(self) -> None:
        secret = "TEST-SENSITIVE-" + "remote-value"
        error_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {
                "code": -32603,
                "message": secret,
                "data": {"code": "INTERNAL_ERROR", "outcome": "unknown"},
            },
        }
        response = decode_response(
            encode_frame(error_response)[:-1], expected_id=2, method="blocks.set"
        )
        exception = server_error_exception(response.error)
        for representation in (
            repr(response), str(response), repr(response.error), str(response.error),
            repr(exception), str(exception),
        ):
            self.assertNotIn(secret, representation)
        result_response = {
            "jsonrpc": "2.0", "id": 2,
            "result": {"applied": True, "future": secret},
        }
        result = decode_response(
            encode_frame(result_response)[:-1], expected_id=2, method="blocks.set"
        )
        self.assertNotIn(secret, repr(result))

    def test_parse_and_shape_errors_do_not_include_input_or_parser_causes(self) -> None:
        secret = "TEST-SENSITIVE-" + "bad-input"
        valid = hello_request()
        valid["params"]["token"] = secret
        valid["params"]["typo"] = secret
        invalid_inputs = (
            ('{"token":"' + secret + '",').encode("utf-8"),
            encode_frame(valid)[:-1],
            ('{"token":"' + secret + '"}').encode("utf-8") + b"\xff",
        )
        for payload in invalid_inputs:
            with self.subTest(payload_length=len(payload)):
                try:
                    decode_request(payload)
                except CodecError as failure:
                    formatted = "".join(traceback.format_exception(failure))
                    self.assertNotIn(secret, str(failure))
                    self.assertNotIn(secret, repr(failure))
                    self.assertNotIn(secret, formatted)
                    self.assertNotIn("JSONDecodeError", formatted)
                    self.assertNotIn("UnicodeDecodeError", formatted)
                    self.assertIsNone(failure.__cause__)
                else:
                    self.fail("Malformed input was accepted")


if __name__ == "__main__":
    unittest.main()
