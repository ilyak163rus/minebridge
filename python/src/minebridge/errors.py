"""Ошибки Minebridge с машинными кодами и явным исходом."""

from typing import Literal

__all__ = [
    "MinecraftError",
    "InvalidBlockError",
    "UnsupportedLegacyBlockError",
    "UnsupportedFeatureError",
    "ProtocolError", "ProtocolVersionError", "InvalidArgumentError",
    "ServerOperationError", "AuthenticationError", "LimitExceededError",
    "WorldNotFoundError", "PermissionDeniedError", "CoordinateOutOfBoundsError",
    "ChunkNotLoadedError",
    "RegionBusyError", "ChunkLoadError",
    "InvalidItemError", "InvalidEffectError", "InvalidEntityTypeError",
    "UnsupportedEntityTypeError", "EntityNotFoundError", "PeacefulSpawnError",
    "PlayerNotFoundError", "InvalidSelectorError", "MissingContextError",
    "InvalidTargetError", "ContextWorldMismatchError",
    "InvalidGameModeError", "InvalidGameRuleError", "InvalidRuleValueError",
    "InvalidPlayerValueError", "InvalidWeatherError", "WorldChangeRejectedError",
    "ConnectionError", "OperationTimeoutError",
    "InvalidEventTypeError", "SubscriptionNotFoundError", "EventHistoryLostError",
    "EventOverflowError",
    "InventoryNotFoundError", "InventoryChangedError", "InvalidSlotError",
    "InvalidItemAmountError", "InventoryWriteRejectedError",
]


class MinecraftError(Exception):
    """Базовая ошибка. Текст предназначен человеку, code — программе."""

    code: str = "MINECRAFT_ERROR"
    request_id: int | None = None
    method: str | None = None
    failures: tuple["MinecraftError", ...] = ()

    def __init__(
        self,
        message: str,
        *,
        outcome: Literal["not-applied", "unknown"] = "not-applied",
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.outcome = outcome
        if code is not None:
            self.code = code


class InvalidBlockError(MinecraftError):
    """Некорректное описание блока."""

    code: str = "INVALID_BLOCK"


class UnsupportedLegacyBlockError(InvalidBlockError):
    """Пара старых ID/data не входит в совместимый набор этой версии."""

    code: str = "UNSUPPORTED_LEGACY_BLOCK"


class UnsupportedFeatureError(MinecraftError):
    """Возможность ещё не поддерживается текущим срезом."""

    code: str = "UNSUPPORTED_FEATURE"


class ProtocolError(MinecraftError):
    """Повреждённое сообщение или нарушение протокола."""

    code: str = "PROTOCOL_ERROR"


class ProtocolVersionError(ProtocolError):
    """Несовместимая основная версия протокола."""

    code: str = "PROTOCOL_VERSION"


class InvalidArgumentError(MinecraftError):
    code: str = "INVALID_PARAMS"


class ServerOperationError(MinecraftError):
    code: str = "INTERNAL_ERROR"


class AuthenticationError(MinecraftError):
    code: str = "AUTH_FAILED"


class LimitExceededError(MinecraftError):
    code: str = "LIMIT_EXCEEDED"


class WorldNotFoundError(MinecraftError):
    code: str = "WORLD_NOT_FOUND"


class PermissionDeniedError(MinecraftError):
    code: str = "PERMISSION_DENIED"


class CoordinateOutOfBoundsError(MinecraftError):
    code: str = "COORDINATE_OUT_OF_BOUNDS"


class ChunkNotLoadedError(MinecraftError):
    code: str = "CHUNK_NOT_LOADED"


class RegionBusyError(MinecraftError):
    """Область занята другой стройкой через Minebridge."""

    code: str = "REGION_BUSY"


class ChunkLoadError(MinecraftError):
    """Серверу не удалось загрузить или сгенерировать чанк."""

    code: str = "CHUNK_LOAD_FAILED"


class PlayerNotFoundError(MinecraftError):
    code: str = "PLAYER_NOT_FOUND"


class InvalidSelectorError(MinecraftError):
    code: str = "INVALID_SELECTOR"


class MissingContextError(MinecraftError):
    code: str = "MISSING_CONTEXT"


class InvalidTargetError(MinecraftError):
    code: str = "INVALID_TARGET"


class ContextWorldMismatchError(MinecraftError):
    code: str = "CONTEXT_WORLD_MISMATCH"


class InvalidItemError(MinecraftError):
    code: str = "INVALID_ITEM"


class InvalidEffectError(MinecraftError):
    code: str = "INVALID_EFFECT"


class InvalidEntityTypeError(MinecraftError):
    code: str = "INVALID_ENTITY_TYPE"


class UnsupportedEntityTypeError(MinecraftError):
    code: str = "UNSUPPORTED_ENTITY_TYPE"


class EntityNotFoundError(MinecraftError):
    code: str = "ENTITY_NOT_FOUND"


class PeacefulSpawnError(MinecraftError):
    """The destination world's Peaceful difficulty prevents this entity spawn."""

    code: str = "PEACEFUL_SPAWN_BLOCKED"


class InvalidGameModeError(MinecraftError):
    code: str = "INVALID_GAME_MODE"


class InvalidGameRuleError(MinecraftError):
    code: str = "INVALID_GAME_RULE"


class InvalidRuleValueError(MinecraftError):
    code: str = "INVALID_RULE_VALUE"


class InvalidPlayerValueError(MinecraftError):
    code: str = "INVALID_PLAYER_VALUE"


class InvalidWeatherError(MinecraftError):
    code: str = "INVALID_WEATHER"


class WorldChangeRejectedError(MinecraftError):
    code: str = "WORLD_CHANGE_REJECTED"


class ConnectionError(MinecraftError):
    """Соединение не установлено, закрыто или потеряно."""

    code: str = "CONNECTION_LOST"


class OperationTimeoutError(MinecraftError):
    """Истёк локальный срок подключения, передачи или ожидания ответа."""

    code: str = "TIMEOUT"


class InvalidEventTypeError(MinecraftError):
    code: str = "INVALID_EVENT_TYPE"


class SubscriptionNotFoundError(MinecraftError):
    code: str = "SUBSCRIPTION_NOT_FOUND"


class EventHistoryLostError(MinecraftError):
    """The requested history interval has expired or includes capture loss."""

    code: str = "EVENT_HISTORY_LOST"


class EventOverflowError(MinecraftError):
    """A live subscription lost events; unsubscribe it before resuming dispatch."""

    code: str = "EVENT_QUEUE_OVERFLOW"

    def __init__(self, message: str, *, source: str | None = None,
                 lostCount: int | None = None, subscriptionIds: tuple[object, ...] = (),
                 outcome: Literal["not-applied", "unknown"] = "not-applied",
                 code: str | None = None) -> None:
        super().__init__(message, outcome=outcome, code=code)
        self.source = source
        self.lostCount = lostCount
        self.subscriptionIds = subscriptionIds


class InventoryNotFoundError(MinecraftError):
    code: str = "INVENTORY_NOT_FOUND"


class InventoryChangedError(MinecraftError):
    code: str = "INVENTORY_CHANGED"


class InvalidSlotError(MinecraftError):
    code: str = "INVALID_SLOT"


class InvalidItemAmountError(MinecraftError):
    code: str = "INVALID_ITEM_AMOUNT"


class InventoryWriteRejectedError(MinecraftError):
    code: str = "INVENTORY_WRITE_REJECTED"

