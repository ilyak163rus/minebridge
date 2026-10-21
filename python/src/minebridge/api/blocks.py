"""Одна операция установки блока с общими правилами для обоих фасадов."""

from __future__ import annotations

from .._transport import TcpTransport
from ..models import BlockInput, normalize_block, normalize_position

__all__ = ["Blocks"]


class Blocks:
    """Блоки выбранного мира; экземпляр доступен через mc.blocks."""

    __slots__ = ("_transport", "_world")

    def __init__(self, transport: TcpTransport, world: str) -> None:
        self._transport = transport
        self._world = world

    def setBlock(self, x: int | float, y: int | float, z: int | float,
                 block: BlockInput, data: int = 0) -> None:
        """Установить блок и дождаться ACK. Координаты округляются вниз.

        Принимает числовой ID 0/1/4, константу block, namespaced-строку или
        BlockSpec без состояний. Сервер проверяет мир, границы и loaded chunk.
        Тайм-аут/обрыв после отправки может иметь неизвестный исход; повторов нет.
        """
        position = normalize_position(x, y, z)
        specification = normalize_block(block, data)
        self._transport.exchange("blocks.set", {
            "world": self._world,
            "position": list(position),
            "block": {"key": specification.key, "states": dict(specification.states)},
        }, mutation=True)

