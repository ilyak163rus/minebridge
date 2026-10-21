"""Перевод знакомых mcpi-блоков в каноническое описание без сети."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
import json
import re
from types import MappingProxyType
from typing import TypeAlias

from ..errors import (
    InvalidBlockError,
    UnsupportedFeatureError,
    UnsupportedLegacyBlockError,
)

__all__ = ["LegacyBlock", "BlockSpec", "BlockInput", "normalize_block"]

_KEY_PATTERN = re.compile(r"[a-z0-9_.-]+:[a-z0-9/._-]+", re.ASCII)


def _require_integer(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} должен быть целым числом; bool не допускается")


@dataclass(frozen=True, slots=True)
class LegacyBlock:
    """Старое описание mcpi. Поддержка пары проверяется при нормализации."""

    id: int
    data: int = 0

    def __post_init__(self) -> None:
        _require_integer(self.id, "id")
        _require_integer(self.data, "data")


@dataclass(frozen=True, slots=True)
class BlockSpec:
    """Современный ключ блока. T01 допускает только пустые состояния."""

    key: str
    states: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.key, str):
            raise TypeError("key должен быть строкой namespace:path")
        if "[" in self.key or "]" in self.key:
            raise UnsupportedFeatureError("Свойства блока в строке пока не поддерживаются")
        if _KEY_PATTERN.fullmatch(self.key) is None:
            raise InvalidBlockError("Нужен полный ключ блока, например minecraft:stone")
        if not isinstance(self.states, Mapping):
            raise TypeError("states должен быть отображением")
        if self.states:
            raise UnsupportedFeatureError("Непустые состояния блока пока не поддерживаются")
        object.__setattr__(self, "states", MappingProxyType(dict(self.states)))

    def __hash__(self) -> int:
        return hash((self.key, tuple(sorted(self.states.items()))))


BlockInput: TypeAlias = int | LegacyBlock | str | BlockSpec


@lru_cache(maxsize=1)
def _legacy_table() -> Mapping[tuple[int, int], str]:
    resource = files("minebridge._data").joinpath("legacy-blocks-v0.1.json")
    document = json.loads(resource.read_text(encoding="utf-8"))
    if document["formatVersion"] != 1:
        raise RuntimeError("Неподдерживаемый формат таблицы совместимости")
    return MappingProxyType({
        (row["id"], row["data"]): row["key"] for row in document["blocks"]
    })


def normalize_block(value: BlockInput, data: int = 0) -> BlockSpec:
    """Проверить вход и получить BlockSpec; не проверяет реестр сервера."""

    _require_integer(data, "data")
    if isinstance(value, bool):
        raise TypeError("bool не является ID блока")
    if isinstance(value, int):
        pair = (value, data)
    elif isinstance(value, LegacyBlock):
        if data != 0:
            raise ValueError("Отдельный data нельзя совмещать с LegacyBlock")
        pair = (value.id, value.data)
    elif isinstance(value, (str, BlockSpec)):
        if data != 0:
            raise ValueError("Для современного блока data должен быть равен 0")
        return BlockSpec(value) if isinstance(value, str) else value
    else:
        raise TypeError("Ожидается int, LegacyBlock, str или BlockSpec")

    key = _legacy_table().get(pair)
    if key is None:
        # Даже int с тысячами цифр должен дать доменную ошибку, а не ошибку
        # преобразования числа в текст из-за защитного лимита Python.
        raise UnsupportedLegacyBlockError("Пара legacy ID/data не поддерживается в v0.1")
    return BlockSpec(key)

