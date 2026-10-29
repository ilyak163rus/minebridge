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
    UnsupportedLegacyBlockError,
)

__all__ = ["LegacyBlock", "BlockSpec", "BlockInput", "normalize_block", "legacy_block_id"]

_KEY_PATTERN = re.compile(r"[a-z0-9_.-]+:[a-z0-9/._-]+", re.ASCII)
_PROPERTY_PATTERN = re.compile(r"[a-z0-9_]{1,64}", re.ASCII)
_VALUE_PATTERN = re.compile(r"[a-z0-9_-]{1,128}", re.ASCII)


def _split_specification(text: str) -> tuple[str, dict[str, str]]:
    if "[" not in text:
        return text, {}
    key, _, tail = text.partition("[")
    if not tail.endswith("]") or "[" in tail or "]" in tail[:-1]:
        raise InvalidBlockError("Некорректная строка состояний блока")
    states: dict[str, str] = {}
    if tail[:-1]:
        for assignment in tail[:-1].split(","):
            name, separator, value = assignment.partition("=")
            if not separator or name in states:
                raise InvalidBlockError("Состояние должно иметь вид свойство=значение без повторов")
            states[name] = value
    return key, states


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

    def withStates(self, **states: str) -> BlockSpec:
        """Современное описание с изменёнными свойствами и сохранением старой константы."""
        return normalize_block(self).withStates(**states)


@dataclass(frozen=True, slots=True)
class BlockSpec:
    """Неизменяемый современный ключ и состояния; свойства проверяет сервер."""

    key: str
    states: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.key, str):
            raise TypeError("key должен быть строкой namespace:path")
        key, inline_states = _split_specification(self.key)
        if _KEY_PATTERN.fullmatch(key) is None:
            raise InvalidBlockError("Нужен полный ключ блока, например minecraft:stone")
        if not isinstance(self.states, Mapping):
            raise TypeError("states должен быть отображением")
        states = dict(inline_states)
        for name, value in self.states.items():
            if name in states and states[name] != value:
                raise InvalidBlockError("Состояние задано дважды с разными значениями")
            states[name] = value
        if len(states) > 64:
            raise InvalidBlockError("Слишком много свойств блока")
        for name, value in states.items():
            if not isinstance(name, str) or not isinstance(value, str):
                raise TypeError("Имена и значения состояний должны быть строками")
            if _PROPERTY_PATTERN.fullmatch(name) is None or _VALUE_PATTERN.fullmatch(value) is None:
                raise InvalidBlockError("Некорректное имя или значение состояния блока")
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "states", MappingProxyType(states))

    def __hash__(self) -> int:
        return hash((self.key, tuple(sorted(self.states.items()))))

    def withStates(self, **states: str) -> BlockSpec:
        """Получить новое описание: block.OAK_LOG.withStates(axis="x")."""
        return BlockSpec(self.key, {**self.states, **states})


BlockInput: TypeAlias = int | LegacyBlock | str | BlockSpec


@lru_cache(maxsize=1)
def _legacy_table() -> Mapping[tuple[int, int], BlockSpec]:
    resource = files("minebridge._data").joinpath("legacy-blocks-v0.2.json")
    document = json.loads(resource.read_text(encoding="utf-8"))
    if document["formatVersion"] != 1:
        raise RuntimeError("Неподдерживаемый формат таблицы совместимости")
    return MappingProxyType({
        (row["id"], row["data"]): BlockSpec(row["key"], row.get("states", {}))
        for row in document["blocks"]
    })


@lru_cache(maxsize=1)
def _reverse_table() -> Mapping[str, tuple[tuple[int, BlockSpec], ...]]:
    grouped: dict[str, list[tuple[int, BlockSpec]]] = {}
    for (identifier, _), spec in _legacy_table().items():
        grouped.setdefault(spec.key, []).append((identifier, spec))
    return MappingProxyType({key: tuple(rows) for key, rows in grouped.items()})


def legacy_block_id(specification: BlockSpec) -> int:
    """Вернуть исторический ID типа; состояния/data не входят в числовой результат."""
    rows = _reverse_table().get(specification.key, ())
    ids = {identifier for identifier, spec in rows
           if all(specification.states.get(name) == value for name, value in spec.states.items())}
    if not ids:
        all_ids = {identifier for identifier, _ in rows}
        if len(all_ids) == 1:
            ids = all_ids
    if len(ids) != 1:
        raise UnsupportedLegacyBlockError(
            f"Нет однозначного старого ID для {specification.key}; используйте mc.blocks.getBlock/getBlocks",
        )
    return ids.pop()


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

    specification = _legacy_table().get(pair)
    if specification is None:
        # Даже int с тысячами цифр должен дать доменную ошибку, а не ошибку
        # преобразования числа в текст из-за защитного лимита Python.
        raise UnsupportedLegacyBlockError("Пара legacy ID/data не входит в проверенную таблицу этой версии")
    return specification

