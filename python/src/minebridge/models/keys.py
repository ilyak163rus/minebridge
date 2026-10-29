"""Distinct immutable registry-key types; importing them never contacts a server."""

from dataclasses import dataclass
import re

__all__ = ["ItemKey", "EffectKey", "EntityTypeKey"]

_KEY = re.compile(r"[a-z0-9_.-]+:[a-z0-9/._-]+\Z", re.ASCII)


def _validate(key: str) -> None:
    if not isinstance(key, str):
        raise TypeError("Registry key must be a namespace:path string")
    if _KEY.fullmatch(key) is None:
        raise ValueError("Use a full registry key, for example minecraft:iron_sword")


@dataclass(frozen=True, slots=True)
class ItemKey:
    key: str

    def __post_init__(self) -> None:
        _validate(self.key)


@dataclass(frozen=True, slots=True)
class EffectKey:
    key: str

    def __post_init__(self) -> None:
        _validate(self.key)


@dataclass(frozen=True, slots=True)
class EntityTypeKey:
    key: str

    def __post_init__(self) -> None:
        _validate(self.key)
