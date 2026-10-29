"""Typed game subscriptions, caller-thread dispatch and independent history."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import math
from typing import Any, TypeVar, cast
from uuid import UUID, uuid4

from .. import errors
from .._capabilities import require_capability
from .._event_state import (
    EventState, cursor_from_wire, cursor_to_wire, event_from_wire, wire_integer,
)
from .._protocol import CodecError, Response, EVENT_TYPES
from .._transport import TcpTransport
from ..models.events import (
    ChatEvent, Event, EventBatch, EventCursor, EventType, RecentEvents, Subscription, Region,
    BlockInteractEvent, EntityAttackEvent, EntityDamageEvent, ProjectileShotEvent, ProjectileHitEvent,
)
from ..models.blocks import BlockInput, BlockSpec, LegacyBlock, normalize_block
from ..models.entities import PlayerRef
from ..selector import ALL_PLAYERS, Selector
from .players import PlayerInput, Players, player_target

__all__ = ["Events", "Subscription", "EventPlayers"]

T = TypeVar("T", bound=Event)
EventPlayers = PlayerInput | Selector | Sequence[PlayerInput] | None


def _event_type(value: EventType[Any] | str) -> str:
    key = value.key if isinstance(value, EventType) else value
    if not isinstance(key, str):
        raise TypeError("eventType must be an events catalog key or string")
    if key not in EVENT_TYPES:
        raise errors.InvalidEventTypeError("Unknown event type; use the events catalog")
    return key


def _limit(value: int) -> int:
    if type(value) is not int:
        raise TypeError("limit must be an integer")
    if not 1 <= value <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    return value


class Events:
    __slots__ = ("_transport", "_world", "_executor", "_state")

    def __init__(self, transport: TcpTransport, world: str, executor: UUID | None = None) -> None:
        self._transport, self._world, self._executor = transport, world, executor
        state = getattr(transport, "_event_state", None)
        if state is None:
            context = transport.context
            if context is None:
                raise errors.ProtocolError("A successful handshake is required")
            state = EventState(context)
            transport._event_state = state
        self._state: EventState = state

    def _require(self, method: str, event_type: str | None = None) -> None:
        require_capability(self._transport, method)
        context = self._transport.context
        if context is None or context.event_history is None:
            raise errors.UnsupportedFeatureError("Server does not provide event metadata; update the Minebridge plugin")
        if event_type is not None and event_type != "chat.message":
            require_capability(self._transport, "events.type." + event_type)

    def _invalid(self, response: Response, method: str) -> None:
        self._transport.close()
        failure = errors.ProtocolError("Event result does not match the request")
        failure.request_id, failure.method = response.request_id, method
        raise failure

    def _players(self, value: EventPlayers, world: str) -> str | list[str] | None:
        if value is None:
            return None
        if isinstance(value, Selector) or isinstance(value, str) and value.startswith("@"):
            expression = value.expression if isinstance(value, Selector) else value
            if expression not in ("@a", "@s"):
                raise errors.InvalidSelectorError("Event subscriptions support only ALL_PLAYERS or SELF selectors")
            if expression == "@s" and self._executor is None:
                raise errors.MissingContextError("SELF requires Minecraft.create(player=...) or withContext(player=...)")
            return expression
        if isinstance(value, (str, UUID, PlayerRef)):
            return player_target(value)
        if isinstance(value, Sequence):
            if len(value) > 1024:
                raise ValueError("Explicit player list must contain at most 1024 players")
            players = Players(self._transport, world, self._executor)
            identities = []
            for target in value:
                normalized = player_target(target)
                try:
                    identity = UUID(normalized)
                except ValueError:
                    identity = players.get(target).uuid
                identities.append(str(identity))
            return list(dict.fromkeys(identities))
        raise TypeError("players must be ALL_PLAYERS, SELF, an explicit player or a sequence of players")

    def subscribe(self, eventType: EventType[T] | str, handler: Callable[[T], object] | None = None,
                  *, players: EventPlayers = ALL_PLAYERS, world: str | None = None,
                  region: Region | None = None, blocks: BlockInput | Sequence[BlockInput] | None = None) -> Subscription[T]:
        """Subscribe now; handlers execute only when you call run()."""
        key = _event_type(eventType)
        if handler is not None and not callable(handler):
            raise TypeError("handler must be callable or None")
        filters: dict[str, object] = {}
        if region is not None:
            if key in ("chat.message", "player.join", "player.quit"):
                raise ValueError("This event type does not support a region filter")
            if not isinstance(region, Region):
                raise TypeError("region must be a Region value")
            filters["region"] = {"world": str(region.world), "min": list(region.min), "max": list(region.max)}
        if blocks is not None:
            if not key.startswith("block."):
                raise ValueError("Only block events support a blocks filter")
            if isinstance(blocks, (int, str, BlockSpec, LegacyBlock)):
                values = [blocks]
            elif isinstance(blocks, Sequence):
                values = blocks
            else:
                raise TypeError("blocks must be a block or a sequence of blocks")
            keys = list(dict.fromkeys(normalize_block(value).key for value in values))
            if len(keys) > 256:
                raise ValueError("blocks must contain at most 256 different block keys")
            filters["blocks"] = keys
        selected_world = self._world if world is None else world
        if not isinstance(selected_world, str):
            raise TypeError("world must be a world name or key, or None")
        if not selected_world.strip() or "\x00" in selected_world:
            raise ValueError("world must be a nonempty world name or key")
        self._require("events.subscribe", key)
        selection = self._players(players, selected_world)
        identity = uuid4()
        with self._state.history_lock:
            known_world = self._state.world_aliases.get(selected_world)
        if region is not None and known_world is not None and region.world != known_world:
            raise ValueError("Region world must match the subscription world")
        item = self._state.prepare(identity, key, known_world, cast(Callable[[Event], object] | None, handler))
        try:
            response = self._transport.exchange("events.subscribe", {
                "subscriptionId": str(identity), "eventType": key, "world": selected_world,
                "executor": None if self._executor is None else str(self._executor), "players": selection,
                **filters,
            }, mutation=True)
            result = cast(dict[str, Any], response.result)
            if result["subscriptionId"] != str(identity) or result["eventType"] != key:
                self._invalid(response, "events.subscribe")
            resolved_world = UUID(result["world"])
            try:
                self._state.activate(item, resolved_world)
                with self._state.history_lock:
                    self._state.register_alias(selected_world, resolved_world)
            except CodecError:
                self._invalid(response, "events.subscribe")
            return Subscription(identity, EventType(key), resolved_world,
                                lambda: self._unsubscribe(item))
        except BaseException:
            self._state.remove(item)
            raise

    def _unsubscribe(self, item: Any) -> None:
        # Wait for an already-running callback on another thread. RLock allows a
        # callback to unsubscribe itself without deadlocking.
        with item.callback_lock:
            with self._state.condition:
                if item.status == "closed":
                    return
                item.status = "unsubscribing"
                self._state.queue = type(self._state.queue)(pair for pair in self._state.queue if pair[0] is not item)
                self._state.condition.notify_all()
            try:
                self._require("events.unsubscribe")
                response = self._transport.exchange("events.unsubscribe", {"subscriptionId": str(item.identity)}, mutation=True)
                result = cast(dict[str, Any], response.result)
                if result["subscriptionId"] != str(item.identity):
                    self._invalid(response, "events.unsubscribe")
            finally:
                self._state.remove(item)

    def run(self) -> None:
        """Dispatch sequentially in this calling thread until stop(), close() or an error."""
        self._require("events.subscribe")
        self._state.run()

    def poll(self, timeout: float | None = 0.0) -> Event | None:
        """Consume one live event without invoking its handler. None waits indefinitely."""
        if timeout is not None:
            if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
                raise TypeError("timeout must be a finite nonnegative number or None")
            try:
                timeout = float(timeout)
            except OverflowError:
                raise ValueError("timeout must be finite and nonnegative") from None
            if not math.isfinite(timeout) or timeout < 0:
                raise ValueError("timeout must be finite and nonnegative")
        self._require("events.subscribe")
        return self._state.poll(timeout)

    def stop(self) -> None:
        """Wake the current consumer; preserve subscriptions and queued events."""
        self._state.stop()

    def _cursor(self, key: str) -> EventCursor | None:
        world = self._state.world_aliases.get(self._world)
        return None if world is None else self._state.history_cursors.get(
            (key, world), self._state.history_baselines.get(world))

    def _page(self, response: Response, method: str, key: str, limit: int,
              cursor: EventCursor | None, upper: int | None = None) -> tuple[dict[str, Any], EventCursor, tuple[Event, ...]]:
        result = cast(dict[str, Any], response.result)
        next_cursor = cursor_from_wire(result["nextCursor"])
        known_world = self._state.world_aliases.get(self._world)
        records = tuple(event_from_wire(value) for value in result["events"])
        tail = wire_integer(result["upperBound"])
        available = wire_integer(result["availableFrom"])
        if (self._state.epoch != next_cursor.epoch
                or known_world is not None and next_cursor.world != known_world
                or len(records) > limit or upper is not None and tail != upper
                or cursor is not None and (
                    next_cursor.epoch != cursor.epoch or next_cursor.world != cursor.world
                    or next_cursor.sequence < cursor.sequence
                    or any(event.sequence <= cursor.sequence for event in records))
                or result["hasMore"] and cursor is not None and next_cursor.sequence <= cursor.sequence
                or any(event.sequence < available for event in records)
                or any(event.eventType.key != key for event in records)):
            self._invalid(response, method)
        try:
            self._state.register_alias(self._world, next_cursor.world)
        except CodecError:
            self._invalid(response, method)
        return result, next_cursor, records

    def pollEvents(self, eventType: EventType[T] | str, *, limit: int = 100) -> EventBatch[T]:
        """Read one journal page and commit its cursor only after full validation."""
        key, limit = _event_type(eventType), _limit(limit)
        self._require("events.pollEvents", key)
        with self._state.history_lock:
            cursor = self._cursor(key)
            response = self._transport.exchange("events.pollEvents", {
                "eventType": key, "world": self._world,
                "cursor": None if cursor is None else cursor_to_wire(cursor), "limit": limit,
            })
            result, next_cursor, records = self._page(response, "events.pollEvents", key, limit, cursor)
            batch = EventBatch(cast(tuple[T, ...], records), cursor, next_cursor, wire_integer(result["upperBound"]),
                               wire_integer(result["availableFrom"]), result["hasMore"])
            self._state.history_cursors[(key, next_cursor.world)] = next_cursor
            return batch

    def pollChatPosts(self, *, limit: int = 100) -> EventBatch[ChatEvent]:
        """Alias of pollEvents(events.CHAT_MESSAGE), sharing exactly the same cursor."""
        return self.pollEvents(EventType[ChatEvent]("chat.message"), limit=limit)

    def pollBlockHits(self, *, limit: int = 100) -> EventBatch[BlockInteractEvent]:
        """Read block.interact; BLOCK_HIT and the generic API share this cursor."""
        return self.pollEvents(EventType[BlockInteractEvent]("block.interact"), limit=limit)

    def pollEntityAttacks(self, *, limit: int = 100) -> EventBatch[EntityAttackEvent]:
        return self.pollEvents(EventType[EntityAttackEvent]("entity.attack"), limit=limit)

    def pollDamageEvents(self, *, limit: int = 100) -> EventBatch[EntityDamageEvent]:
        return self.pollEvents(EventType[EntityDamageEvent]("entity.damage"), limit=limit)

    def pollProjectileShots(self, *, limit: int = 100) -> EventBatch[ProjectileShotEvent]:
        return self.pollEvents(EventType[ProjectileShotEvent]("projectile.shot"), limit=limit)

    def pollProjectileHits(self, *, limit: int = 100) -> EventBatch[ProjectileHitEvent]:
        return self.pollEvents(EventType[ProjectileHitEvent]("projectile.hit"), limit=limit)

    def getRecent(self, eventType: EventType[T] | str, limit: int = 20) -> RecentEvents[T]:
        """Read the latest retained session events without moving the pull cursor."""
        key, limit = _event_type(eventType), _limit(limit)
        self._require("events.getRecent", key)
        with self._state.history_lock:
            records: list[Event] = []
            cursor, upper = None, None
            session_start, available, limited = None, 0, False
            identities: set[UUID] = set()
            while True:
                response = self._transport.exchange("events.getRecent", {
                    "eventType": key, "world": self._world, "limit": limit - len(records),
                    "cursor": None if cursor is None else cursor_to_wire(cursor), "upperBound": upper,
                })
                result, next_cursor, page = self._page(response, "events.getRecent", key,
                                                        limit - len(records), cursor, upper)
                start = wire_integer(result["sessionStart"])
                metadata = self._transport.context.event_history
                if (session_start is not None and session_start != start or next_cursor.sequence < start
                        or metadata is not None and str(next_cursor.world) == metadata.world
                        and start != metadata.start_sequence):
                    self._invalid(response, "events.getRecent")
                session_start = start
                upper = wire_integer(result["upperBound"])
                available = max(available, wire_integer(result["availableFrom"]))
                limited |= result["windowLimited"]
                if any(event.eventId in identities for event in page):
                    self._invalid(response, "events.getRecent")
                identities.update(event.eventId for event in page)
                records.extend(page)
                cursor = next_cursor
                if not result["hasMore"]:
                    break
                if len(records) >= limit or not page:
                    self._invalid(response, "events.getRecent")
            return RecentEvents(cast(tuple[T, ...], tuple(records)), cursor, upper, available,
                                session_start, limited)

    def clearPending(self, eventType: EventType[Any] | str | None = None) -> None:
        """Skip unread history for this connection; live events and server history stay intact."""
        key = None if eventType is None else _event_type(eventType)
        self._require("events.clearPending", key)
        with self._state.history_lock:
            response = self._transport.exchange("events.clearPending", {"eventType": key, "world": self._world})
            cursor = cursor_from_wire(cast(dict[str, Any], response.result)["cursor"])
            known_world = self._state.world_aliases.get(self._world)
            existing = [value.sequence for pair, value in self._state.history_cursors.items()
                        if pair[1] == cursor.world and (key is None or pair[0] == key)]
            baseline = self._state.history_baselines.get(cursor.world)
            if baseline is not None:
                existing.append(baseline.sequence)
            if (cursor.epoch != self._state.epoch or known_world is not None and cursor.world != known_world
                    or existing and cursor.sequence < max(existing)):
                self._invalid(response, "events.clearPending")
            try:
                self._state.register_alias(self._world, cursor.world)
            except CodecError:
                self._invalid(response, "events.clearPending")
            if key is None:
                self._state.history_baselines[cursor.world] = cursor
                self._state.history_cursors = {pair: value for pair, value in self._state.history_cursors.items()
                                               if pair[1] != cursor.world}
            else:
                self._state.history_cursors[(key, cursor.world)] = cursor

    def clearAll(self) -> None:
        """Alias of clearPending() for every event type in this connection's world."""
        self.clearPending()
