"""Private handshake preflight and immutable negotiated metadata.

Remote limits are descriptive metadata, never instructions to enlarge local
codec ceilings. Their exact JSON numbers are retained because the wire contract
does not impose a machine-sized upper bound on counters or exponents.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Literal, cast

from . import errors
from ._protocol import CodecError, JsonNumber, encode_frame


@dataclass(frozen=True, slots=True)
class ProtocolVersion:
    major: int
    minor: int


@dataclass(frozen=True, slots=True)
class WorldContext:
    name: str
    uuid: str
    min_y: int
    max_y_exclusive: int


@dataclass(frozen=True, slots=True)
class ServerLimits:
    max_frame_bytes: JsonNumber
    max_json_depth: JsonNumber
    max_sessions: JsonNumber
    max_queued_requests: JsonNumber
    max_output_frames: JsonNumber
    handshake_timeout_seconds: JsonNumber
    frame_assembly_timeout_seconds: JsonNumber
    write_timeout_seconds: JsonNumber
    max_operations_per_tick: JsonNumber
    max_operations_per_session_per_tick: JsonNumber
    executor_budget_millis: JsonNumber


@dataclass(frozen=True, slots=True)
class SessionContext:
    protocol: ProtocolVersion
    session_id: str
    plugin_version: str
    server_version: str
    world: WorldContext
    coordinates: Literal["absolute"]
    chunk_policy: Literal["loaded-only"]
    apply_physics: Literal[True]
    capabilities: tuple[str, ...]
    limits: ServerLimits


def prepare_hello(*, token: str | None, world: str | None,
                  coordinates: str | None) -> dict[str, object]:
    """Validate local options before DNS/TCP; never include values in errors."""
    if token is None:
        token = os.environ.get("MINEBRIDGE_TOKEN")
    if token is None:
        raise errors.AuthenticationError("A lesson token is required") from None
    if not isinstance(token, str):
        raise TypeError("token must be a string or None")
    if not token.strip():
        raise errors.AuthenticationError("A lesson token is required") from None
    if world is not None and not isinstance(world, str):
        raise TypeError("world must be a string or None")
    if coordinates is None:
        coordinates = "absolute"
    if not isinstance(coordinates, str):
        raise TypeError("coordinates must be a string or None")
    if coordinates != "absolute":
        raise errors.UnsupportedFeatureError(
            "Only absolute coordinates are supported",
        ) from None
    params: dict[str, object] = {
        "protocol": {"major": 1, "minor": 0},
        "token": token,
        "world": world,
        "coordinates": coordinates,
    }
    # Reject unencodable/oversized values before opening a connection. The
    # transport still independently encodes the actual request with its own ID.
    try:
        encode_frame({
            "jsonrpc": "2.0", "id": 1, "method": "system.hello", "params": params,
        })
    except CodecError:
        raise errors.ProtocolError("Cannot encode handshake request") from None
    return params


def context_from_result(result: dict[str, object]) -> SessionContext:
    """Copy a codec-validated hello result without retaining mutable wire data."""
    world = cast(dict[str, object], result["world"])
    limits = cast(dict[str, JsonNumber], result["limits"])
    # Protocol 1.0 was already checked by decode_response. Only the bounded
    # world heights require conversion to Python integers here.
    return SessionContext(
        protocol=ProtocolVersion(1, 0),
        session_id=cast(str, result["sessionId"]),
        plugin_version=cast(str, result["pluginVersion"]),
        server_version=cast(str, result["serverVersion"]),
        world=WorldContext(
            name=cast(str, world["name"]),
            uuid=cast(str, world["uuid"]),
            min_y=int(cast(JsonNumber, world["minY"]).text),
            max_y_exclusive=int(cast(JsonNumber, world["maxYExclusive"]).text),
        ),
        coordinates="absolute",
        chunk_policy="loaded-only",
        apply_physics=True,
        capabilities=tuple(cast(list[str], result["capabilities"])),
        limits=ServerLimits(
            max_frame_bytes=limits["maxFrameBytes"],
            max_json_depth=limits["maxJsonDepth"],
            max_sessions=limits["maxSessions"],
            max_queued_requests=limits["maxQueuedRequests"],
            max_output_frames=limits["maxOutputFrames"],
            handshake_timeout_seconds=limits["handshakeTimeoutSeconds"],
            frame_assembly_timeout_seconds=limits["frameAssemblyTimeoutSeconds"],
            write_timeout_seconds=limits["writeTimeoutSeconds"],
            max_operations_per_tick=limits["maxOperationsPerTick"],
            max_operations_per_session_per_tick=limits["maxOperationsPerSessionPerTick"],
            executor_budget_millis=limits["executorBudgetMillis"],
        ),
    )
