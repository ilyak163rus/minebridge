"""Online players, explicit execution context and vanilla targets."""

from __future__ import annotations

from collections.abc import Sequence
import math
import re
from typing import Any, TypeAlias, cast
from uuid import UUID

from .._protocol import JsonNumber
from .._capabilities import require_capability
from .._transport import TcpTransport
from ..errors import ProtocolError
from ..models import (
    EntityRef, InventoryOutcome, InventoryResult, ItemInput, Location, OverflowMode,
    PlayerRef, TargetOutcome, TargetResult, normalize_item, normalize_real_coordinate,
    GameMode,
)
from ..selector import ALL_PLAYERS, Selector
from ..slots import Slot
from ._items import item_from_wire, item_to_wire

__all__ = ["Players", "PlayerInput", "TargetSpec"]

PlayerInput: TypeAlias = str | UUID | PlayerRef
TargetSpec: TypeAlias = str | UUID | EntityRef | Selector | Sequence[EntityRef]
_NAME = re.compile(r"[A-Za-z0-9_]{1,16}\Z", re.ASCII)


def player_name(value: object) -> str:
    """Validate an explicit login name before opening a connection."""
    if not isinstance(value, str):
        raise TypeError("player must be a Minecraft player name")
    if _NAME.fullmatch(value) is None:
        raise ValueError("Player name must contain 1–16 ASCII letters, digits or underscores")
    return value


def player_target(value: PlayerInput) -> str:
    if isinstance(value, PlayerRef):
        return str(value.uuid)
    if isinstance(value, UUID):
        return str(value)
    if not isinstance(value, str):
        raise TypeError("Player must be a name, UUID or PlayerRef")
    if _NAME.fullmatch(value) is not None:
        return value
    try:
        if len(value) != 36:
            raise ValueError
        return str(UUID(value))
    except ValueError:
        raise ValueError("Player must be a Minecraft name or hyphenated UUID") from None


def normalize_targets(value: TargetSpec) -> str | list[str]:
    if isinstance(value, Selector):
        return value.expression
    if isinstance(value, EntityRef):
        return str(value.uuid)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        if not value.strip() or len(value) > 2048 or "\x00" in value:
            raise ValueError("Target must contain 1–2048 characters and no NUL")
        return value
    if isinstance(value, Sequence):
        if len(value) > 1024:
            raise ValueError("Explicit target list must contain at most 1024 references")
        if not all(isinstance(target, EntityRef) for target in value):
            raise TypeError("Explicit target list must contain only entity references")
        return [str(target.uuid) for target in value]
    raise TypeError("Targets must be a name, UUID, entity reference, selector or reference list")


def _number(value: Any) -> float:
    return float(value.text) if isinstance(value, JsonNumber) else float(value)


def _integer(value: Any) -> int:
    return int(value.text) if isinstance(value, JsonNumber) else int(value)


def _player(value: dict[str, Any]) -> PlayerRef:
    return PlayerRef(UUID(value["uuid"]), _integer(value["entityId"]), value["name"])


def _target_result(value: dict[str, Any]) -> TargetResult:
    return TargetResult(_integer(value["matched"]), _integer(value["applied"]), tuple(
        TargetOutcome(UUID(target["uuid"]), target["applied"], target["code"])
        for target in value["targets"]))


