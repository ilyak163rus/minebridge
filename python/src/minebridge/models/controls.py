"""Typed world/player settings and immutable connection information."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, Literal, TypeVar
from uuid import UUID

__all__ = ["GameMode", "Weather", "GameRuleKey", "WorldInfo", "ConnectionInfo"]


class GameMode(StrEnum):
    SURVIVAL = "survival"
    CREATIVE = "creative"
    ADVENTURE = "adventure"
    SPECTATOR = "spectator"


class Weather(StrEnum):
    CLEAR = "clear"
    RAIN = "rain"
    THUNDER = "thunder"


RuleValue = TypeVar("RuleValue", bool, int)


@dataclass(frozen=True, slots=True)
class GameRuleKey(Generic[RuleValue]):
    """A known game rule with its real value type, independent of a connection."""

    key: str
    valueType: type[RuleValue]
    defaultValue: RuleValue

    def __post_init__(self) -> None:
        if not isinstance(self.key, str):
            raise TypeError("Game rule key must be a string")
        if not self.key or not self.key.strip() or "\x00" in self.key:
            raise ValueError("Game rule key must be nonempty and contain no NUL")
        if self.valueType is not bool and self.valueType is not int:
            raise TypeError("Game rule valueType must be bool or int")
        if type(self.defaultValue) is not self.valueType:
            raise TypeError("Game rule defaultValue must match valueType")


@dataclass(frozen=True, slots=True)
class WorldInfo:
    name: str
    key: str
    uuid: UUID
    minY: int
    maxYExclusive: int


@dataclass(frozen=True, slots=True)
class ConnectionInfo:
    """Negotiated hello metadata, not a live measurement of server state/TPS."""

    sessionId: UUID
    pluginVersion: str
    serverVersion: str
    protocolMajor: int
    protocolMinor: int
    world: WorldInfo
    writeMode: Literal["buffered", "sync"]
    logging: bool
    capabilities: tuple[str, ...]
