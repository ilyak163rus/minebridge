"""One bounded live dispatcher and independent history cursors per connection.

The receiver may only validate/enqueue. User handlers run in run()'s caller.
No state lock is held while calling a handler or issuing a synchronous RPC.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
import threading
import time
from typing import Any, TYPE_CHECKING
from uuid import UUID

from . import errors
from ._protocol import CodecError, JsonNumber
from .models.events import Event, EventCursor
from .models.entities import PlayerRef

if TYPE_CHECKING:
    from ._handshake import SessionContext


def wire_integer(value: Any) -> int:
    return int(value.text) if isinstance(value, JsonNumber) else int(value)


def cursor_from_wire(value: dict[str, Any]) -> EventCursor:
    return EventCursor(UUID(value["epoch"]), UUID(value["world"]), wire_integer(value["sequence"]))


def cursor_to_wire(value: EventCursor) -> dict[str, object]:
    return {"epoch": str(value.epoch), "world": str(value.world), "sequence": value.sequence}


from ._event_models import event_from_wire


@dataclass
class _LiveSubscription:
    identity: UUID
    event_type: str
    world: UUID | None
    handler: Callable[[Event], object] | None
    status: str = "pending"
    delivery_sequence: int = 0
    journal_sequence: int = 0
    acknowledged: bool = False
    failure: errors.EventOverflowError | None = None
    callback_lock: Any = field(default_factory=threading.RLock)


class EventState:
    def __init__(self, context: SessionContext) -> None:
        self.condition = threading.Condition()
        self.history_lock = threading.RLock()
        self.subscriptions: dict[UUID, _LiveSubscription] = {}
        self.queue: deque[tuple[_LiveSubscription, Event]] = deque()
        self.tombstones: deque[UUID] = deque()
        self._tombstone_set: set[UUID] = set()
        self._consumer = False
        self._generation = 0
        self._closed = False
        self._failure: errors.MinecraftError | None = None
        self.history_cursors: dict[tuple[str, UUID], EventCursor] = {}
        self.history_baselines: dict[UUID, EventCursor] = {}
        self.world_aliases = {context.world.name: UUID(context.world.uuid),
                              context.world.key: UUID(context.world.uuid),
                              context.world.uuid: UUID(context.world.uuid)}
        metadata = context.event_history
        self.epoch = UUID(metadata.epoch) if metadata else None
        self.max_events = min(512, metadata.max_live_events) if metadata else 512
        self.max_subscriptions = min(32, metadata.max_subscriptions) if metadata else 32
        if metadata:
            baseline = EventCursor(UUID(metadata.epoch), UUID(metadata.world), metadata.start_sequence)
            self.history_baselines[baseline.world] = baseline

    @property
    def has_stream(self) -> bool:
        with self.condition:
            return bool(self.subscriptions or self.tombstones)

    def register_alias(self, alias: str, world: UUID) -> None:
        # The server limits retained worlds; keep client aliases bounded too.
        if alias not in self.world_aliases and len(self.world_aliases) >= 256:
            return
        previous = self.world_aliases.get(alias)
        if previous is not None and previous != world:
            raise CodecError("INVALID_RESPONSE")
        self.world_aliases[alias] = world

    def prepare(self, identity: UUID, event_type: str, world: UUID | None,
                handler: Callable[[Event], object] | None) -> _LiveSubscription:
        with self.condition:
            if self._closed:
                raise errors.ConnectionError("TCP connection is closed")
            if self._failure is not None:
                raise errors.ConnectionError("TCP connection is closed")
            if len(self.subscriptions) >= self.max_subscriptions:
                raise errors.LimitExceededError("Event subscription limit was exceeded")
            item = _LiveSubscription(identity, event_type, world, handler)
            self.subscriptions[identity] = item
            return item

    def activate(self, item: _LiveSubscription, world: UUID) -> None:
        with self.condition:
            if item.world is not None and item.world != world:
                raise CodecError("INVALID_RESPONSE")
            item.world = world
            if item.status == "pending":
                item.status = "active"
            self.condition.notify_all()

    def acknowledge(self, identity: str, result: dict[str, Any]) -> None:
        """Record wire order while leaving dispatch PENDING until subscribe returns."""
        with self.condition:
            item = self.subscriptions.get(UUID(identity))
            if (item is None or result["subscriptionId"] != identity
                    or result["eventType"] != item.event_type
                    or item.world is not None and str(item.world) != result["world"]):
                raise CodecError("INVALID_RESPONSE")
            item.world = UUID(result["world"])
            item.acknowledged = True

    def remove(self, item: _LiveSubscription) -> None:
        with self.condition:
            item.status = "closed"
            item.handler = None
            self.subscriptions.pop(item.identity, None)
            self.queue = deque(pair for pair in self.queue if pair[0] is not item)
            if not self._closed and self._failure is None and item.identity not in self._tombstone_set:
                if len(self.tombstones) >= 256:
                    self._tombstone_set.discard(self.tombstones.popleft())
                self.tombstones.append(item.identity)
                self._tombstone_set.add(item.identity)
            self.condition.notify_all()

    def _known(self, identity: UUID) -> _LiveSubscription | None:
        item = self.subscriptions.get(identity)
        if item is None and identity not in self._tombstone_set:
            raise CodecError("INVALID_RESPONSE")
        return item

    def _overflow(self, items: list[_LiveSubscription], source: str, count: int) -> None:
        identities = tuple(item.identity for item in items)
        for item in items:
            if item.status != "closed":
                item.status = "broken"
                item.failure = errors.EventOverflowError(
                    "Live event delivery lost records; unsubscribe the affected subscription",
                    source=source, lostCount=count, subscriptionIds=identities)
        self.queue = deque(pair for pair in self.queue if pair[0].status != "broken")
        self.condition.notify_all()

    def receive(self, notification: tuple[str, dict[str, Any]]) -> None:
        """Receiver-only operation: bounded state updates, never user code."""
        method, params = notification
        with self.condition:
            if self._closed:
                return
            if method == "events.overflow":
                items = [item for identity in params["subscriptionIds"]
                         if (item := self._known(UUID(identity))) is not None]
                if any(not item.acknowledged for item in items):
                    raise CodecError("INVALID_RESPONSE")
                self._overflow(items, params["source"], wire_integer(params["lostCount"]))
                return
            identity = UUID(params["subscriptionId"])
            item = self._known(identity)
            if item is None or item.status in ("closed", "unsubscribing"):
                return
            if not item.acknowledged:
                raise CodecError("INVALID_RESPONSE")
            value = params["event"]
            world = UUID(value["world"]["uuid"])
            if (value["eventType"] != item.event_type
                    or self.epoch is not None and UUID(value["serverEpoch"]) != self.epoch
                    or item.world is not None and world != item.world):
                raise CodecError("INVALID_RESPONSE")
            if item.status == "broken":
                return
            delivery, sequence = wire_integer(params["deliverySequence"]), wire_integer(value["sequence"])
            if delivery != item.delivery_sequence + 1 or sequence <= item.journal_sequence:
                raise CodecError("INVALID_RESPONSE")
            item.world = world
            item.delivery_sequence, item.journal_sequence = delivery, sequence
            if len(self.queue) >= self.max_events:
                self._overflow([item], "python", 1)
                return
            self.queue.append((item, event_from_wire(value, subscription_id=identity,
                                                     delivery_sequence=delivery)))
            self.condition.notify_all()

    def stop(self) -> None:
        with self.condition:
            self._generation += 1
            self.condition.notify_all()

    def local_close(self) -> None:
        with self.condition:
            self._closed = True
            self.queue.clear()
            for item in self.subscriptions.values():
                item.status = "closed"
                item.handler = None
            self.subscriptions.clear()
            self.tombstones.clear()
            self._tombstone_set.clear()
            self.condition.notify_all()

    def fail(self, failure: errors.MinecraftError) -> None:
        with self.condition:
            if not self._closed and self._failure is None:
                self._failure = failure
                self.queue.clear()
                for item in self.subscriptions.values():
                    item.status = "closed"
                    item.handler = None
                self.subscriptions.clear()
                self.tombstones.clear()
                self._tombstone_set.clear()
            self.condition.notify_all()

    def _claim(self, *, handlers: bool) -> int:
        with self.condition:
            if self._consumer:
                raise RuntimeError("Only one events.run() or events.poll() consumer is allowed per connection")
            if handlers and any(item.handler is None and item.status in ("pending", "active")
                                for item in self.subscriptions.values()):
                raise ValueError("events.run() requires a handler for each active subscription")
            self._consumer = True
            return self._generation

    def _release(self) -> None:
        with self.condition:
            self._consumer = False
            self.condition.notify_all()

    def _take(self, generation: int, deadline: float | None, *, handlers: bool = False) -> tuple[_LiveSubscription, Event] | None:
        with self.condition:
            while True:
                if self._closed or self._generation != generation:
                    return None
                if self._failure is not None:
                    raise self._failure
                for item in self.subscriptions.values():
                    if item.failure is not None:
                        # Repeated poll errors must not grow a retained traceback
                        # chain on the status stored for this subscription.
                        failure = item.failure
                        raise errors.EventOverflowError(
                            str(failure), source=failure.source, lostCount=failure.lostCount,
                            subscriptionIds=failure.subscriptionIds)
                    if handlers and item.status in ("pending", "active") and item.handler is None:
                        raise ValueError("events.run() requires a handler for each active subscription")
                if self.queue and self.queue[0][0].status == "active":
                    return self.queue.popleft()
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    self.condition.wait(remaining)
                else:
                    self.condition.wait()

    def poll(self, timeout: float | None) -> Event | None:
        generation = self._claim(handlers=False)
        try:
            pair = self._take(generation, None if timeout is None else time.monotonic() + timeout)
            return None if pair is None else pair[1]
        finally:
            self._release()

    def run(self) -> None:
        generation = self._claim(handlers=True)
        try:
            while (pair := self._take(generation, None, handlers=True)) is not None:
                item, event = pair
                with item.callback_lock:
                    with self.condition:
                        if self._closed or generation != self._generation:
                            return
                        if item.status != "active":
                            continue
                        handler = item.handler
                    if handler is None:
                        raise ValueError("events.run() requires a handler for each active subscription")
                    handler(event)
        finally:
            self._release()