class Players:
    """Players in this facade's world and optional UUID-bound execution context."""

    __slots__ = ("_transport", "_world", "_executor")

    def __init__(self, transport: TcpTransport, world: str, executor: UUID | None = None) -> None:
        self._transport = transport
        self._world = world
        self._executor = executor

    def _selection(self, targets: TargetSpec) -> dict[str, object]:
        return {"world": self._world,
                "executor": str(self._executor) if self._executor is not None else None,
                "targets": normalize_targets(targets)}

    def get(self, target: PlayerInput) -> PlayerRef:
        """Resolve one online name or UUID; this never changes SELF."""
        response = self._transport.exchange("players.get", {
            "world": self._world,
            "executor": str(self._executor) if self._executor is not None else None,
            "target": player_target(target),
        })
        payload = cast(dict[str, Any], response.result)
        return _player(payload["player"])

    def list(self, targets: TargetSpec = ALL_PLAYERS) -> list[PlayerRef]:
        """Resolve the selector once; an empty group returns an empty list."""
        response = self._transport.exchange("players.list", self._selection(targets))
        payload = cast(dict[str, Any], response.result)
        return [_player(player) for player in payload["players"]]

    def getPos(self, target: TargetSpec) -> Location:
        """Read one selected player's current position; multiple targets are an error."""
        response = self._transport.exchange("players.getPos", self._selection(target))
        value = cast(dict[str, Any], response.result)["location"]
        return Location(value["world"], _number(value["x"]), _number(value["y"]),
                        _number(value["z"]), _number(value["yaw"]), _number(value["pitch"]))

    def teleport(self, targets: TargetSpec, x: int | float, y: int | float, z: int | float,
                 *, world: str | None = None) -> TargetResult:
        """Teleport a prevalidated target set and wait for per-player outcomes.

        Coordinates preserve fractions. Destination chunks are loaded by Paper.
        The result does not promise a transaction across multiple players.
        """
        parameters = self._selection(targets)
        position = [normalize_real_coordinate(value) for value in (x, y, z)]
        if world is not None and not isinstance(world, str):
            raise TypeError("world must be a world name or key, or None")
        if world is not None and (not world.strip() or "\x00" in world):
            raise ValueError("world must be a nonempty world name or key")
        parameters.update({"position": position, "destinationWorld": world})
        response = self._transport.exchange("players.teleport", parameters, mutation=True)
        value = cast(dict[str, Any], response.result)
        return TargetResult(_integer(value["matched"]), _integer(value["applied"]), tuple(
            TargetOutcome(UUID(target["uuid"]), target["applied"], target["code"])
            for target in value["targets"]))

    def setPos(self, targets: TargetSpec, x: int | float, y: int | float, z: int | float,
               *, world: str | None = None) -> TargetResult:
        """Alias of teleport with exactly the same selector and completion semantics."""
        return self.teleport(targets, x, y, z, world=world)

    def _read_setting(self, method: str, target: TargetSpec) -> dict[str, Any]:
        parameters = self._selection(target)
        require_capability(self._transport, method)
        return cast(dict[str, Any], self._transport.exchange(method, parameters).result)

    def _set_setting(self, method: str, targets: TargetSpec, field: str,
                     value: object) -> TargetResult:
        parameters = self._selection(targets)
        parameters[field] = value
        require_capability(self._transport, method)
        response = self._transport.exchange(method, parameters, mutation=True)
        return _target_result(cast(dict[str, Any], response.result))

    def getGameMode(self, target: TargetSpec) -> GameMode:
        """Read the mode of exactly one selected online player."""
        return GameMode(self._read_setting("players.getGameMode", target)["mode"])

    def setGameMode(self, targets: TargetSpec, mode: GameMode | str) -> TargetResult:
        """Set a prevalidated player group and return actual per-player outcomes."""
        if not isinstance(mode, (GameMode, str)):
            raise TypeError("mode must be GameMode or a lowercase game-mode name")
        try:
            value = GameMode(mode)
        except ValueError:
            raise ValueError("mode must be survival, creative, adventure or spectator") from None
        return self._set_setting("players.setGameMode", targets, "mode", value.value)

    def getHealth(self, target: TargetSpec) -> float:
        """Read one player's health points; twenty points normally means ten hearts."""
        return _number(self._read_setting("players.getHealth", target)["value"])

    def setHealth(self, targets: TargetSpec, value: int | float) -> TargetResult:
        """Set health points; zero can kill. The server validates each actual maximum."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("health must be a finite nonnegative number")
        try:
            health = float(value)
        except OverflowError:
            raise ValueError("health must be a finite nonnegative number") from None
        if not math.isfinite(health) or health < 0:
            raise ValueError("health must be a finite nonnegative number")
        return self._set_setting("players.setHealth", targets, "value", health)

    def getFoodLevel(self, target: TargetSpec) -> int:
        """Read the food level of exactly one selected online player."""
        return _integer(self._read_setting("players.getFoodLevel", target)["value"])

    def setFoodLevel(self, targets: TargetSpec, value: int) -> TargetResult:
        """Set a food level from zero through twenty for every selected player."""
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("food level must be an integer")
        if not 0 <= value <= 20:
            raise ValueError("food level must be between 0 and 20")
        return self._set_setting("players.setFoodLevel", targets, "value", value)

    def giveItem(self, targets: TargetSpec, item: ItemInput, amount: int | None = None,
                 *, overflow: OverflowMode = "return") -> InventoryResult:
        """Give items and account for everything that did not fit the inventory.

        The default returns leftovers; overflow="drop" drops them at each
        player's location. A full inventory is a processed request, so inspect
        given, leftovers and dropped in each outcome rather than applied alone.
        This result waits for the server in either write mode.
        """
        specification = normalize_item(item, amount)
        if not isinstance(overflow, str):
            raise TypeError("overflow must be 'return' or 'drop'")
        if overflow not in ("return", "drop"):
            raise ValueError("overflow must be 'return' or 'drop'")
        parameters = self._selection(targets)
        parameters.update({"item": item_to_wire(specification), "overflow": overflow})
        response = self._transport.exchange("players.giveItem", parameters, mutation=True)
        value = cast(dict[str, Any], response.result)
        outcomes = []
        for target in value["targets"]:
            leftovers = tuple(item_from_wire(leftover) for leftover in target["leftovers"])
            if (_integer(target["requested"]) != specification.amount
                or (overflow == "return" and _integer(target["dropped"]) != 0) or any(
                leftover.key != specification.key or leftover.name != specification.name
                or (leftover.lore or ()) != (specification.lore or ()) for leftover in leftovers
            )):
                self._transport.close()
                error = ProtocolError("Inventory result does not match the requested item",
                                      outcome="unknown")
                error.request_id = response.request_id
                error.method = "players.giveItem"
                raise error
            outcomes.append(InventoryOutcome(
                UUID(target["uuid"]), target["applied"], target["code"],
                _integer(target["requested"]), _integer(target["given"]), leftovers,
                _integer(target["dropped"])))
        return InventoryResult(_integer(value["matched"]), _integer(value["applied"]), tuple(outcomes))

    def setItem(self, targets: TargetSpec, slot: "Slot", item: ItemInput,
                amount: int | None = None) -> TargetResult:
        """Replace one exact public slot for a prevalidated group of online players."""
        from .inventories import normalize_slot, _slot_to_wire
        selected_slot = normalize_slot(slot)
        specification = normalize_item(item, amount)
        parameters = self._selection(targets)
        parameters.update(slot=_slot_to_wire(selected_slot), item=item_to_wire(specification))
        require_capability(self._transport, "players.setItem")
        response = self._transport.exchange("players.setItem", parameters, mutation=True)
        result = _target_result(cast(dict[str, Any], response.result))
        selection = parameters["targets"]
        expected = None
        if isinstance(selection, list):
            expected = {UUID(value) for value in selection}
        elif isinstance(selection, str):
            try:
                expected = {UUID(selection)}
            except ValueError:
                if selection == "@s" and self._executor is not None:
                    expected = {self._executor}
        if expected is not None and {target.uuid for target in result.targets} != expected:
            self._transport.close()
            error = ProtocolError("Inventory target result does not match the requested UUIDs", outcome="unknown")
            error.request_id, error.method = response.request_id, "players.setItem"
            raise error
        return result
