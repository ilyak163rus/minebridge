"""Internal protocol 1.0 codec. No sockets, authorization or world access.

Numbers retain their spelling until a field is validated. Request/response
representations and diagnostics intentionally omit peer-controlled content.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import math
import re
from typing import Literal

from . import errors

MAX_FRAME_BYTES = 65536
MAX_JSON_DEPTH = 16
MAX_ID = 9007199254740991
_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)\Z", re.ASCII)
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z", re.ASCII)
_KEY = re.compile(r"[a-z0-9_.-]+:[a-z0-9/._-]+\Z", re.ASCII)
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z", re.ASCII)

# A single table drives safe errors and client exception classification.
ERROR_CODES = {
    -32700: "PARSE_ERROR", -32600: "INVALID_REQUEST",
    -32601: "METHOD_NOT_FOUND", -32602: "INVALID_PARAMS",
    -32603: "INTERNAL_ERROR", -32001: "AUTH_FAILED",
    -32002: "PROTOCOL_VERSION", -32003: "NOT_READY",
    -32004: "INVALID_STATE", -32010: "LIMIT_EXCEEDED",
    -32020: "WORLD_NOT_FOUND", -32021: "PERMISSION_DENIED",
    -32022: "COORDINATE_OUT_OF_BOUNDS", -32023: "CHUNK_NOT_LOADED",
    -32024: "INVALID_BLOCK", -32025: "UNSUPPORTED_FEATURE",
}
_ERROR_TYPES = {
    "PARSE_ERROR": errors.ProtocolError,
    "INVALID_REQUEST": errors.ProtocolError,
    "METHOD_NOT_FOUND": errors.UnsupportedFeatureError,
    "INVALID_PARAMS": errors.InvalidArgumentError,
    "INTERNAL_ERROR": errors.ServerOperationError,
    "AUTH_FAILED": errors.AuthenticationError,
    "PROTOCOL_VERSION": errors.ProtocolVersionError,
    "NOT_READY": errors.ProtocolError,
    "INVALID_STATE": errors.ProtocolError,
    "LIMIT_EXCEEDED": errors.LimitExceededError,
    "WORLD_NOT_FOUND": errors.WorldNotFoundError,
    "PERMISSION_DENIED": errors.PermissionDeniedError,
    "COORDINATE_OUT_OF_BOUNDS": errors.CoordinateOutOfBoundsError,
    "CHUNK_NOT_LOADED": errors.ChunkNotLoadedError,
    "INVALID_BLOCK": errors.InvalidBlockError,
    "UNSUPPORTED_FEATURE": errors.UnsupportedFeatureError,
}
_COUNT_LIMITS = (
    "maxFrameBytes", "maxJsonDepth", "maxSessions", "maxQueuedRequests",
    "maxOutputFrames", "maxOperationsPerTick", "maxOperationsPerSessionPerTick",
)
_TIME_LIMITS = (
    "handshakeTimeoutSeconds", "frameAssemblyTimeoutSeconds",
    "writeTimeoutSeconds", "executorBudgetMillis",
)


class CodecError(Exception):
    """Safe codec failure; caller owns any reply/connection operation."""

    def __init__(self, code: str, request_id: int | None = None, *,
                 reply: bool = False, close: bool = True) -> None:
        super().__init__(f"Protocol input rejected ({code})")
        self.code = code
        self.request_id = request_id
        self.reply = reply
        self.close = close


@dataclass(frozen=True, slots=True)
class JsonNumber:
    """A JSON number token; never an implicit float or coerced integer."""

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or _NUMBER.fullmatch(self.text) is None:
            raise ValueError("Invalid JSON number token")


@dataclass(frozen=True, slots=True, repr=False)
class Request:
    request_id: int | None
    method: str
    params: dict[str, object] = field(repr=False)

    @property
    def is_notification(self) -> bool:
        return self.request_id is None

    def __repr__(self) -> str:
        return f"Request(id={self.request_id}, notification={self.is_notification})"


@dataclass(frozen=True, slots=True, repr=False)
class RpcError:
    numeric_code: JsonNumber
    message: str
    code: str
    outcome: Literal["not-applied", "unknown"]

    def __repr__(self) -> str:
        return f"RpcError(outcome={self.outcome!r})"


@dataclass(frozen=True, slots=True, repr=False)
class Response:
    request_id: int | None
    result: dict[str, object] | None = field(default=None, repr=False)
    error: RpcError | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        return f"Response(id={self.request_id}, error={self.error is not None})"


class FrameDecoder:
    """Bounded LF framing independent of read boundaries and UTF-8 boundaries.

    A failed feed returns no frames from that call and permanently closes the
    decoder. EOF discards an incomplete frame; it is never emitted as a request.
    """

    def __init__(self) -> None:
        self._pending = bytearray()
        self._closed = False

    def feed(self, chunk: bytes) -> list[bytes]:
        if self._closed:
            raise CodecError("DECODER_CLOSED")
        if not isinstance(chunk, bytes):
            raise TypeError("Frame input must be bytes")
        frames: list[bytes] = []
        offset = 0
        while offset < len(chunk):
            end = chunk.find(b"\n", offset)
            stop = end if end >= 0 else len(chunk)
            length = stop - offset
            if len(self._pending) + length > MAX_FRAME_BYTES:
                self._closed = True
                self._pending.clear()
                raise CodecError("FRAME_TOO_LARGE")
            self._pending.extend(chunk[offset:stop])
            if end < 0:
                break
            payload = bytes(self._pending)
            self._pending.clear()
            frames.append(payload[:-1] if payload.endswith(b"\r") else payload)
            offset = end + 1
        return frames

    def finish(self) -> None:
        if self._closed:
            raise CodecError("DECODER_CLOSED")
        self._closed = True
        partial = bool(self._pending)
        self._pending.clear()
        if partial:
            raise CodecError("EOF_PARTIAL")


def _reject(code: str, request_id: int | None = None) -> None:
    raise CodecError(code, request_id, reply=code != "INVALID_RESPONSE",
                     close=code in ("PARSE_ERROR", "INVALID_REQUEST", "INVALID_RESPONSE"))


def _valid_unicode(text: str) -> bool:
    return all(not 0xD800 <= ord(character) <= 0xDFFF for character in text)


def _depth_guard(text: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise CodecError("JSON_TOO_DEEP")
        elif char in "}]":
            depth -= 1


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result or not _valid_unicode(key):
            _reject("PARSE_ERROR")
        result[key] = value
    return result


def _no_constant(_: str) -> None:
    _reject("PARSE_ERROR")


def _check_strings(value: object) -> None:
    if isinstance(value, str) and not _valid_unicode(value):
        _reject("PARSE_ERROR")
    if isinstance(value, dict):
        for nested in value.values():
            _check_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            _check_strings(nested)


def _parse(payload: bytes) -> object:
    if not isinstance(payload, bytes):
        raise TypeError("Payload must be bytes")
    if len(payload) > MAX_FRAME_BYTES:
        raise CodecError("FRAME_TOO_LARGE")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise CodecError("INVALID_UTF8") from None
    if text.startswith("\ufeff"):
        _reject("PARSE_ERROR")
    _depth_guard(text)
    try:
        value = json.loads(text, object_pairs_hook=_pairs,
                           parse_int=JsonNumber, parse_float=JsonNumber,
                           parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise CodecError("PARSE_ERROR", reply=True) from None
    _check_strings(value)
    return value


def _integer(value: object) -> bool:
    return isinstance(value, JsonNumber) and _INTEGER.fullmatch(value.text) is not None


def _nonnegative_integer(value: object) -> bool:
    return _integer(value) and (not value.text.startswith("-") or value.text == "-0")


def _positive_number(value: object) -> bool:
    if not isinstance(value, JsonNumber) or value.text.startswith("-"):
        return False
    mantissa = value.text.lower().split("e", 1)[0]
    return any(char in "123456789" for char in mantissa)


def _bounded_integer(value: object, lower: int, upper: int) -> int | None:
    if not _integer(value):
        return None
    text = value.text
    # Bound before int() so huge wire integers never hit Python's digit limit.
    if len(text.lstrip("-")) > max(len(str(abs(lower))), len(str(abs(upper)))):
        return None
    number = int(text)
    return number if lower <= number <= upper else None


def _identifier(value: object) -> int | None:
    return _bounded_integer(value, 1, MAX_ID)


def _exact(value: object, keys: set[str], request_id: int | None) -> dict[str, object]:
    if not isinstance(value, dict) or value.keys() != keys:
        _reject("INVALID_PARAMS", request_id)
    return value


def _request_params(method: str, params: dict[str, object], request_id: int) -> None:
    if method == "system.hello":
        _exact(params, {"protocol", "token", "world", "coordinates"}, request_id)
        protocol = _exact(params["protocol"], {"major", "minor"}, request_id)
        if not all(_nonnegative_integer(protocol[key]) for key in ("major", "minor")):
            _reject("INVALID_PARAMS", request_id)
        if (not isinstance(params["token"], str)
                or not (params["world"] is None or isinstance(params["world"], str))
                or not isinstance(params["coordinates"], str)):
            _reject("INVALID_PARAMS", request_id)
        if params["coordinates"] != "absolute":
            _reject("UNSUPPORTED_FEATURE", request_id)
    elif method == "blocks.set":
        _exact(params, {"world", "position", "block"}, request_id)
        position = params["position"]
        if (not isinstance(params["world"], str) or not isinstance(position, list)
                or len(position) != 3
                or any(_bounded_integer(value, -2147483648, 2147483647) is None for value in position)):
            _reject("INVALID_PARAMS", request_id)
        block = _exact(params["block"], {"key", "states"}, request_id)
        if not isinstance(block["key"], str) or not isinstance(block["states"], dict):
            _reject("INVALID_PARAMS", request_id)
        if _KEY.fullmatch(block["key"]) is None:
            _reject("INVALID_BLOCK", request_id)
        if block["states"]:
            _reject("UNSUPPORTED_FEATURE", request_id)


def decode_request(payload: bytes) -> Request:
    value = _parse(payload)
    if not isinstance(value, dict):
        _reject("INVALID_REQUEST")
    request_id = _identifier(value.get("id"))
    if (value.get("jsonrpc") != "2.0" or not isinstance(value.get("method"), str)
            or not isinstance(value.get("params"), dict)):
        _reject("INVALID_REQUEST", request_id)
    if "id" in value and request_id is None:
        _reject("INVALID_REQUEST")
    # Valid notifications are never domain-validated or dispatched.
    if request_id is not None:
        _request_params(value["method"], value["params"], request_id)
    return Request(request_id, value["method"], value["params"])


def _hello_result(result: dict[str, object]) -> bool:
    required = {"protocol", "sessionId", "pluginVersion", "serverVersion", "world",
                "coordinates", "chunkPolicy", "applyPhysics", "capabilities", "limits"}
    if not required <= result.keys():
        return False
    protocol, world, limits = result["protocol"], result["world"], result["limits"]
    if not isinstance(protocol, dict) or not isinstance(world, dict) or not isinstance(limits, dict):
        return False
    if (_bounded_integer(protocol.get("major"), 1, 1) != 1
            or _bounded_integer(protocol.get("minor"), 0, 0) != 0):
        return False
    for value in (result["sessionId"], world.get("uuid")):
        if not isinstance(value, str) or _UUID.fullmatch(value) is None:
            return False
    for value in (result["pluginVersion"], result["serverVersion"], world.get("name")):
        if not isinstance(value, str) or not value.strip():
            return False
    minimum = _bounded_integer(world.get("minY"), -2147483648, 2147483647)
    maximum = _bounded_integer(world.get("maxYExclusive"), -2147483648, 2147483647)
    if minimum is None or maximum is None or minimum >= maximum:
        return False
    capabilities = result["capabilities"]
    if (result["coordinates"] != "absolute" or result["chunkPolicy"] != "loaded-only"
            or result["applyPhysics"] is not True or not isinstance(capabilities, list)
            or not all(isinstance(capability, str) for capability in capabilities)
            or "blocks.set" not in capabilities):
        return False
    if any(not _nonnegative_integer(limits.get(key)) or not _positive_number(limits[key])
           for key in _COUNT_LIMITS):
        return False
    return all(_positive_number(limits.get(key)) for key in _TIME_LIMITS)


def _rpc_error(value: object) -> RpcError:
    if not isinstance(value, dict) or not _integer(value.get("code")) or not isinstance(value.get("message"), str):
        _reject("INVALID_RESPONSE")
    data = value.get("data")
    if (not isinstance(data, dict) or not isinstance(data.get("code"), str)
            or not data["code"] or data.get("outcome") not in ("not-applied", "unknown")):
        _reject("INVALID_RESPONSE")
    known = next((name for number, name in ERROR_CODES.items()
                  if value["code"].text == str(number)), None)
    if known is not None and known != data["code"]:
        _reject("INVALID_RESPONSE")
    return RpcError(value["code"], value["message"], data["code"], data["outcome"])


def decode_response(payload: bytes, expected_id: int | None, method: str) -> Response:
    value = _parse(payload)
    if (not isinstance(value, dict) or value.get("jsonrpc") != "2.0" or "id" not in value
            or ("result" in value) == ("error" in value)):
        _reject("INVALID_RESPONSE")
    request_id = _identifier(value["id"])
    if value["id"] is None:
        if expected_id is not None or "error" not in value:
            _reject("INVALID_RESPONSE")
    elif request_id is None or type(expected_id) is not int or request_id != expected_id:
        _reject("INVALID_RESPONSE")
    if "error" in value:
        return Response(request_id, error=_rpc_error(value["error"]))
    result = value["result"]
    if not isinstance(result, dict):
        _reject("INVALID_RESPONSE")
    if method == "system.hello":
        valid = _hello_result(result)
    else:
        valid = method == "blocks.set" and result.get("applied") is True
    if not valid:
        _reject("INVALID_RESPONSE")
    return Response(request_id, result=result)


def _json_chunks(value: object, depth: int, seen: set[int]):
    if value is None:
        yield "null"
    elif isinstance(value, bool):
        yield "true" if value else "false"
    elif isinstance(value, JsonNumber):
        text = value.text
        if _NUMBER.fullmatch(text) is None:
            raise CodecError("ENCODING_ERROR")
        yield text
    elif isinstance(value, str):
        if not _valid_unicode(value):
            raise CodecError("ENCODING_ERROR")
        if len(value) > MAX_FRAME_BYTES:
            raise CodecError("FRAME_TOO_LARGE")
        yield json.dumps(value, ensure_ascii=False)
    elif isinstance(value, int):
        try:
            text = int.__repr__(value)
        except ValueError:
            raise CodecError("ENCODING_ERROR") from None
        yield text
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise CodecError("ENCODING_ERROR")
        yield json.dumps(value, allow_nan=False)
    elif isinstance(value, (Mapping, list, tuple)):
        if depth >= MAX_JSON_DEPTH:
            raise CodecError("JSON_TOO_DEEP")
        identity = id(value)
        if identity in seen:
            raise CodecError("ENCODING_ERROR")
        seen.add(identity)
        try:
            if isinstance(value, Mapping):
                yield "{"
                keys: set[str] = set()
                for index, (key, nested) in enumerate(value.items()):
                    if not isinstance(key, str) or key in keys:
                        raise CodecError("ENCODING_ERROR")
                    keys.add(key)
                    if index:
                        yield ","
                    yield from _json_chunks(key, depth + 1, seen)
                    yield ":"
                    yield from _json_chunks(nested, depth + 1, seen)
                yield "}"
            else:
                yield "["
                for index, nested in enumerate(value):
                    if index:
                        yield ","
                    yield from _json_chunks(nested, depth + 1, seen)
                yield "]"
        finally:
            seen.remove(identity)
    else:
        raise CodecError("ENCODING_ERROR")


def encode_frame(value: Mapping[str, object]) -> bytes:
    if not isinstance(value, Mapping):
        raise CodecError("ENCODING_ERROR")
    output = bytearray()
    for text in _json_chunks(value, 0, set()):
        chunk = text.encode("utf-8", errors="strict")
        if len(output) + len(chunk) > MAX_FRAME_BYTES:
            raise CodecError("FRAME_TOO_LARGE")
        output.extend(chunk)
    payload = bytes(output)
    try:
        _parse(payload)
    except CodecError:
        raise CodecError("ENCODING_ERROR") from None
    return payload + b"\n"


def error_frame(request_id: int | None, code: str, *,
                outcome: Literal["not-applied", "unknown"] = "not-applied") -> bytes:
    number = next((number for number, name in ERROR_CODES.items() if name == code), None)
    if (number is None or outcome not in ("not-applied", "unknown")
            or (request_id is not None and (type(request_id) is not int or not 1 <= request_id <= MAX_ID))):
        raise CodecError("ENCODING_ERROR")
    return encode_frame({"jsonrpc": "2.0", "id": request_id, "error": {
        "code": number, "message": "Request rejected", "data": {"code": code, "outcome": outcome}}})


def server_error_exception(error: RpcError) -> errors.MinecraftError:
    # Classify the numeric protocol code, never a peer-supplied message/name alone.
    known = next((name for number, name in ERROR_CODES.items()
                  if error.numeric_code.text == str(number)), None)
    exception_type = _ERROR_TYPES.get(known, errors.MinecraftError)
    return exception_type("Server operation failed", code=error.code, outcome=error.outcome)
