"""Immutable inventory metadata and read-only item descriptions."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Sequence
from typing import Literal, TYPE_CHECKING
from uuid import UUID

from ..slots import Slot
from .keys import ItemKey
from .items import ItemInput

if TYPE_CHECKING:
    from .._transport import TcpTransport

__all__ = ["ItemView", "InventoryPart", "InventoryInfo", "InventoryRef", "SlotWriteResult", "InventoryUpdateResult"]


@dataclass(frozen=True, slots=True)
class ItemView:
    """A bounded view, not a lossless item specification accepted by setItem."""

    key: ItemKey
    amount: int
    name: str | None
    lore: tuple[str, ...] | None
    hasAdditionalData: bool
    truncated: bool

    def __post_init__(self) -> None:
        if not isinstance(self.key, ItemKey):
            raise TypeError("ItemView key must be an ItemKey")
        if type(self.amount) is not int or not 1 <= self.amount <= 2147483647:
            raise ValueError("ItemView amount must be a positive int32")
        if self.name is not None and (not isinstance(self.name, str) or len(self.name) > 256):
            raise ValueError("ItemView name must contain at most 256 characters")
        if self.lore is not None:
            if (not isinstance(self.lore, Sequence) or isinstance(self.lore, (str, bytes))
                    or len(self.lore) > 16 or any(not isinstance(line, str) or len(line) > 256 for line in self.lore)):
                raise ValueError("ItemView lore must contain at most sixteen bounded text lines")
            object.__setattr__(self, "lore", tuple(self.lore))
        if type(self.hasAdditionalData) is not bool or type(self.truncated) is not bool:
            raise TypeError("ItemView flags must be booleans")


@dataclass(frozen=True, slots=True)
class InventoryPart:
    position: tuple[int, int, int]
    offset: int
    size: int
    key: str


@dataclass(frozen=True, slots=True)
class InventoryInfo:
    kind: Literal["player", "chest"]
    size: int
    slots: tuple[Slot, ...]
    player: UUID | None = None
    world: UUID | None = None
    position: tuple[int, int, int] | None = None
    combined: bool | None = None
    layout: tuple[InventoryPart, ...] = ()


@dataclass(frozen=True, slots=True)
class SlotWriteResult:
    applied: bool
    slot: Slot
    previous: ItemView | None
    current: ItemView | None


@dataclass(frozen=True, slots=True)
class InventoryUpdateResult:
    applied: bool
    slots: tuple[Slot, ...]


@dataclass(frozen=True, slots=True)
class InventoryRef:
    """A stable descriptor. Metadata is local; methods explicitly access Paper."""

    _transport: TcpTransport = field(repr=False, compare=False)
    _info: InventoryInfo

    @property
    def kind(self) -> Literal["player", "chest"]:
        return self._info.kind

    @property
    def size(self) -> int:
        return self._info.size

    @property
    def slots(self) -> tuple[Slot, ...]:
        return self._info.slots

    @property
    def player(self) -> UUID | None:
        return self._info.player

    @property
    def world(self) -> UUID | None:
        return self._info.world

    @property
    def position(self) -> tuple[int, int, int] | None:
        return self._info.position

    @property
    def combined(self) -> bool | None:
        return self._info.combined

    @property
    def layout(self) -> tuple[InventoryPart, ...]:
        return self._info.layout

    def getItem(self, slot: Slot) -> ItemView | None:
        from ..api.inventories import _get_item
        return _get_item(self, slot)

    def getContents(self) -> dict[Slot, ItemView | None]:
        from ..api.inventories import _get_contents
        return _get_contents(self)

    def setItem(self, slot: Slot, item: ItemInput, amount: int | None = None) -> SlotWriteResult:
        from ..api.inventories import _set_item
        return _set_item(self, slot, item, amount)

    def clear(self, slot: Slot | None = None) -> InventoryUpdateResult:
        from ..api.inventories import _clear
        return _clear(self, slot)
