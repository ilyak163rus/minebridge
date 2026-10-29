"""Immutable event snapshots and bounded history results."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Generic, TypeVar, overload
from uuid import UUID

from .entities import EntityRef, PlayerRef
from .blocks import BlockSpec
from .keys import ItemKey
from ..damageCause import DamageCause

__all__ = ["EventType", "EventWorld", "EventCursor", "Event", "ChatEvent",
           "EventBatch", "RecentEvents", "Subscription", "EventPosition", "Region",
           "EventBlock", "EventLocation", "BlockBreakEvent", "BlockPlaceEvent", "BlockInteractEvent",
           "EntityAttackEvent", "EntityDamageEvent", "PlayerDamageEvent", "LavaEnterEvent",
           "PlayerJoinEvent", "PlayerQuitEvent", "PlayerDeathEvent", "PlayerRespawnEvent",
           "ProjectileShotEvent", "ProjectileHitEvent"]

T = TypeVar("T", covariant=True)


@dataclass(frozen=True, slots=True)
class EventType(Generic[T]):
    """A catalog key carrying the event model for IDE type inference."""

    key: str

    def __str__(self) -> str:
        return self.key


@dataclass(frozen=True, slots=True)
class EventWorld:
    uuid: UUID
    name: str
    key: str


@dataclass(frozen=True, slots=True)
class EventCursor:
    epoch: UUID
    world: UUID
    sequence: int


@dataclass(frozen=True, slots=True)
class Subscription(Generic[T]):
    id: UUID
    eventType: EventType[T]
    world: UUID
    _unsubscribe: Callable[[], None] = field(repr=False, compare=False)

    def unsubscribe(self) -> None:
        """Stop this subscription; calling again is safe."""
        self._unsubscribe()


@dataclass(frozen=True, slots=True)
class Event:
    eventId: UUID
    serverEpoch: UUID
    sequence: int
    serverTick: int
    eventType: EventType[Event]
    world: EventWorld
    subscriptionId: UUID | None = field(default=None, kw_only=True)
    deliverySequence: int | None = field(default=None, kw_only=True)


@dataclass(frozen=True, slots=True)
class ChatEvent(Event):
    player: PlayerRef
    message: str
    cancelled: bool
    truncated: bool


@dataclass(frozen=True, slots=True)
class EventPosition:
    x: float
    y: float
    z: float

    def __iter__(self) -> Iterator[float]:
        return iter((self.x, self.y, self.z))


@dataclass(frozen=True, slots=True, init=False)
class Region:
    """Inclusive block-coordinate bounds in an explicitly identified world."""

    world: UUID
    min: tuple[int, int, int]
    max: tuple[int, int, int]

    def __init__(self, world: UUID | str, corner1: Sequence[int], corner2: Sequence[int]) -> None:
        if not isinstance(world, (UUID, str)):
            raise TypeError("Region world must be a UUID or UUID string")
        identity = world if isinstance(world, UUID) else UUID(world)
        corners = []
        for corner in (corner1, corner2):
            if not isinstance(corner, Sequence) or isinstance(corner, (str, bytes)) or len(corner) != 3:
                raise TypeError("Region corners must contain three integer coordinates")
            if any(type(value) is not int for value in corner):
                raise TypeError("Region coordinates must be integers, not bool")
            if any(not -2147483648 <= value <= 2147483647 for value in corner):
                raise ValueError("Region coordinates must fit int32")
            corners.append(tuple(corner))
        object.__setattr__(self, "world", identity)
        object.__setattr__(self, "min", tuple(min(a, b) for a, b in zip(*corners)))
        object.__setattr__(self, "max", tuple(max(a, b) for a, b in zip(*corners)))


@dataclass(frozen=True, slots=True)
class EventBlock:
    position: EventPosition
    block: BlockSpec


@dataclass(frozen=True, slots=True)
class EventLocation:
    world: EventWorld
    position: EventPosition
    yaw: float
    pitch: float


@dataclass(frozen=True, slots=True)
class BlockBreakEvent(Event):
    player: PlayerRef
    position: EventPosition
    block: BlockSpec
    cancelled: bool


@dataclass(frozen=True, slots=True)
class BlockPlaceEvent(Event):
    player: PlayerRef
    position: EventPosition
    block: BlockSpec
    replacedBlock: BlockSpec
    cancelled: bool


@dataclass(frozen=True, slots=True)
class BlockInteractEvent(Event):
    player: PlayerRef
    position: EventPosition
    block: BlockSpec
    face: str | None
    action: str
    hand: str
    item: ItemKey | None
    useInteractedBlock: str
    useItemInHand: str
    cancelled: bool


@dataclass(frozen=True, slots=True)
class EntityAttackEvent(Event):
    player: PlayerRef
    target: EntityRef
    willAttack: bool
    cancelled: bool


@dataclass(frozen=True, slots=True)
class EntityDamageEvent(Event):
    victim: EntityRef
    directSource: EntityRef | None
    causingEntity: EntityRef | None
    cause: DamageCause | str
    rawDamage: float
    finalDamage: float
    cancelled: bool


@dataclass(frozen=True, slots=True)
class PlayerDamageEvent(EntityDamageEvent):
    @property
    def player(self) -> PlayerRef:
        assert isinstance(self.victim, PlayerRef)
        return self.victim


@dataclass(frozen=True, slots=True)
class LavaEnterEvent(Event):
    player: PlayerRef
    position: EventPosition


@dataclass(frozen=True, slots=True)
class PlayerJoinEvent(Event):
    player: PlayerRef


@dataclass(frozen=True, slots=True)
class PlayerQuitEvent(Event):
    player: PlayerRef


@dataclass(frozen=True, slots=True)
class PlayerDeathEvent(Event):
    player: PlayerRef
    position: EventPosition


@dataclass(frozen=True, slots=True)
class PlayerRespawnEvent(Event):
    player: PlayerRef
    reason: str
    respawnLocation: EventLocation


@dataclass(frozen=True, slots=True)
class ProjectileShotEvent(Event):
    projectile: EntityRef
    shooter: EntityRef | None
    sourceBlock: EventBlock | None
    position: EventPosition
    velocity: EventPosition
    weapon: ItemKey | None
    hand: str | None
    force: float | None
    cancelled: bool


@dataclass(frozen=True, slots=True)
class ProjectileHitEvent(Event):
    projectile: EntityRef
    shooter: EntityRef | None
    sourceBlock: EventBlock | None
    position: EventPosition
    hitEntity: EntityRef | None
    hitBlock: EventBlock | None
    hitFace: str | None
    cancelled: bool


@dataclass(frozen=True, slots=True)
class EventBatch(Sequence[T], Generic[T]):
    """One validated forward page. Reading this object does not perform I/O."""

    events: tuple[T, ...]
    fromCursor: EventCursor | None
    nextCursor: EventCursor
    upperBound: int
    availableFrom: int
    hasMore: bool

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self) -> Iterator[T]:
        return iter(self.events)

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[T, ...]: ...

    def __getitem__(self, index: int | slice) -> T | tuple[T, ...]:
        return self.events[index]


@dataclass(frozen=True, slots=True)
class RecentEvents(Sequence[T], Generic[T]):
    """An entire recent window, assembled against one fixed upper bound."""

    events: tuple[T, ...]
    nextCursor: EventCursor
    upperBound: int
    availableFrom: int
    sessionStart: int
    windowLimited: bool

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self) -> Iterator[T]:
        return iter(self.events)

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[T, ...]: ...

    def __getitem__(self, index: int | slice) -> T | tuple[T, ...]:
        return self.events[index]
