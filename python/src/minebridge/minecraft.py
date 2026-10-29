"""Подключение к Paper, буферизованные записи и синхронные барьеры."""

from __future__ import annotations

from _thread import LockType
from dataclasses import dataclass, field
from threading import Lock
from types import TracebackType
from typing import Literal, Self
from uuid import UUID

from ._transport import TcpTransport
from .api.blocks import Blocks
from .api.effects import Effects
from .api.entities import Entities, EntityFace
from .api.players import Players, PlayerInput, player_name
from .api.players import TargetSpec
from .api.worlds import Worlds
from .api.server import Server
from .api.events import Events
from .api.inventories import Inventories
from .errors import ProtocolError
from .models import BlockInput, EntityRef, EntityTypeKey, ItemInput, TargetResult
from .models.blocks import legacy_block_id

__all__ = ["Minecraft"]


@dataclass(slots=True)
class _CloseState:
    closed: bool = False
    lock: LockType = field(default_factory=Lock)


class Minecraft:
    """Создавайте подключение через Minecraft.create(ip, port)."""

    __slots__ = ("_transport", "_blocks", "_players", "_effects", "_entities",
                 "_worlds", "_server", "_events", "_inventories", "_logging", "_write_mode", "_close_state")

    def __init__(self, transport: TcpTransport, write_mode: Literal["buffered", "sync"] = "buffered", *,
                 executor: UUID | None = None, close_state: _CloseState | None = None,
                 logging: bool = False) -> None:
        """Внутренняя сборка фасада; пользовательский вход — create."""
        context = transport.context
        if context is None:
            raise ProtocolError("A successful handshake is required") from None
        self._transport = transport
        self._blocks = Blocks(transport, context.world.name, write_mode)
        self._players = Players(transport, context.world.name, executor)
        self._effects = Effects(transport, context.world.name, executor)
        self._entities = Entities(transport, context.world.name)
        self._worlds = Worlds(transport, context.world.name)
        self._server = Server(transport, write_mode, logging)
        self._events = Events(transport, context.world.name, executor)
        self._inventories = Inventories(transport, context.world.name, executor)
        self._logging = logging
        self._write_mode = write_mode
        self._close_state = close_state if close_state is not None else _CloseState()

    @classmethod
    def create(cls, ip: str = "localhost", port: int = 4711, *,
               writeMode: Literal["buffered", "sync"] = "buffered",
               token: str | None = None, world: str | None = None,
               timeout: float = 5.0, coordinates: str | None = None,
               player: str | None = None, logging: bool = False) -> Self:
        """Подключиться и дождаться успешного hello.

        writeMode="buffered" не ждёт каждый блок; flush()/close() ждут записи.
        writeMode="sync" ждёт каждую запись. Токен необязателен при authEnabled=false.
        world=None автоматически выбирает основной мир; coordinates=None означает absolute.
        timeout ограничивает отдельные сетевые стадии. Повторов и reconnect нет.
        player="ТекущийНик" связывает SELF с UUID игрока после hello; без player SELF не задан.
        logging=True включает серверный журнал действий этого соединения.
        При обычном выходе из Python ожидающие записи завершаются автоматически.
        """
        if not isinstance(writeMode, str):
            raise TypeError("writeMode must be 'buffered' or 'sync'")
        if writeMode not in ("buffered", "sync"):
            raise ValueError("writeMode must be 'buffered' or 'sync'")
        if player is not None:
            player_name(player)
        transport = TcpTransport.connect_and_handshake(
            ip, port, token=token, world=world, timeout=timeout, coordinates=coordinates,
            logging=logging,
        )
        try:
            client = cls(transport, writeMode, logging=logging)
            return client if player is None else client.withContext(player=player)
        except BaseException:
            transport.close()
            raise

    @property
    def blocks(self) -> Blocks:
        """Операции с блоками; используют то же соединение, что и mc.setBlock."""
        return self._blocks

    @property
    def players(self) -> Players:
        """Online-player operations with this facade's explicit SELF binding."""
        return self._players

    @property
    def effects(self) -> Effects:
        """Effects with this facade's explicit SELF binding."""
        return self._effects

    @property
    def entities(self) -> Entities:
        """Entity creation in this connection's selected world."""
        return self._entities

    @property
    def worlds(self) -> Worlds:
        """Time, weather and game rules; the default world is already selected."""
        return self._worlds

    @property
    def server(self) -> Server:
        """Public immutable connection metadata, available without another RPC."""
        return self._server

    @property
    def events(self) -> Events:
        """Shared live event dispatcher and independent journal reads."""
        return self._events

    @property
    def inventories(self) -> Inventories:
        """Exact public slots of online players and physical chests."""
        return self._inventories

    def setPos(self, targets: TargetSpec, x: int | float, y: int | float, z: int | float,
               *, world: str | None = None) -> TargetResult:
        """Alias of mc.players.teleport with a selector before the coordinates."""
        return self._players.teleport(targets, x, y, z, world=world)

    def spawnEntity(self, x: int | float, y: int | float, z: int | float,
                    entityType: EntityTypeKey | str, *, world: str | None = None,
                    item: ItemInput | None = None, block: BlockInput | None = None,
                    face: EntityFace | None = None, owner: PlayerInput | None = None) -> EntityRef:
        """Create one entity and wait for its reference; no automatic retries."""
        return self._entities.spawn(entityType, x, y, z, world=world, item=item,
                                    block=block, face=face, owner=owner)

    def withContext(self, *, player: PlayerInput | None = None) -> Self:
        """Return a facade sharing this connection, bound to an online player's UUID.

        The original facade is unchanged. Omitting player or passing None clears
        SELF. Closing either facade closes their shared connection for both.
        This binding is an execution origin, not authentication of a student.
        """
        executor = None if player is None else self._players.get(player).uuid
        return type(self)(self._transport, self._write_mode, executor=executor,
                          close_state=self._close_state, logging=self._logging)

    def getPlayerEntityId(self, name: str) -> int:
        """Read an online player's runtime ID without changing SELF."""
        return self._players.get(player_name(name)).entityId

    def postToChat(self, message: str) -> None:
        """Broadcast literal text; buffered mode waits through flush/read/close."""
        if not isinstance(message, str):
            raise TypeError("Chat message must be a string")
        if not 1 <= len(message) <= 4096:
            raise ValueError("Chat message must contain 1–4096 characters")
        send = self._transport.submit if self._write_mode == "buffered" else self._transport.exchange
        send("chat.post", {"message": message}, mutation=True)

    def setBlock(self, x: int | float, y: int | float, z: int | float,
                 block: BlockInput, data: int = 0) -> None:
        """Установить блок через mc.blocks; режим ожидания выбран в create."""
        return self._blocks.setBlock(x, y, z, block, data)

    def setBlocks(self, x1: int | float, y1: int | float, z1: int | float,
                  x2: int | float, y2: int | float, z2: int | float,
                  block: BlockInput, data: int = 0) -> None:
        """Заполнить включённую область блоком; режим ожидания выбран в create."""
        return self._blocks.setBlocks(x1, y1, z1, x2, y2, z2, block, data)

    def getBlock(self, x: int | float, y: int | float, z: int | float) -> int:
        """Прочитать старый числовой ID; для полного современного блока — mc.blocks.getBlock."""
        return legacy_block_id(self._blocks.getBlock(x, y, z))

    def getBlocks(self, x1: int | float, y1: int | float, z1: int | float,
                  x2: int | float, y2: int | float, z2: int | float,
                  ) -> dict[tuple[int, int, int], int]:
        """Словарь абсолютные координаты → старый числовой ID без состояний."""
        return {position: legacy_block_id(specification) for position, specification in
                self._blocks.getBlocks(x1, y1, z1, x2, y2, z2).items()}

    def flush(self) -> None:
        """Дождаться всех предыдущих записей; сообщить отложенные ошибки."""
        self._transport.flush()

    def close(self) -> None:
        """Дождаться записей и закрыть соединение даже при ошибке; повтор безопасен."""
        with self._close_state.lock:
            if self._close_state.closed:
                return
            self._events._state.local_close()
            try:
                self._transport.finish()
            finally:
                self._close_state.closed = True

    def __repr__(self) -> str:
        return f"Minecraft(closed={self._transport.closed})"

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc_value: BaseException | None, traceback: TracebackType | None) -> Literal[False]:
        """Drain on exit; keep a body exception if closing also fails."""
        try:
            self.close()
        except BaseException as close_error:
            if exc_value is None:
                raise
            exc_value.add_note(f"Minebridge close() also failed: {type(close_error).__name__}: {close_error}")
        return False
