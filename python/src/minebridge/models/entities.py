"""Immutable entity references and results; property access never uses the network."""

from dataclasses import dataclass, field
from uuid import UUID

__all__ = ["EntityRef", "LivingEntityRef", "PlayerRef", "TargetOutcome", "TargetResult"]


@dataclass(frozen=True, slots=True)
class EntityRef:
    """A server entity UUID and its temporary runtime ID, not a student identity."""

    uuid: UUID
    entityId: int
    key: str | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.uuid, UUID):
            raise TypeError("Entity UUID must be a UUID value")
        if isinstance(self.entityId, bool) or not isinstance(self.entityId, int):
            raise TypeError("Runtime entity ID must be an integer")
        if not 0 <= self.entityId <= 2147483647:
            raise ValueError("Runtime entity ID must fit a nonnegative int32")
        if self.key is not None:
            from .keys import EntityTypeKey
            EntityTypeKey(self.key)


@dataclass(frozen=True, slots=True)
class LivingEntityRef(EntityRef):
    """A reference to a living entity."""


@dataclass(frozen=True, slots=True)
class PlayerRef(LivingEntityRef):
    """An online-player reference; the player may leave after it was obtained."""

    name: str
    key: str = field(default="minecraft:player", init=False, kw_only=True)

    def __post_init__(self) -> None:
        EntityRef.__post_init__(self)
        if not isinstance(self.name, str):
            raise TypeError("Player name must be a string")
        if not self.name.strip():
            raise ValueError("Player name must not be blank")

@dataclass(frozen=True, slots=True)
class TargetOutcome:
    uuid: UUID
    applied: bool
    code: str | None


@dataclass(frozen=True, slots=True)
class TargetResult:
    """One resolved target set and the outcome for every selected UUID."""

    matched: int
    applied: int
    targets: tuple[TargetOutcome, ...]
