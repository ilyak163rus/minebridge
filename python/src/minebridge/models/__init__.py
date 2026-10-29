"""Неизменяемые описания и нормализация аргументов."""

from .blocks import BlockInput, BlockSpec, LegacyBlock, normalize_block
from .coordinates import Location, normalize_coordinate, normalize_position, normalize_real_coordinate
from .entities import EntityRef, LivingEntityRef, PlayerRef, TargetOutcome, TargetResult
from .keys import ItemKey, EffectKey, EntityTypeKey
from .items import ItemStack, ItemInput, OverflowMode, InventoryOutcome, InventoryResult, normalize_item
from .controls import GameMode, Weather, GameRuleKey, WorldInfo, ConnectionInfo
from .inventories import ItemView, InventoryPart, InventoryInfo, InventoryRef, SlotWriteResult, InventoryUpdateResult
from .events import (
    EventType, EventWorld, EventCursor, Event, ChatEvent, EventBatch, RecentEvents, Subscription,
    EventPosition, Region, EventBlock, EventLocation, BlockBreakEvent, BlockPlaceEvent, BlockInteractEvent,
    EntityAttackEvent, EntityDamageEvent, PlayerDamageEvent, LavaEnterEvent,
    PlayerJoinEvent, PlayerQuitEvent, PlayerDeathEvent, PlayerRespawnEvent,
    ProjectileShotEvent, ProjectileHitEvent,
)

__all__ = [
    "BlockInput",
    "BlockSpec",
    "LegacyBlock",
    "normalize_block",
    "normalize_coordinate",
    "normalize_position",
    "normalize_real_coordinate",
    "Location", "EntityRef", "LivingEntityRef", "PlayerRef", "TargetOutcome", "TargetResult",
    "ItemKey", "EffectKey", "EntityTypeKey", "ItemStack", "ItemInput", "OverflowMode",
    "InventoryOutcome", "InventoryResult", "normalize_item",
    "GameMode", "Weather", "GameRuleKey", "WorldInfo", "ConnectionInfo",
    "ItemView", "InventoryPart", "InventoryInfo", "InventoryRef", "SlotWriteResult", "InventoryUpdateResult",
    "EventType", "EventWorld", "EventCursor", "Event", "ChatEvent", "EventBatch", "RecentEvents", "Subscription",
    "EventPosition", "Region", "EventBlock", "EventLocation", "BlockBreakEvent", "BlockPlaceEvent", "BlockInteractEvent",
    "EntityAttackEvent", "EntityDamageEvent", "PlayerDamageEvent", "LavaEnterEvent", "PlayerJoinEvent",
    "PlayerQuitEvent", "PlayerDeathEvent", "PlayerRespawnEvent", "ProjectileShotEvent", "ProjectileHitEvent",
]

