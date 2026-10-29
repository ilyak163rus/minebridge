"""Одна операция установки блока с общими правилами для обоих фасадов."""

from __future__ import annotations

from typing import Any, cast

from .._transport import TcpTransport
from .. import errors
from ..models import BlockInput, BlockSpec, normalize_block, normalize_position
from .._protocol import JsonNumber

__all__ = ["Blocks"]

MAX_SET_VOLUME = 1_000_000
MAX_READ_VOLUME = 262_144
PAGE_SIZE = 64


def _region(x1: int | float, y1: int | float, z1: int | float,
            x2: int | float, y2: int | float, z2: int | float, limit: int,
            ) -> tuple[tuple[int, int, int], tuple[int, int, int], int]:
    first, second = normalize_position(x1, y1, z1), normalize_position(x2, y2, z2)
    lower = (min(first[0], second[0]), min(first[1], second[1]), min(first[2], second[2]))
    upper = (max(first[0], second[0]), max(first[1], second[1]), max(first[2], second[2]))
    volume = (upper[0] - lower[0] + 1) * (upper[1] - lower[1] + 1) * (upper[2] - lower[2] + 1)
    if volume > limit:
        raise errors.LimitExceededError(f"Объём области превышает {limit} блоков")
    return lower, upper, volume


def _block_from_wire(value: object) -> BlockSpec:
    # The wire schema has already checked key and states, preserving future keys.
    block = cast(dict[str, Any], value)
    return BlockSpec(block["key"], block["states"])


class Blocks:
    """Блоки выбранного мира; экземпляр доступен через mc.blocks."""

    __slots__ = ("_transport", "_world", "_write_mode")

    def __init__(self, transport: TcpTransport, world: str, write_mode: str = "buffered") -> None:
        self._transport = transport
        self._world = world
        self._write_mode = write_mode

    def setBlock(self, x: int | float, y: int | float, z: int | float,
                 block: BlockInput, data: int = 0) -> None:
        """Установить блок. В buffered-режиме результат ожидается через mc.flush().

        Принимает проверенный старый ID, константу block, namespaced-строку или
        BlockSpec с состояниями. Сервер проверяет мир и границы, загружает чанк.
        Тайм-аут/обрыв после отправки может иметь неизвестный исход; повторов нет.
        """
        position = normalize_position(x, y, z)
        specification = normalize_block(block, data)
        send = self._transport.submit if self._write_mode == "buffered" else self._transport.exchange
        send("blocks.set", {
            "world": self._world,
            "position": list(position),
            "block": {"key": specification.key, "states": dict(specification.states)},
        }, mutation=True)

    def setBlocks(self, x1: int | float, y1: int | float, z1: int | float,
                  x2: int | float, y2: int | float, z2: int | float,
                  block: BlockInput, data: int = 0) -> None:
        """Заполнить включённую область; переставленные углы допустимы.

        Buffered-запись ожидается через flush/чтение/close. Большая стройка
        выполняется частями; отмена или ошибка не откатывает построенную часть.
        """
        lower, upper, _ = _region(x1, y1, z1, x2, y2, z2, MAX_SET_VOLUME)
        specification = normalize_block(block, data)
        send = self._transport.submit if self._write_mode == "buffered" else self._transport.exchange
        send("blocks.setRegion", {
            "world": self._world, "from": list(lower), "to": list(upper),
            "block": {"key": specification.key, "states": dict(specification.states)},
        }, mutation=True)

    def getBlock(self, x: int | float, y: int | float, z: int | float) -> BlockSpec:
        """Прочитать современный блок со всеми состояниями после предыдущих записей."""
        response = self._transport.exchange("blocks.get", {
            "world": self._world, "position": list(normalize_position(x, y, z)),
        })
        assert response.result is not None
        return _block_from_wire(response.result["block"])

    def getBlocks(self, x1: int | float, y1: int | float, z1: int | float,
                  x2: int | float, y2: int | float, z2: int | float,
                  ) -> dict[tuple[int, int, int], BlockSpec]:
        """Прочитать словарь абсолютные координаты → BlockSpec, включая обе границы.

        Внутри читается страницами; чужие изменения не образуют атомарный снимок.
        """
        lower, upper, volume = _region(x1, y1, z1, x2, y2, z2, MAX_READ_VOLUME)
        width, depth = upper[0] - lower[0] + 1, upper[2] - lower[2] + 1
        result: dict[tuple[int, int, int], BlockSpec] = {}
        offset = 0
        while True:
            response = self._transport.exchange("blocks.getRegion", {
                "world": self._world, "from": list(lower), "to": list(upper),
                "offset": offset, "limit": PAGE_SIZE,
            })
            page = cast(dict[str, Any], response.result)
            rows = page["blocks"]
            next_offset = page["nextOffset"]
            if int(page["total"].text) != volume or not rows or len(rows) > min(PAGE_SIZE, volume - offset):
                self._invalid_page()
            for index, row in enumerate(rows, offset):
                coordinates = tuple(int(number.text) for number in row["position"])
                expected = (lower[0] + index % width,
                            lower[1] + index // (width * depth),
                            lower[2] + (index // width) % depth)
                if coordinates != expected:
                    self._invalid_page()
                result[expected] = _block_from_wire(row["block"])
            offset += len(rows)
            if next_offset is None:
                if offset != volume:
                    self._invalid_page()
                return result
            if not isinstance(next_offset, JsonNumber) or int(next_offset.text) != offset or offset >= volume:
                self._invalid_page()

    def _invalid_page(self) -> None:
        self._transport.close()
        raise errors.ProtocolError("Сервер вернул несогласованную страницу блоков")

