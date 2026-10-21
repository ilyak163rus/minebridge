"""Подключение к Paper и знакомые учебные вызовы v0.1."""

from __future__ import annotations

from typing import Self

from ._transport import TcpTransport
from .api.blocks import Blocks
from .errors import ProtocolError
from .models import BlockInput

__all__ = ["Minecraft"]


class Minecraft:
    """Создавайте подключение через Minecraft.create(ip, port)."""

    __slots__ = ("_transport", "_blocks")

    def __init__(self, transport: TcpTransport) -> None:
        """Внутренняя сборка фасада; пользовательский вход — create."""
        context = transport.context
        if context is None:
            raise ProtocolError("A successful handshake is required") from None
        self._transport = transport
        self._blocks = Blocks(transport, context.world.name)

    @classmethod
    def create(cls, ip: str = "localhost", port: int = 4711, *,
               token: str | None = None, world: str | None = None,
               timeout: float = 5.0, coordinates: str | None = None) -> Self:
        """Подключиться и дождаться успешного hello.

        token=None берёт MINEBRIDGE_TOKEN из окружения. world=None выбирает
        настроенный мир сервера; coordinates=None означает absolute.
        timeout ограничивает отдельные сетевые стадии. Повторов и reconnect нет.
        """
        transport = TcpTransport.connect_and_handshake(
            ip, port, token=token, world=world, timeout=timeout, coordinates=coordinates,
        )
        try:
            return cls(transport)
        except BaseException:
            transport.close()
            raise

    @property
    def blocks(self) -> Blocks:
        """Операции с блоками; используют то же соединение, что и mc.setBlock."""
        return self._blocks

    def setBlock(self, x: int | float, y: int | float, z: int | float,
                 block: BlockInput, data: int = 0) -> None:
        """Установить блок через общую реализацию mc.blocks.setBlock и дождаться ACK."""
        return self._blocks.setBlock(x, y, z, block, data)

    def close(self) -> None:
        """Закрыть соединение без отдельного RPC; повторный close безопасен."""
        self._transport.close()

    def __repr__(self) -> str:
        return f"Minecraft(closed={self._transport.closed})"
