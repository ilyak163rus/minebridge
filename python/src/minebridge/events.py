"""Typed event catalog, available to IDEs without a server connection."""

from typing import Final

from .models.events import (
    EventType, ChatEvent, BlockBreakEvent, BlockPlaceEvent, BlockInteractEvent,
    EntityAttackEvent, EntityDamageEvent, PlayerDamageEvent, LavaEnterEvent,
    PlayerJoinEvent, PlayerQuitEvent, PlayerDeathEvent, PlayerRespawnEvent,
    ProjectileShotEvent, ProjectileHitEvent,
)

__all__ = ["CHAT_MESSAGE", "BLOCK_INTERACT", "BLOCK_HIT", "BLOCK_BREAK", "BLOCK_PLACE",
           "ENTITY_ATTACK", "ENTITY_DAMAGE", "PLAYER_DAMAGE", "PLAYER_ENTER_LAVA",
           "PLAYER_JOIN", "PLAYER_QUIT", "PLAYER_DEATH", "PLAYER_RESPAWN",
           "PROJECTILE_SHOT", "PROJECTILE_HIT"]

CHAT_MESSAGE: Final[EventType[ChatEvent]] = EventType("chat.message")
BLOCK_INTERACT: Final[EventType[BlockInteractEvent]] = EventType("block.interact")
BLOCK_HIT: Final[EventType[BlockInteractEvent]] = BLOCK_INTERACT
BLOCK_BREAK: Final[EventType[BlockBreakEvent]] = EventType("block.break")
BLOCK_PLACE: Final[EventType[BlockPlaceEvent]] = EventType("block.place")
ENTITY_ATTACK: Final[EventType[EntityAttackEvent]] = EventType("entity.attack")
ENTITY_DAMAGE: Final[EventType[EntityDamageEvent]] = EventType("entity.damage")
PLAYER_DAMAGE: Final[EventType[PlayerDamageEvent]] = EventType("player.damage")
PLAYER_ENTER_LAVA: Final[EventType[LavaEnterEvent]] = EventType("player.enter_lava")
PLAYER_JOIN: Final[EventType[PlayerJoinEvent]] = EventType("player.join")
PLAYER_QUIT: Final[EventType[PlayerQuitEvent]] = EventType("player.quit")
PLAYER_DEATH: Final[EventType[PlayerDeathEvent]] = EventType("player.death")
PLAYER_RESPAWN: Final[EventType[PlayerRespawnEvent]] = EventType("player.respawn")
PROJECTILE_SHOT: Final[EventType[ProjectileShotEvent]] = EventType("projectile.shot")
PROJECTILE_HIT: Final[EventType[ProjectileHitEvent]] = EventType("projectile.hit")
