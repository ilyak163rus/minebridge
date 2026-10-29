"""Exact public inventory slots; every method explicitly waits for its result."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from .. import errors
from .._capabilities import require_capability
from .._protocol import JsonNumber, Response
from .._transport import TcpTransport
from ..models.coordinates import normalize_position
from ..models.inventories import (
    InventoryInfo, InventoryPart, InventoryRef, InventoryUpdateResult, ItemView, SlotWriteResult,
)
from ..models.items import ItemInput, normalize_item
from ..models.keys import ItemKey
from ..slots import EquipmentSlot, Slot
from ._items import item_to_wire
from .players import TargetSpec, normalize_targets

__all__ = ["Inventories", "InventoryRef"]


def _integer(value: Any) -> int:
    return int(value.text) if isinstance(value, JsonNumber) else int(value)


def _slot_from_wire(value: Any) -> Slot:
    return EquipmentSlot(value) if isinstance(value, str) else _integer(value)


def normalize_slot(value: Slot, *, size: int = 41) -> Slot:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError("slot must be an integer index or slots equipment constant")
    if isinstance(value, str):
        try:
            slot = EquipmentSlot(value)
        except ValueError:
            raise errors.InvalidSlotError("Unknown public equipment slot") from None
        if size != 41:
            raise errors.InvalidSlotError("Chest slots use integer indices")
        return slot
    maximum = 35 if size == 41 else size - 1
    if not 0 <= value <= maximum:
        raise errors.InvalidSlotError("Slot is outside this inventory's public range")
    return value


def _slot_to_wire(slot: Slot) -> int | str:
    return slot.value if isinstance(slot, EquipmentSlot) else slot


def _view(value: dict[str, Any] | None) -> ItemView | None:
    if value is None:
        return None
    return ItemView(ItemKey(value["key"]), _integer(value["amount"]), value["name"],
                    None if value["lore"] is None else tuple(value["lore"]),
                    value["hasAdditionalData"], value["truncated"])


def _descriptor(info: InventoryInfo) -> dict[str, Any]:
    base: dict[str, Any] = {"kind": info.kind, "size": info.size,
                            "slots": [_slot_to_wire(slot) for slot in info.slots]}
    if info.kind == "player":
        base["player"] = str(info.player)
    else:
        base.update(world=str(info.world), position=list(info.position), combined=info.combined,
                    layout=[{"position": list(part.position), "offset": part.offset,
                             "size": part.size, "key": part.key} for part in info.layout])
    return base


def _info(value: dict[str, Any]) -> InventoryInfo:
    slots = tuple(_slot_from_wire(slot) for slot in value["slots"])
    if value["kind"] == "player":
        return InventoryInfo("player", _integer(value["size"]), slots, player=UUID(value["player"]))
    position = cast(tuple[int, int, int], tuple(_integer(axis) for axis in value["position"]))
    layout = tuple(InventoryPart(cast(tuple[int, int, int], tuple(_integer(axis) for axis in part["position"])),
                                 _integer(part["offset"]), _integer(part["size"]), part["key"])
                   for part in value["layout"])
    return InventoryInfo("chest", _integer(value["size"]), slots, world=UUID(value["world"]),
                         position=position, combined=value["combined"], layout=layout)


def _invalid(transport: TcpTransport, response: Response, method: str, *, mutation: bool = False) -> None:
    transport.close()
    error = errors.ProtocolError("Inventory result does not match the request",
                                 outcome="unknown" if mutation else "not-applied")
    error.request_id, error.method = response.request_id, method
    raise error


def _exchange(ref: InventoryRef, method: str, params: dict[str, object], *, mutation: bool = False) -> Response:
    require_capability(ref._transport, method)
    return ref._transport.exchange(method, {"inventory": _descriptor(ref._info), **params}, mutation=mutation)


def _get_item(ref: InventoryRef, slot: Slot) -> ItemView | None:
    selected = normalize_slot(slot, size=ref.size)
    response = _exchange(ref, "inventories.getItem", {"slot": _slot_to_wire(selected)})
    result = cast(dict[str, Any], response.result)
    if _slot_from_wire(result["slot"]) != selected:
        _invalid(ref._transport, response, "inventories.getItem")
    return _view(result["item"])


def _get_contents(ref: InventoryRef) -> dict[Slot, ItemView | None]:
    result: dict[Slot, ItemView | None] = {}
    offset = 0
    while offset < ref.size:
        response = _exchange(ref, "inventories.getContents", {"offset": offset, "limit": 54})
        page = cast(dict[str, Any], response.result)
        rows = page["items"]
        count = len(rows)
        next_offset = None if page["nextOffset"] is None else _integer(page["nextOffset"])
        expected_next = offset + count if offset + count < ref.size else None
        if (_integer(page["total"]) != ref.size or count == 0 or offset + count > ref.size
                or tuple(_slot_from_wire(row["slot"]) for row in rows) != ref.slots[offset:offset + count]
                or next_offset != expected_next):
            _invalid(ref._transport, response, "inventories.getContents")
        for row in rows:
            result[_slot_from_wire(row["slot"])] = _view(row["item"])
        offset += count
    return result


def _set_item(ref: InventoryRef, slot: Slot, item: ItemInput, amount: int | None) -> SlotWriteResult:
    selected = normalize_slot(slot, size=ref.size)
    specification = normalize_item(item, amount)
    response = _exchange(ref, "inventories.setItem", {"slot": _slot_to_wire(selected),
                         "item": item_to_wire(specification)}, mutation=True)
    result = cast(dict[str, Any], response.result)
    current = _view(result["current"])
    if (_slot_from_wire(result["slot"]) != selected or current is None
            or current.key.key != specification.key or current.amount != specification.amount
            or current.name != specification.name or (current.lore or ()) != (specification.lore or ())
            or current.hasAdditionalData or current.truncated):
        _invalid(ref._transport, response, "inventories.setItem", mutation=True)
    return SlotWriteResult(result["applied"], selected, _view(result["previous"]), current)


def _clear(ref: InventoryRef, slot: Slot | None) -> InventoryUpdateResult:
    selected = None if slot is None else normalize_slot(slot, size=ref.size)
    response = _exchange(ref, "inventories.clear", {"slot": None if selected is None else _slot_to_wire(selected)}, mutation=True)
    result = cast(dict[str, Any], response.result)
    changed = tuple(_slot_from_wire(value) for value in result["slots"])
    if changed != (ref.slots if selected is None else (selected,)):
        _invalid(ref._transport, response, "inventories.clear", mutation=True)
    return InventoryUpdateResult(result["applied"], changed)


class Inventories:
    """References to supported physical chests and online-player inventories."""

    __slots__ = ("_transport", "_world", "_executor")

    def __init__(self, transport: TcpTransport, world: str, executor: UUID | None = None) -> None:
        self._transport, self._world, self._executor = transport, world, executor

    def ofBlock(self, x: int | float, y: int | float, z: int | float, *,
                world: str | None = None, combined: bool = False) -> InventoryRef:
        position = normalize_position(x, y, z)
        if type(combined) is not bool:
            raise TypeError("combined must be a boolean")
        if world is not None and not isinstance(world, str):
            raise TypeError("world must be a world name or key, or None")
        if world is not None and (not world.strip() or "\x00" in world):
            raise ValueError("world must be a nonempty world name or key")
        require_capability(self._transport, "inventories.ofBlock")
        response = self._transport.exchange("inventories.ofBlock", {
            "world": self._world, "destinationWorld": world, "position": list(position), "combined": combined})
        metadata = _info(cast(dict[str, Any], response.result)["inventory"])
        context = self._transport.context
        known_world = (context is not None and (world is None or world in (context.world.name, context.world.key)))
        if (metadata.kind != "chest" or metadata.position != position or metadata.combined is not combined
                or known_world and metadata.world != UUID(context.world.uuid)):
            _invalid(self._transport, response, "inventories.ofBlock")
        return InventoryRef(self._transport, metadata)

    def ofPlayer(self, target: TargetSpec) -> InventoryRef:
        selection = normalize_targets(target)
        require_capability(self._transport, "inventories.ofPlayer")
        response = self._transport.exchange("inventories.ofPlayer", {
            "world": self._world, "executor": None if self._executor is None else str(self._executor), "targets": selection})
        metadata = _info(cast(dict[str, Any], response.result)["inventory"])
        explicit = None
        if isinstance(selection, str):
            try:
                explicit = UUID(selection)
            except ValueError:
                if selection == "@s":
                    explicit = self._executor
        elif len(set(selection)) == 1:
            explicit = UUID(selection[0])
        if metadata.kind != "player" or explicit is not None and metadata.player != explicit:
            _invalid(self._transport, response, "inventories.ofPlayer")
        return InventoryRef(self._transport, metadata)
