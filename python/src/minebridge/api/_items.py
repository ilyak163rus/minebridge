"""Conversion of validated wire item values into immutable public models."""

from __future__ import annotations

from typing import Any

from .._protocol import JsonNumber
from ..models.items import ItemStack


def item_to_wire(item: ItemStack) -> dict[str, object]:
    return {"key": item.key, "amount": item.amount, "name": item.name,
            "lore": None if item.lore is None else list(item.lore)}


def item_from_wire(value: dict[str, Any]) -> ItemStack:
    amount = value["amount"]
    return ItemStack(value["key"], int(amount.text) if isinstance(amount, JsonNumber) else int(amount),
                     value["name"], value["lore"])
