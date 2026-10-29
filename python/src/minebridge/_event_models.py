"""Convert already validated wire snapshots into immutable public event models."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ._protocol import JsonNumber
from .damageCause import DamageCause
from .models.blocks import BlockSpec
from .models.entities import EntityRef, LivingEntityRef, PlayerRef
from .models.events import (
    Event, EventType, EventWorld, EventPosition, EventBlock, EventLocation,
    ChatEvent, BlockBreakEvent, BlockPlaceEvent, BlockInteractEvent,
    EntityAttackEvent, EntityDamageEvent, PlayerDamageEvent, LavaEnterEvent,
    PlayerJoinEvent, PlayerQuitEvent, PlayerDeathEvent, PlayerRespawnEvent,
    ProjectileShotEvent, ProjectileHitEvent,
)
from .models.keys import ItemKey


def number(value: Any) -> float:
    return float(value.text) if isinstance(value, JsonNumber) else float(value)


def integer(value: Any) -> int:
    return int(value.text) if isinstance(value, JsonNumber) else int(value)


def position(value: list[Any], *, block: bool = False) -> EventPosition:
    convert = integer if block else number
    return EventPosition(*(convert(v) for v in value))


def world(value: dict[str, Any]) -> EventWorld:
    return EventWorld(UUID(value["uuid"]), value["name"], value["key"])


def entity(value: dict[str, Any] | None) -> EntityRef | None:
    if value is None:
        return None
    identity, runtime = UUID(value["uuid"]), integer(value["entityId"])
    if value["key"] == "minecraft:player":
        return PlayerRef(identity, runtime, value["name"])
    kind = LivingEntityRef if value["living"] else EntityRef
    return kind(identity, runtime, key=value["key"])


def block(value: dict[str, Any]) -> BlockSpec:
    return BlockSpec(value["key"], value["states"])


def block_ref(value: dict[str, Any] | None) -> EventBlock | None:
    return None if value is None else EventBlock(position(value["position"], block=True), block(value["block"]))


def item(value: str | None) -> ItemKey | None:
    return None if value is None else ItemKey(value)


def event_from_wire(value: dict[str, Any], *, subscription_id: UUID | None = None,
                    delivery_sequence: int | None = None) -> Event:
    kind, data = value["eventType"], value["data"]
    base = (UUID(value["eventId"]), UUID(value["serverEpoch"]), integer(value["sequence"]),
            integer(value["serverTick"]), EventType(kind), world(value["world"]))
    delivery = {"subscriptionId": subscription_id, "deliverySequence": delivery_sequence}
    if kind == "chat.message":
        player = data["player"]
        return ChatEvent(*base, PlayerRef(UUID(player["uuid"]), integer(player["entityId"]), player["name"]),
                         data["message"], data["cancelled"], data["truncated"], **delivery)
    if kind == "block.break":
        return BlockBreakEvent(*base, entity(data["player"]), position(data["position"], block=True),
                               block(data["block"]), data["cancelled"], **delivery)
    if kind == "block.place":
        return BlockPlaceEvent(*base, entity(data["player"]), position(data["position"], block=True),
                               block(data["block"]), block(data["replacedBlock"]), data["cancelled"], **delivery)
    if kind == "block.interact":
        return BlockInteractEvent(*base, entity(data["player"]), position(data["position"], block=True),
                                  block(data["block"]), data["face"], data["action"], data["hand"], item(data["item"]),
                                  data["useInteractedBlock"], data["useItemInHand"], data["cancelled"], **delivery)
    if kind == "entity.attack":
        return EntityAttackEvent(*base, entity(data["player"]), entity(data["target"]),
                                 data["willAttack"], data["cancelled"], **delivery)
    if kind in ("entity.damage", "player.damage"):
        cls = PlayerDamageEvent if kind == "player.damage" else EntityDamageEvent
        try:
            cause = DamageCause(data["cause"])
        except ValueError:
            cause = data["cause"]
        return cls(*base, entity(data["victim"]), entity(data["directSource"]), entity(data["causingEntity"]),
                   cause, number(data["rawDamage"]), number(data["finalDamage"]), data["cancelled"], **delivery)
    if kind in ("player.enter_lava", "player.death"):
        cls = LavaEnterEvent if kind == "player.enter_lava" else PlayerDeathEvent
        return cls(*base, entity(data["player"]), position(data["position"]), **delivery)
    if kind in ("player.join", "player.quit"):
        cls = PlayerJoinEvent if kind == "player.join" else PlayerQuitEvent
        return cls(*base, entity(data["player"]), **delivery)
    if kind == "player.respawn":
        at = data["respawnLocation"]
        location = EventLocation(world(at["world"]), position(at["position"]), number(at["yaw"]), number(at["pitch"]))
        return PlayerRespawnEvent(*base, entity(data["player"]), data["reason"], location, **delivery)
    if kind == "projectile.shot":
        return ProjectileShotEvent(*base, entity(data["projectile"]), entity(data["shooter"]), block_ref(data["sourceBlock"]),
                                   position(data["position"]), position(data["velocity"]), item(data["weapon"]), data["hand"],
                                   None if data["force"] is None else number(data["force"]), data["cancelled"], **delivery)
    if kind == "projectile.hit":
        return ProjectileHitEvent(*base, entity(data["projectile"]), entity(data["shooter"]), block_ref(data["sourceBlock"]),
                                  position(data["position"]), entity(data["hitEntity"]), block_ref(data["hitBlock"]),
                                  data["hitFace"], data["cancelled"], **delivery)
    raise ValueError("Unsupported event snapshot type")
