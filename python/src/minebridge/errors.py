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
    "ConnectionError", "OperationTimeoutError",
]


class MinecraftError(Exception):
    """Базовая ошибка. Текст предназначен человеку, code — программе."""

    code: str = "MINECRAFT_ERROR"

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


class ConnectionError(MinecraftError):
    """Соединение не установлено, закрыто или потеряно."""

    code: str = "CONNECTION_LOST"


class OperationTimeoutError(MinecraftError):
    """Истёк локальный срок подключения, передачи или ожидания ответа."""

    code: str = "TIMEOUT"

