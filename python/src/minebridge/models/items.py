"""Item descriptions and loss-accounted inventory results."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias
from uuid import UUID

from .keys import ItemKey

__all__ = ["ItemStack", "ItemInput", "OverflowMode", "InventoryOutcome", "InventoryResult",
           "normalize_item"]

MAX_ITEM_AMOUNT = 2304
OverflowMode: TypeAlias = Literal["return", "drop"]


def _amount(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Item amount must be an integer")
    if not 1 <= value <= MAX_ITEM_AMOUNT:
        raise ValueError("Item amount must be between 1 and 2304")
    return value


@dataclass(frozen=True, slots=True)
class ItemStack:
    """Requested item, independent of the server's per-slot stack size.

    name/lore are literal text. Enchantments and arbitrary components are future
    features; unsupported properties are never silently discarded.
    """

    material: ItemKey | str
    amount: int = 1
    name: str | None = None
    lore: tuple[str, ...] | Sequence[str] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.material, str):
            object.__setattr__(self, "material", ItemKey(self.material))
        elif not isinstance(self.material, ItemKey):
            raise TypeError("Item material must be ItemKey or a namespace:path string")
        _amount(self.amount)
        if self.name is not None and not isinstance(self.name, str):
            raise TypeError("Item name must be a string or None")
        if self.name is not None and len(self.name) > 256:
            raise ValueError("Item name must contain at most 256 characters")
        if self.lore is not None:
            if isinstance(self.lore, (str, bytes)) or not isinstance(self.lore, Sequence):
                raise TypeError("Item lore must be a sequence of strings or None")
            if len(self.lore) > 16 or any(not isinstance(line, str) for line in self.lore):
                raise ValueError("Item lore must contain at most 16 string lines")
            if any(len(line) > 256 for line in self.lore):
                raise ValueError("Each lore line must contain at most 256 characters")
            object.__setattr__(self, "lore", tuple(self.lore))

    @property
    def key(self) -> str:
        assert isinstance(self.material, ItemKey)
        return self.material.key


ItemInput: TypeAlias = ItemKey | ItemStack | str


def normalize_item(value: ItemInput, amount: int | None = None) -> ItemStack:
    if isinstance(value, ItemStack):
        return value if amount is None else ItemStack(value.material, _amount(amount), value.name, value.lore)
    return ItemStack(value, 1 if amount is None else _amount(amount))


@dataclass(frozen=True, slots=True)
class InventoryOutcome:
    """A processed request may return leftovers even when applied=True."""

    uuid: UUID
    applied: bool
    code: str | None
    requested: int
    given: int
    leftovers: tuple[ItemStack, ...]
    dropped: int


@dataclass(frozen=True, slots=True)
class InventoryResult:
    matched: int
    applied: int
    targets: tuple[InventoryOutcome, ...]
