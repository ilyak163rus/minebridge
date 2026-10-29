"""Internal protocol 2.0 codec. No sockets, authorization or world access.

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
EVENT_TYPES = frozenset(("chat.message", "block.interact", "block.break", "block.place", "entity.attack",
                         "entity.damage", "player.damage", "player.enter_lava", "player.join", "player.quit",
                         "player.death", "player.respawn", "projectile.shot", "projectile.hit"))

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
    -32026: "REGION_BUSY", -32027: "CHUNK_LOAD_FAILED",
    -32028: "PLAYER_NOT_FOUND", -32029: "INVALID_SELECTOR",
    -32030: "MISSING_CONTEXT", -32031: "INVALID_TARGET",
    -32032: "CONTEXT_WORLD_MISMATCH",
    -32033: "INVALID_ITEM", -32034: "INVALID_EFFECT",
    -32035: "INVALID_ENTITY_TYPE", -32036: "UNSUPPORTED_ENTITY_TYPE",
    -32037: "ENTITY_NOT_FOUND",
    -32038: "INVALID_GAME_MODE", -32039: "INVALID_GAME_RULE",
    -32040: "INVALID_RULE_VALUE", -32041: "INVALID_PLAYER_VALUE",
    -32042: "INVALID_WEATHER", -32043: "WORLD_CHANGE_REJECTED",
    -32044: "INVALID_EVENT_TYPE", -32045: "SUBSCRIPTION_NOT_FOUND",
    -32046: "EVENT_HISTORY_LOST", -32047: "EVENT_QUEUE_OVERFLOW",
    -32048: "INVENTORY_NOT_FOUND", -32049: "INVENTORY_CHANGED",
    -32050: "INVALID_SLOT", -32051: "INVALID_ITEM_AMOUNT", -32052: "INVENTORY_WRITE_REJECTED",
    -32053: "PEACEFUL_SPAWN_BLOCKED",
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
    "REGION_BUSY": errors.RegionBusyError,
    "CHUNK_LOAD_FAILED": errors.ChunkLoadError,
    "PLAYER_NOT_FOUND": errors.PlayerNotFoundError,
    "INVALID_SELECTOR": errors.InvalidSelectorError,
    "MISSING_CONTEXT": errors.MissingContextError,
    "INVALID_TARGET": errors.InvalidTargetError,
    "CONTEXT_WORLD_MISMATCH": errors.ContextWorldMismatchError,
    "INVALID_ITEM": errors.InvalidItemError,
    "INVALID_EFFECT": errors.InvalidEffectError,
    "INVALID_ENTITY_TYPE": errors.InvalidEntityTypeError,
    "UNSUPPORTED_ENTITY_TYPE": errors.UnsupportedEntityTypeError,
    "ENTITY_NOT_FOUND": errors.EntityNotFoundError,
    "INVALID_GAME_MODE": errors.InvalidGameModeError,
    "INVALID_GAME_RULE": errors.InvalidGameRuleError,
    "INVALID_RULE_VALUE": errors.InvalidRuleValueError,
    "INVALID_PLAYER_VALUE": errors.InvalidPlayerValueError,
    "INVALID_WEATHER": errors.InvalidWeatherError,
    "WORLD_CHANGE_REJECTED": errors.WorldChangeRejectedError,
    "INVALID_EVENT_TYPE": errors.InvalidEventTypeError,
    "SUBSCRIPTION_NOT_FOUND": errors.SubscriptionNotFoundError,
    "EVENT_HISTORY_LOST": errors.EventHistoryLostError,
    "EVENT_QUEUE_OVERFLOW": errors.EventOverflowError,
    "INVENTORY_NOT_FOUND": errors.InventoryNotFoundError,
    "INVENTORY_CHANGED": errors.InventoryChangedError,
    "INVALID_SLOT": errors.InvalidSlotError,
    "INVALID_ITEM_AMOUNT": errors.InvalidItemAmountError,
    "INVENTORY_WRITE_REJECTED": errors.InventoryWriteRejectedError,
    "PEACEFUL_SPAWN_BLOCKED": errors.PeacefulSpawnError,
}
# Human diagnostics are fixed locally: peer messages can contain arbitrary data
# (including tokens), and must never become the text of a public exception.
_ERROR_MESSAGES = {
    "PARSE_ERROR": "Server rejected malformed JSON",
    "INVALID_REQUEST": "Server rejected the request envelope",
    "METHOD_NOT_FOUND": "Server does not support this method",
    "INVALID_PARAMS": "Server rejected the operation arguments",
    "INTERNAL_ERROR": "Server could not complete the operation",
    "AUTH_FAILED": "Server rejected the connection token",
    "PROTOCOL_VERSION": "Client and server protocol versions are incompatible",
    "NOT_READY": "Server session is not ready",
    "INVALID_STATE": "Operation is not allowed in the current session state",
    "LIMIT_EXCEEDED": "Server operation limit was exceeded",
    "WORLD_NOT_FOUND": "Requested world is not available",
    "PERMISSION_DENIED": "Server denied permission for this operation",
    "COORDINATE_OUT_OF_BOUNDS": "Position is outside the world height or border",
    "CHUNK_NOT_LOADED": "Target chunk is not loaded; load it in game before writing",
    "INVALID_BLOCK": "Server rejected the block description",
    "UNSUPPORTED_FEATURE": "Server does not support this feature",
    "REGION_BUSY": "Region is reserved by another construction operation",
    "CHUNK_LOAD_FAILED": "Server could not load or generate the requested chunk",
    "PLAYER_NOT_FOUND": "Requested player is not online",
    "INVALID_SELECTOR": "Server rejected the entity selector",
    "MISSING_CONTEXT": "This selector requires a bound player",
    "INVALID_TARGET": "Operation requires the correct number and type of targets",
    "CONTEXT_WORLD_MISMATCH": "Bound player is outside the selected world",
    "INVALID_ITEM": "Server rejected the item description or amount",
    "INVALID_EFFECT": "Server rejected the effect description",
    "INVALID_ENTITY_TYPE": "Server rejected the entity type",
    "UNSUPPORTED_ENTITY_TYPE": "This entity type cannot be created by the server API",
    "PEACEFUL_SPAWN_BLOCKED": "Cannot spawn this entity because the destination world is in Peaceful difficulty",
    "ENTITY_NOT_FOUND": "Requested entity is no longer available",
    "INVALID_GAME_MODE": "Server rejected the game mode",
    "INVALID_GAME_RULE": "Requested game rule is not available",
    "INVALID_RULE_VALUE": "Server rejected the game rule value",
    "INVALID_PLAYER_VALUE": "Requested player value is outside the allowed range",
    "INVALID_WEATHER": "Server rejected the weather value",
    "WORLD_CHANGE_REJECTED": "Server could not confirm the requested world setting",
    "INVALID_EVENT_TYPE": "Server does not support the requested event type",
    "SUBSCRIPTION_NOT_FOUND": "Requested event subscription is not available",
    "EVENT_HISTORY_LOST": "Requested event history interval is no longer complete; call clearPending to resume",
    "EVENT_QUEUE_OVERFLOW": "Live event delivery lost records; unsubscribe the affected subscription",
    "INVENTORY_NOT_FOUND": "Requested block is not a supported chest",
    "INVENTORY_CHANGED": "Inventory layout no longer matches this reference; resolve it again",
    "INVALID_SLOT": "Requested slot is not public in this inventory",
    "INVALID_ITEM_AMOUNT": "Requested item amount exceeds the allowed slot stack size",
    "INVENTORY_WRITE_REJECTED": "Server could not confirm the requested inventory update",
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


def _control_params(method: str, params: dict[str, object], request_id: int) -> None:
    extra = ({"mode"} if method == "players.setGameMode" else
             {"value"} if method in ("players.setHealth", "players.setFoodLevel") else
             {"effect"} if method == "effects.remove" else set())
    _exact(params, {"world", "executor", "targets"} | extra, request_id)
    _selection_parameters(params, request_id)
    if "mode" in extra:
        if not isinstance(params["mode"], str):
            _reject("INVALID_PARAMS", request_id)
        if params["mode"] not in ("survival", "creative", "adventure", "spectator"):
            _reject("INVALID_GAME_MODE", request_id)
    if "value" in extra:
        value = params["value"]
        if method == "players.setFoodLevel":
            if not _integer(value):
                _reject("INVALID_PARAMS", request_id)
            valid = _bounded_integer(value, 0, 20) is not None
        else:
            if not isinstance(value, JsonNumber):
                _reject("INVALID_PARAMS", request_id)
            valid = _finite_number(value, 0)
        if not valid:
            _reject("INVALID_PLAYER_VALUE", request_id)
    if "effect" in extra:
        effect = _exact(params["effect"], {"key"}, request_id)
        if not isinstance(effect["key"], str):
            _reject("INVALID_PARAMS", request_id)
        if _KEY.fullmatch(effect["key"]) is None:
            _reject("INVALID_EFFECT", request_id)


def _world_params(method: str, params: dict[str, object], request_id: int) -> None:
    keys = {"world"}
    if method == "worlds.setTime":
        keys.add("time")
    elif method == "worlds.setWeather":
        keys.add("weather")
    elif method in ("worlds.getGameRule", "worlds.setGameRule"):
        keys.add("rule")
        if method == "worlds.setGameRule":
            keys.add("value")
    _exact(params, keys, request_id)
    if not _nonblank_text(params["world"]):
        _reject("INVALID_PARAMS", request_id)
    if "time" in keys and _bounded_integer(params["time"], 0, 23999) is None:
        _reject("INVALID_PARAMS", request_id)
    if "weather" in keys:
        if not isinstance(params["weather"], str):
            _reject("INVALID_PARAMS", request_id)
        if params["weather"] not in ("clear", "rain", "thunder"):
            _reject("INVALID_WEATHER", request_id)
    if "rule" in keys and not _nonblank_text(params["rule"], 256):
        _reject("INVALID_PARAMS", request_id)
    if "value" in keys and not _rule_value(params["value"]):
        _reject("INVALID_RULE_VALUE", request_id)


def _rule_value(value: object) -> bool:
    return type(value) is bool or _bounded_integer(value, -2147483648, 2147483647) is not None


def _request_params(method: str, params: dict[str, object], request_id: int) -> None:
    if method.startswith("inventories.") or method == "players.setItem":
        _slot_inventory_params(method, params, request_id)
    elif method.startswith("events."):
        _event_params(method, params, request_id)
    elif method == "system.hello":
        keys = {"protocol", "token", "world", "coordinates"}
        if "logging" in params:
            keys.add("logging")
            if type(params["logging"]) is not bool:
                _reject("INVALID_PARAMS", request_id)
        _exact(params, keys, request_id)
        protocol = _exact(params["protocol"], {"major", "minor"}, request_id)
        if not all(_nonnegative_integer(protocol[key]) for key in ("major", "minor")):
            _reject("INVALID_PARAMS", request_id)
        if (not (params["token"] is None or isinstance(params["token"], str))
                or not (params["world"] is None or isinstance(params["world"], str))
                or not isinstance(params["coordinates"], str)):
            _reject("INVALID_PARAMS", request_id)
        if params["coordinates"] != "absolute":
            _reject("UNSUPPORTED_FEATURE", request_id)
    elif method in ("blocks.set", "blocks.get", "blocks.setRegion", "blocks.getRegion"):
        keys = {"world"}
        keys.update(("from", "to") if method.endswith("Region") else ("position",))
        if method in ("blocks.set", "blocks.setRegion"):
            keys.add("block")
        if method == "blocks.getRegion":
            keys.update(("offset", "limit"))
        _exact(params, keys, request_id)
        if not isinstance(params["world"], str):
            _reject("INVALID_PARAMS", request_id)
        for name in (("from", "to") if method.endswith("Region") else ("position",)):
            if not _position(params[name]):
                _reject("INVALID_PARAMS", request_id)
        if "block" in keys:
            block = _exact(params["block"], {"key", "states"}, request_id)
            if not isinstance(block["key"], str) or not isinstance(block["states"], dict):
                _reject("INVALID_PARAMS", request_id)
            if not _block_spec(block):
                _reject("INVALID_BLOCK", request_id)
        if method == "blocks.getRegion" and (
            _bounded_integer(params["offset"], 0, 262143) is None
            or _bounded_integer(params["limit"], 1, 64) is None
        ):
            _reject("INVALID_PARAMS", request_id)
    elif method in ("players.get", "players.list", "players.getPos", "players.teleport"):
        keys = {"world", "executor", "target" if method == "players.get" else "targets"}
        if method == "players.teleport":
            keys.update(("position", "destinationWorld"))
        _exact(params, keys, request_id)
        if (not _nonblank_text(params["world"])
                or not (params["executor"] is None or _uuid(params["executor"]))):
            _reject("INVALID_PARAMS", request_id)
        target = params["target"] if method == "players.get" else params["targets"]
        if method == "players.get":
            valid_target = _nonblank_text(target, 2048) and not target.startswith("@")
        else:
            valid_target = (_nonblank_text(target, 2048)
                            or isinstance(target, list) and len(target) <= 1024
                            and all(_uuid(value) for value in target))
        if not valid_target:
            _reject("INVALID_PARAMS", request_id)
        if method == "players.teleport" and (
            not isinstance(params["position"], list) or len(params["position"]) != 3
            or not all(_finite_number(value, -2147483648, 2147483647)
                       for value in params["position"])
            or not (params["destinationWorld"] is None
                    or _nonblank_text(params["destinationWorld"]))
        ):
            _reject("INVALID_PARAMS", request_id)
    elif method in ("players.getGameMode", "players.setGameMode", "players.getHealth", "players.setHealth",
                    "players.getFoodLevel", "players.setFoodLevel", "effects.remove", "effects.clear"):
        _control_params(method, params, request_id)
    elif method in ("worlds.getTime", "worlds.setTime", "worlds.getWeather", "worlds.setWeather",
                    "worlds.getGameRule", "worlds.setGameRule"):
        _world_params(method, params, request_id)
    elif method in ("players.giveItem", "effects.add"):
        keys = {"world", "executor", "targets"}
        keys.update(("item", "overflow") if method == "players.giveItem" else ("effect",))
        _exact(params, keys, request_id)
        _selection_parameters(params, request_id)
        if method == "players.giveItem":
            _item_parameters(params["item"], request_id)
            if params["overflow"] not in ("return", "drop"):
                _reject("INVALID_PARAMS", request_id)
        else:
            effect = _exact(params["effect"], {"key", "durationTicks", "level", "particles"}, request_id)
            if (not isinstance(effect["key"], str)
                    or _bounded_integer(effect["durationTicks"], 1, 2147483647) is None
                    or _bounded_integer(effect["level"], 1, 256) is None
                    or type(effect["particles"]) is not bool):
                _reject("INVALID_PARAMS", request_id)
            if _KEY.fullmatch(effect["key"]) is None:
                _reject("INVALID_EFFECT", request_id)
    elif method == "entities.spawn":
        _exact(params, {"world", "destinationWorld", "position", "entity", "options"}, request_id)
        if (not _nonblank_text(params["world"])
                or not (params["destinationWorld"] is None or _nonblank_text(params["destinationWorld"]))
                or not _real_position(params["position"])):
            _reject("INVALID_PARAMS", request_id)
        entity = _exact(params["entity"], {"key"}, request_id)
        if not isinstance(entity["key"], str):
            _reject("INVALID_PARAMS", request_id)
        if _KEY.fullmatch(entity["key"]) is None:
            _reject("INVALID_ENTITY_TYPE", request_id)
        options = _exact(params["options"], {"item", "block", "face", "owner"}, request_id)
        if options["item"] is not None:
            _item_parameters(options["item"], request_id)
        if options["block"] is not None:
            block = _exact(options["block"], {"key", "states"}, request_id)
            if not isinstance(block["key"], str) or not isinstance(block["states"], dict):
                _reject("INVALID_PARAMS", request_id)
            if not _block_spec(block):
                _reject("INVALID_BLOCK", request_id)
        if (options["face"] is not None
                and options["face"] not in ("north", "south", "east", "west", "up", "down")):
            _reject("INVALID_PARAMS", request_id)
        if not (options["owner"] is None or _nonblank_text(options["owner"], 2048)
                and not options["owner"].startswith("@")):
            _reject("INVALID_PARAMS", request_id)
    elif method == "chat.post":
        _exact(params, {"message"}, request_id)
        if not isinstance(params["message"], str) or not 1 <= len(params["message"]) <= 4096:
            _reject("INVALID_PARAMS", request_id)


def _selection_parameters(params: dict[str, object], request_id: int) -> None:
    targets = params["targets"]
    if (not _nonblank_text(params["world"])
            or not (params["executor"] is None or _uuid(params["executor"]))
            or not (_nonblank_text(targets, 2048)
                    or isinstance(targets, list) and len(targets) <= 1024
                    and all(_uuid(value) for value in targets))):
        _reject("INVALID_PARAMS", request_id)


def _item_parameters(value: object, request_id: int) -> None:
    item = _exact(value, {"key", "amount", "name", "lore"}, request_id)
    if not _item_shape(item):
        _reject("INVALID_PARAMS", request_id)
    if _KEY.fullmatch(item["key"]) is None:
        _reject("INVALID_ITEM", request_id)


def _item_shape(value: object) -> bool:
    if not isinstance(value, dict) or value.keys() != {"key", "amount", "name", "lore"}:
        return False
    lore = value["lore"]
    return (isinstance(value["key"], str)
            and _bounded_integer(value["amount"], 1, 2304) is not None
            and (value["name"] is None or isinstance(value["name"], str) and len(value["name"]) <= 256)
            and (lore is None or isinstance(lore, list) and len(lore) <= 16
                 and all(isinstance(line, str) and len(line) <= 256 for line in lore)))


def _item_spec(value: object) -> bool:
    return _item_shape(value) and _KEY.fullmatch(value["key"]) is not None


def _real_position(value: object) -> bool:
    return (isinstance(value, list) and len(value) == 3
            and all(_finite_number(number, -2147483648, 2147483647) for number in value))


def _nonblank_text(value: object, maximum: int | None = None) -> bool:
    return (isinstance(value, str) and bool(value.strip())
            and (maximum is None or len(value) <= maximum))


def _uuid(value: object) -> bool:
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


def _finite_number(value: object, lower: float = -math.inf, upper: float = math.inf) -> bool:
    if not isinstance(value, JsonNumber):
        return False
    try:
        number = float(value.text)
    except (ValueError, OverflowError):
        return False
    return math.isfinite(number) and lower <= number <= upper


def _player(value: object) -> bool:
    return (isinstance(value, dict) and value.keys() == {"uuid", "name", "entityId"}
            and _uuid(value["uuid"]) and _nonblank_text(value["name"])
            and _bounded_integer(value["entityId"], 0, 2147483647) is not None)


def _location(value: object) -> bool:
    return (isinstance(value, dict) and value.keys() == {"world", "x", "y", "z", "yaw", "pitch"}
            and _nonblank_text(value["world"])
            and all(_finite_number(value[key]) for key in ("x", "y", "z", "yaw", "pitch")))


def _target_result(value: dict[str, object]) -> bool:
    if value.keys() != {"matched", "applied", "targets"} or not isinstance(value["targets"], list):
        return False
    rows = value["targets"]
    matched = _bounded_integer(value["matched"], 0, 2147483647)
    applied = _bounded_integer(value["applied"], 0, 2147483647)
    if matched != len(rows) or applied is None or applied > len(rows):
        return False
    identities: set[str] = set()
    successes = 0
    for row in rows:
        if (not isinstance(row, dict) or row.keys() != {"uuid", "applied", "code"}
                or not _uuid(row["uuid"]) or type(row["applied"]) is not bool
                or row["uuid"].lower() in identities):
            return False
        identities.add(row["uuid"].lower())
        if row["applied"]:
            if row["code"] is not None:
                return False
            successes += 1
        elif not _nonblank_text(row["code"]):
            return False
    return successes == applied


def _inventory_result(value: dict[str, object]) -> bool:
    if value.keys() != {"matched", "applied", "targets"} or not isinstance(value["targets"], list):
        return False
    rows = value["targets"]
    expected = {"uuid", "applied", "code", "requested", "given", "leftovers", "dropped"}
    for row in rows:
        if not isinstance(row, dict) or row.keys() != expected:
            return False
        requested = _bounded_integer(row["requested"], 1, 2304)
        given = _bounded_integer(row["given"], 0, 2304)
        dropped = _bounded_integer(row["dropped"], 0, 2304)
        leftovers = row["leftovers"]
        if (requested is None or given is None or dropped is None
                or not isinstance(leftovers, list) or not all(_item_spec(item) for item in leftovers)
                or requested != given + dropped + sum(int(item["amount"].text) for item in leftovers)):
            return False
    return _target_result({"matched": value["matched"], "applied": value["applied"], "targets": [
        {key: row[key] for key in ("uuid", "applied", "code")} for row in rows
    ]})


def _entity_ref(value: object) -> bool:
    return (isinstance(value, dict) and value.keys() == {"uuid", "entityId", "key", "living"}
            and _uuid(value["uuid"])
            and _bounded_integer(value["entityId"], 0, 2147483647) is not None
            and isinstance(value["key"], str) and _KEY.fullmatch(value["key"]) is not None
            and type(value["living"]) is bool)


def _position(value: object) -> bool:
    return (isinstance(value, list) and len(value) == 3
            and all(_bounded_integer(number, -2147483648, 2147483647) is not None for number in value))


def _block_spec(value: object) -> bool:
    if (not isinstance(value, dict) or value.keys() != {"key", "states"}
            or not isinstance(value["key"], str) or _KEY.fullmatch(value["key"]) is None
            or not isinstance(value["states"], dict) or len(value["states"]) > 64):
        return False
    return all(isinstance(name, str) and re.fullmatch(r"[a-z0-9_]{1,64}", name, re.ASCII)
               and isinstance(state, str) and re.fullmatch(r"[a-z0-9_-]{1,128}", state, re.ASCII)
               for name, state in value["states"].items())


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
    if (_bounded_integer(protocol.get("major"), 2, 2) != 2
            or _bounded_integer(protocol.get("minor"), 0, 0) != 0):
        return False
    for value in (result["sessionId"], world.get("uuid")):
        if not isinstance(value, str) or _UUID.fullmatch(value) is None:
            return False
    for value in (result["pluginVersion"], result["serverVersion"], world.get("name")):
        if not isinstance(value, str) or not value.strip():
            return False
    if not isinstance(world.get("key"), str) or _KEY.fullmatch(world["key"]) is None:
        return False
    minimum = _bounded_integer(world.get("minY"), -2147483648, 2147483647)
    maximum = _bounded_integer(world.get("maxYExclusive"), -2147483648, 2147483647)
    if minimum is None or maximum is None or minimum >= maximum:
        return False
    capabilities = result["capabilities"]
    if (result["coordinates"] != "absolute" or result["chunkPolicy"] not in ("loaded-only", "load-generate")
            or result["applyPhysics"] is not True or not isinstance(capabilities, list)
            or not all(isinstance(capability, str) for capability in capabilities)
            or "blocks.set" not in capabilities):
        return False
    if any(not _nonnegative_integer(limits.get(key)) or not _positive_number(limits[key])
           for key in _COUNT_LIMITS):
        return False
    if "eventHistory" in result and not _event_history(result["eventHistory"], world["uuid"]):
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
    if method.startswith("inventories.") or method == "players.setItem":
        valid = _slot_inventory_result(method, result)
    elif method.startswith("events."):
        valid = _event_result(method, result)
    elif method == "system.hello":
        valid = _hello_result(result)
    elif method == "players.get":
        valid = result.keys() == {"player"} and _player(result["player"])
    elif method == "players.list":
        rows = result.get("players")
        valid = (result.keys() == {"players"} and isinstance(rows, list)
                 and all(_player(row) for row in rows))
        if valid:
            identities = [row["uuid"].lower() for row in rows]
            valid = len(set(identities)) == len(identities)
    elif method == "players.getPos":
        valid = result.keys() == {"location"} and _location(result["location"])
    elif method in ("players.teleport", "players.setGameMode", "players.setHealth", "players.setFoodLevel",
                    "effects.remove", "effects.clear"):
        valid = _target_result(result)
    elif method == "players.getGameMode":
        valid = result.keys() == {"mode"} and result["mode"] in ("survival", "creative", "adventure", "spectator")
    elif method == "players.getHealth":
        valid = result.keys() == {"value"} and _finite_number(result["value"], 0)
    elif method == "players.getFoodLevel":
        valid = result.keys() == {"value"} and _bounded_integer(result["value"], 0, 20) is not None
    elif method == "worlds.getTime":
        valid = result.keys() == {"time"} and _bounded_integer(result["time"], 0, 23999) is not None
    elif method == "worlds.getWeather":
        valid = result.keys() == {"weather"} and result["weather"] in ("clear", "rain", "thunder")
    elif method == "worlds.getGameRule":
        valid = (result.keys() == {"rule", "value"} and _nonblank_text(result["rule"], 256)
                 and _rule_value(result["value"]))
    elif method in ("worlds.setTime", "worlds.setWeather", "worlds.setGameRule"):
        valid = result.keys() == {"applied"} and result["applied"] is True
    elif method == "effects.add":
        valid = _target_result(result)
    elif method == "players.giveItem":
        valid = _inventory_result(result)
    elif method == "entities.spawn":
        valid = result.keys() == {"entity"} and _entity_ref(result["entity"])
    elif method == "chat.post":
        valid = result.keys() == {"applied"} and result["applied"] is True
    elif method == "blocks.get":
        valid = _block_spec(result.get("block"))
    elif method == "blocks.getRegion":
        rows = result.get("blocks")
        valid = (isinstance(rows, list) and 1 <= len(rows) <= 64
                 and _bounded_integer(result.get("total"), 1, 262144) is not None
                 and (result.get("nextOffset") is None
                      or _bounded_integer(result.get("nextOffset"), 1, 262143) is not None)
                 and "nextOffset" in result
                 and all(isinstance(row, dict) and _position(row.get("position"))
                         and _block_spec(row.get("block")) for row in rows))
    else:
        valid = method in ("blocks.set", "blocks.setRegion") and result.get("applied") is True
    if not valid:
        _reject("INVALID_RESPONSE")
    return Response(request_id, result=result)


_EQUIPMENT_SLOTS = ("head", "chest", "legs", "feet", "off_hand")
_INVENTORY_METHODS = frozenset(("inventories.ofBlock", "inventories.ofPlayer", "inventories.getItem",
                              "inventories.getContents", "inventories.setItem", "inventories.clear", "players.setItem"))


def _slot_value(value: object) -> int | str | None:
    if isinstance(value, str):
        return value if value in _EQUIPMENT_SLOTS else None
    return _bounded_integer(value, -2147483648, 2147483647)


def _inventory_slot(value: object, size: int) -> bool:
    slot = _slot_value(value)
    if size == 41:
        return isinstance(slot, str) or type(slot) is int and 0 <= slot <= 35
    return type(slot) is int and 0 <= slot < size


def _inventory_reference(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    kind = value.get("kind")
    size = _bounded_integer(value.get("size"), 1, 54)
    slots = value.get("slots")
    if not isinstance(slots, list):
        return False
    if kind == "player":
        return (value.keys() == {"kind", "player", "size", "slots"} and _uuid(value["player"])
                and size == 41 and [_slot_value(slot) for slot in slots] == list(range(36)) + list(_EQUIPMENT_SLOTS))
    if (kind != "chest" or value.keys() != {"kind", "world", "position", "combined", "size", "slots", "layout"}
            or not _uuid(value["world"]) or not _position(value["position"])
            or type(value["combined"]) is not bool or size not in (27, 54)
            or [_slot_value(slot) for slot in slots] != list(range(size))):
        return False
    layout = value["layout"]
    if (not isinstance(layout, list) or len(layout) != size // 27
            or not value["combined"] and size != 27):
        return False
    positions, keys = [], []
    for index, part in enumerate(layout):
        if (not isinstance(part, dict) or part.keys() != {"position", "offset", "size", "key"}
                or not _position(part["position"]) or _bounded_integer(part["offset"], 0, 27) != index * 27
                or _bounded_integer(part["size"], 27, 27) != 27
                or part["key"] not in ("minecraft:chest", "minecraft:trapped_chest")):
            return False
        positions.append(tuple(int(axis.text) for axis in part["position"]))
        keys.append(part["key"])
    anchor = tuple(int(axis.text) for axis in value["position"])
    return (anchor in positions and len(set(keys)) == 1 and (size == 27 or (
        positions[0][1] == positions[1][1]
        and abs(positions[0][0] - positions[1][0]) + abs(positions[0][2] - positions[1][2]) == 1)))


def _item_view(value: object) -> bool:
    return (value is None or isinstance(value, dict)
            and value.keys() == {"key", "amount", "name", "lore", "hasAdditionalData", "truncated"}
            and isinstance(value["key"], str) and _KEY.fullmatch(value["key"]) is not None
            and _bounded_integer(value["amount"], 1, 2147483647) is not None
            and (value["name"] is None or isinstance(value["name"], str) and len(value["name"]) <= 256)
            and (value["lore"] is None or isinstance(value["lore"], list) and len(value["lore"]) <= 16
                 and all(isinstance(line, str) and len(line) <= 256 for line in value["lore"]))
            and type(value["hasAdditionalData"]) is bool and type(value["truncated"]) is bool)


def _slot_inventory_params(method: str, p: dict[str, object], request_id: int) -> None:
    if method not in _INVENTORY_METHODS:
        return
    if method == "inventories.ofBlock":
        _exact(p, {"world", "destinationWorld", "position", "combined"}, request_id)
        if (not _nonblank_text(p["world"]) or not (p["destinationWorld"] is None or _nonblank_text(p["destinationWorld"]))
                or not _position(p["position"]) or type(p["combined"]) is not bool):
            _reject("INVALID_PARAMS", request_id)
        return
    if method in ("inventories.ofPlayer", "players.setItem"):
        _exact(p, {"world", "executor", "targets"} | ({"slot", "item"} if method == "players.setItem" else set()), request_id)
        _selection_parameters(p, request_id)
        if method == "inventories.ofPlayer":
            return
        size = 41
    else:
        fields = {"inventory"}
        fields.update(("offset", "limit") if method == "inventories.getContents" else ("slot",))
        if method == "inventories.setItem":
            fields.add("item")
        _exact(p, fields, request_id)
        if not _inventory_reference(p["inventory"]):
            _reject("INVALID_PARAMS", request_id)
        size = int(p["inventory"]["size"].text)
        if method == "inventories.getContents":
            if (_bounded_integer(p["offset"], 0, size - 1) is None or _bounded_integer(p["limit"], 1, 54) is None):
                _reject("INVALID_PARAMS", request_id)
            return
    if not (method == "inventories.clear" and p["slot"] is None):
        if not isinstance(p["slot"], str) and not _integer(p["slot"]):
            _reject("INVALID_PARAMS", request_id)
        if not _inventory_slot(p["slot"], size):
            _reject("INVALID_SLOT", request_id)
    if method in ("inventories.setItem", "players.setItem"):
        _item_parameters(p["item"], request_id)


def _slot_inventory_result(method: str, r: dict[str, object]) -> bool:
    if method in ("inventories.ofBlock", "inventories.ofPlayer"):
        return (r.keys() == {"inventory"} and _inventory_reference(r["inventory"])
                and r["inventory"]["kind"] == ("chest" if method == "inventories.ofBlock" else "player"))
    if method == "players.setItem":
        return _target_result(r)
    if method == "inventories.getItem":
        return r.keys() == {"slot", "item"} and _inventory_slot(r["slot"], 54 if not isinstance(r["slot"], str) else 41) and _item_view(r["item"])
    if method == "inventories.setItem":
        return (r.keys() == {"applied", "slot", "previous", "current"} and r["applied"] is True
                and _inventory_slot(r["slot"], 54 if not isinstance(r["slot"], str) else 41)
                and _item_view(r["previous"]) and _item_view(r["current"]))
    if method == "inventories.clear":
        rows = r.get("slots")
        if not (r.keys() == {"applied", "slots"} and r["applied"] is True and isinstance(rows, list) and 1 <= len(rows) <= 54
                and all(_inventory_slot(slot, 54 if not isinstance(slot, str) else 41) for slot in rows)):
            return False
        normalized = [_slot_value(slot) for slot in rows]
        return len(set(normalized)) == len(normalized)
    if method == "inventories.getContents":
        total = _bounded_integer(r.get("total"), 1, 54)
        rows = r.get("items")
        if not (r.keys() == {"items", "total", "nextOffset"} and total in (27, 41, 54) and isinstance(rows, list)
                and 1 <= len(rows) <= total and (r["nextOffset"] is None or _bounded_integer(r["nextOffset"], 1, total - 1) is not None)):
            return False
        if not rows and r["nextOffset"] is not None:
            return False
        normalized = []
        for row in rows:
            if (not isinstance(row, dict) or row.keys() != {"slot", "item"} or not _inventory_slot(row["slot"], total)
                    or not _item_view(row["item"])):
                return False
            normalized.append(_slot_value(row["slot"]))
        return len(set(normalized)) == len(normalized)
    return False


def _event_uuid(value: object) -> bool:
    return _uuid(value) and value == value.lower()


def _event_integer(value: object, lower: int = 0) -> int | None:
    return _bounded_integer(value, lower, MAX_ID)


def _event_cursor(value: object) -> bool:
    return (isinstance(value, dict) and value.keys() == {"epoch", "world", "sequence"}
            and _event_uuid(value["epoch"]) and _event_uuid(value["world"])
            and _event_integer(value["sequence"]) is not None)


def _event_history(value: object, world: object) -> bool:
    if (not isinstance(value, dict) or value.keys() != {
        "epoch", "world", "startSequence", "retention", "maxSubscriptions", "maxLiveEvents"
    } or not _event_uuid(value["epoch"]) or value["world"] != world
            or not _event_uuid(value["world"])
            or _event_integer(value["startSequence"]) is None
            or _event_integer(value["maxSubscriptions"], 1) is None
            or _event_integer(value["maxLiveEvents"], 1) is None):
        return False
    retention = value["retention"]
    return (isinstance(retention, dict)
            and retention.keys() == {"maxRecords", "maxBytes", "maxAgeTicks"}
            and all(_event_integer(retention[key], 1) is not None for key in retention))


def _event_world(value: object) -> bool:
    return (isinstance(value, dict) and value.keys() == {"uuid", "name", "key"}
            and _event_uuid(value["uuid"]) and _nonblank_text(value["name"])
            and isinstance(value["key"], str) and _KEY.fullmatch(value["key"]) is not None)


def _event_vector(value: object, *, block: bool = False) -> bool:
    return (isinstance(value, list) and len(value) == 3
            and all(_bounded_integer(number, -2147483648, 2147483647) is not None if block
                    else _finite_number(number) for number in value))


def _event_entity(value: object, *, player: bool = False) -> bool:
    if (not isinstance(value, dict) or value.keys() != {"uuid", "entityId", "key", "living", "name"}
            or not _event_uuid(value["uuid"]) or _bounded_integer(value["entityId"], 0, 2147483647) is None
            or not isinstance(value["key"], str) or _KEY.fullmatch(value["key"]) is None
            or type(value["living"]) is not bool):
        return False
    if value["key"] == "minecraft:player":
        return value["living"] is True and _nonblank_text(value["name"])
    return not player and value["name"] is None


def _event_key(value: object) -> bool:
    return isinstance(value, str) and _KEY.fullmatch(value) is not None


def _event_native_name(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value, re.ASCII) is not None


def _event_block_ref(value: object) -> bool:
    return (isinstance(value, dict) and value.keys() == {"position", "block"}
            and _event_vector(value["position"], block=True) and _block_spec(value["block"]))


def _event_payload(kind: str, data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if kind == "chat.message":
        return (data.keys() == {"player", "message", "cancelled", "truncated"}
                and _player(data["player"]) and _event_uuid(data["player"]["uuid"])
                and isinstance(data["message"], str) and len(data["message"]) <= 4096
                and data["cancelled"] is False and type(data["truncated"]) is bool)
    player_keys = {"player"}
    if kind in ("block.break", "block.place", "block.interact"):
        expected = player_keys | {"position", "block", "cancelled"}
        if kind == "block.place": expected.add("replacedBlock")
        if kind == "block.interact": expected.update(("face", "action", "hand", "item", "useInteractedBlock", "useItemInHand"))
        if (data.keys() != expected or not _event_entity(data["player"], player=True)
                or not _event_vector(data["position"], block=True) or not _block_spec(data["block"])):
            return False
        if kind == "block.place" and not _block_spec(data["replacedBlock"]): return False
        if kind == "block.interact":
            return (type(data["cancelled"]) is bool and (data["face"] is None or _event_native_name(data["face"]))
                    and data["action"] in ("LEFT_CLICK_BLOCK", "RIGHT_CLICK_BLOCK")
                    and data["hand"] in ("HAND", "OFF_HAND") and (data["item"] is None or _event_key(data["item"]))
                    and data["useInteractedBlock"] in ("DEFAULT", "ALLOW", "DENY")
                    and data["useItemInHand"] in ("DEFAULT", "ALLOW", "DENY"))
        return data["cancelled"] is False
    if kind == "entity.attack":
        return (data.keys() == {"player", "target", "willAttack", "cancelled"}
                and _event_entity(data["player"], player=True) and _event_entity(data["target"])
                and type(data["willAttack"]) is bool and type(data["cancelled"]) is bool)
    if kind in ("entity.damage", "player.damage"):
        return (data.keys() == {"victim", "directSource", "causingEntity", "cause", "rawDamage", "finalDamage", "cancelled"}
                and _event_entity(data["victim"], player=kind == "player.damage")
                and all(data[field] is None or _event_entity(data[field]) for field in ("directSource", "causingEntity"))
                and _event_native_name(data["cause"]) and _finite_number(data["rawDamage"], 0)
                and _finite_number(data["finalDamage"], 0) and data["cancelled"] is False)
    if kind in ("player.join", "player.quit", "player.enter_lava", "player.death"):
        expected = player_keys if kind in ("player.join", "player.quit") else player_keys | {"position"}
        return (data.keys() == expected and _event_entity(data["player"], player=True)
                and ("position" not in expected or _event_vector(data["position"])))
    if kind == "player.respawn":
        if data.keys() != {"player", "reason", "respawnLocation"} or not _event_entity(data["player"], player=True): return False
        at = data["respawnLocation"]
        return (_event_native_name(data["reason"]) and isinstance(at, dict)
                and at.keys() == {"world", "position", "yaw", "pitch"} and _event_world(at["world"])
                and _event_vector(at["position"]) and _finite_number(at["yaw"]) and _finite_number(at["pitch"]))
    if kind in ("projectile.shot", "projectile.hit"):
        expected = {"projectile", "shooter", "sourceBlock", "position", "cancelled"}
        expected.update(("velocity", "weapon", "hand", "force") if kind == "projectile.shot" else ("hitEntity", "hitBlock", "hitFace"))
        if (data.keys() != expected or not _event_entity(data["projectile"])
                or not (data["shooter"] is None or _event_entity(data["shooter"]))
                or not (data["sourceBlock"] is None or _event_block_ref(data["sourceBlock"]))
                or not _event_vector(data["position"])): return False
        if kind == "projectile.shot":
            return (data["cancelled"] is False and _event_vector(data["velocity"])
                    and (data["weapon"] is None or _event_key(data["weapon"]))
                    and data["hand"] in (None, "HAND", "OFF_HAND")
                    and (data["force"] is None or _finite_number(data["force"])))
        return (type(data["cancelled"]) is bool and (data["hitEntity"] is None or _event_entity(data["hitEntity"]))
                and (data["hitBlock"] is None or _event_block_ref(data["hitBlock"]))
                and (data["hitFace"] is None or _event_native_name(data["hitFace"])))
    return False


def _event_record(value: object) -> bool:
    if (not isinstance(value, dict) or value.keys() != {
        "eventId", "serverEpoch", "sequence", "serverTick", "eventType", "world", "data"
    } or not _event_uuid(value["eventId"]) or not _event_uuid(value["serverEpoch"])
            or _event_integer(value["sequence"], 1) is None
            or _event_integer(value["serverTick"]) is None
            or not isinstance(value["eventType"], str) or value["eventType"] not in EVENT_TYPES):
        return False
    return _event_world(value["world"]) and _event_payload(value["eventType"], value["data"])


def _event_params(method: str, params: dict[str, object], request_id: int) -> None:
    keys = {
        "events.subscribe": {"subscriptionId", "eventType", "world", "executor", "players"},
        "events.unsubscribe": {"subscriptionId"},
        "events.pollEvents": {"eventType", "world", "cursor", "limit"},
        "events.getRecent": {"eventType", "world", "cursor", "limit", "upperBound"},
        "events.clearPending": {"eventType", "world"},
    }.get(method)
    if keys is None:
        return
    if method == "events.subscribe":
        keys = keys | (params.keys() & {"region", "blocks"})
    _exact(params, keys, request_id)
    if "subscriptionId" in keys and not _event_uuid(params["subscriptionId"]):
        _reject("INVALID_PARAMS", request_id)
    if "world" in keys and not _nonblank_text(params["world"]):
        _reject("INVALID_PARAMS", request_id)
    if "eventType" in keys and not (method == "events.clearPending" and params["eventType"] is None):
        if not isinstance(params["eventType"], str):
            _reject("INVALID_PARAMS", request_id)
        if params["eventType"] not in EVENT_TYPES:
            _reject("INVALID_EVENT_TYPE", request_id)
    if "limit" in keys and _bounded_integer(params["limit"], 1, 1000) is None:
        _reject("INVALID_PARAMS", request_id)
    if method == "events.subscribe":
        players = params["players"]
        if (not (params["executor"] is None or _event_uuid(params["executor"]))
                or not (players is None or _nonblank_text(players, 2048)
                        or isinstance(players, list) and len(players) <= 1024
                        and all(_event_uuid(player) for player in players))):
            _reject("INVALID_PARAMS", request_id)
        if "region" in params:
            region = params["region"]
            if (params["eventType"] in ("chat.message", "player.join", "player.quit")
                    or not isinstance(region, dict) or region.keys() != {"world", "min", "max"}
                    or not _event_uuid(region["world"]) or not _event_vector(region["min"], block=True)
                    or not _event_vector(region["max"], block=True)
                    or any(int(a.text) > int(b.text) for a, b in zip(region["min"], region["max"]))):
                _reject("INVALID_PARAMS", request_id)
        if "blocks" in params:
            blocks = params["blocks"]
            if (not params["eventType"].startswith("block.") or not isinstance(blocks, list)
                    or len(blocks) > 256 or not all(_event_key(key) for key in blocks)
                    or len(set(blocks)) != len(blocks)):
                _reject("INVALID_PARAMS", request_id)
    if method == "events.pollEvents" and not (params["cursor"] is None or _event_cursor(params["cursor"])):
        _reject("INVALID_PARAMS", request_id)
    if method == "events.getRecent":
        if not ((params["cursor"] is None and params["upperBound"] is None)
                or _event_cursor(params["cursor"]) and _event_integer(params["upperBound"]) is not None):
            _reject("INVALID_PARAMS", request_id)


def _event_result(method: str, result: dict[str, object]) -> bool:
    if method == "events.subscribe":
        return (result.keys() == {"subscriptionId", "eventType", "world"}
                and _event_uuid(result["subscriptionId"]) and _event_uuid(result["world"])
                and isinstance(result["eventType"], str) and result["eventType"] in EVENT_TYPES)
    if method == "events.unsubscribe":
        return (result.keys() == {"subscriptionId", "unsubscribed"}
                and _event_uuid(result["subscriptionId"]) and result["unsubscribed"] is True)
    if method == "events.clearPending":
        return result.keys() == {"cursor"} and _event_cursor(result["cursor"])
    if method not in ("events.pollEvents", "events.getRecent"):
        return False
    keys = {"events", "nextCursor", "upperBound", "availableFrom", "hasMore"}
    if method == "events.getRecent":
        keys.update(("sessionStart", "windowLimited"))
    if (result.keys() != keys or not _event_cursor(result["nextCursor"])
            or _event_integer(result["upperBound"]) is None
            or _event_integer(result["availableFrom"]) is None
            or type(result["hasMore"]) is not bool
            or not isinstance(result["events"], list) or len(result["events"]) > 1000):
        return False
    cursor, rows = result["nextCursor"], result["events"]
    next_sequence, upper = int(cursor["sequence"].text), int(result["upperBound"].text)
    if (next_sequence > upper or int(result["availableFrom"].text) > upper + 1
            or result["hasMore"] != (next_sequence < upper)):
        return False
    previous = 0
    identities = set()
    for row in rows:
        if not _event_record(row):
            return False
        sequence = int(row["sequence"].text)
        if (row["serverEpoch"] != cursor["epoch"] or row["world"]["uuid"] != cursor["world"]
                or not previous < sequence <= next_sequence or row["eventId"] in identities):
            return False
        previous = sequence
        identities.add(row["eventId"])
    if method == "events.getRecent":
        start = _event_integer(result["sessionStart"])
        if start is None or start > upper or type(result["windowLimited"]) is not bool:
            return False
        if rows and int(rows[0]["sequence"].text) <= start:
            return False
    return True


def decode_event(payload: bytes) -> tuple[str, dict[str, object]] | None:
    """Recognize only event notifications; schema-valid data never calls user code."""
    value = _parse(payload)
    if not isinstance(value, dict) or value.get("method") not in ("events.event", "events.overflow"):
        return None
    if (value.keys() != {"jsonrpc", "method", "params"} or value["jsonrpc"] != "2.0"
            or not isinstance(value["params"], dict)):
        _reject("INVALID_RESPONSE")
    params = value["params"]
    if value["method"] == "events.event":
        valid = (params.keys() == {"subscriptionId", "deliverySequence", "event"}
                 and _event_uuid(params["subscriptionId"])
                 and _event_integer(params["deliverySequence"], 1) is not None
                 and _event_record(params["event"]))
    else:
        identities = params.get("subscriptionIds")
        valid = (params.keys() == {"subscriptionIds", "source", "lostCount"}
                 and isinstance(identities, list) and 1 <= len(identities) <= 32
                 and all(_event_uuid(identity) for identity in identities)
                 and len(set(identities)) == len(identities)
                 and params["source"] in ("server", "capture")
                 and _event_integer(params["lostCount"], 1) is not None)
    if not valid:
        _reject("INVALID_RESPONSE")
    return value["method"], params


def decode_progress(payload: bytes) -> int | None:
    """An internal liveness notification never substitutes for the final ACK."""
    value = _parse(payload)
    if not isinstance(value, dict) or "method" not in value:
        return None
    if (value.keys() != {"jsonrpc", "method", "params"} or value["jsonrpc"] != "2.0"
            or value["method"] != "system.progress" or not isinstance(value["params"], dict)
            or value["params"].keys() != {"requestId"}):
        _reject("INVALID_RESPONSE")
    request_id = _identifier(value["params"]["requestId"])
    if request_id is None:
        _reject("INVALID_RESPONSE")
    return request_id


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
    message = _ERROR_MESSAGES.get(known, "Server operation failed")
    return exception_type(message, code=error.code, outcome=error.outcome)
