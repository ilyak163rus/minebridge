"""Spawn one registry entity through the server's public API."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias, cast
from uuid import UUID

from .._transport import TcpTransport
from ..errors import ProtocolError
from ..models import (
    BlockInput, EntityRef, EntityTypeKey, ItemInput, LivingEntityRef,
    normalize_block, normalize_item, normalize_real_coordinate,
)
from ._items import item_to_wire
from .players import PlayerInput, _integer, player_target

__all__ = ["Entities", "EntityFace"]

EntityFace: TypeAlias = Literal["north", "south", "east", "west", "up", "down"]
_FACES = ("north", "south", "east", "west", "up", "down")


class Entities:
    """Spawn entities, including lightning, at fractional world coordinates."""

    __slots__ = ("_transport", "_world")

    def __init__(self, transport: TcpTransport, world: str) -> None:
        self._transport = transport
        self._world = world

    def spawn(self, entityType: EntityTypeKey | str,
              x: int | float, y: int | float, z: int | float, *,
              world: str | None = None, item: ItemInput | None = None,
              block: BlockInput | None = None, face: EntityFace | None = None,
              owner: PlayerInput | None = None) -> EntityRef:
        """Spawn once and wait for an entity reference in either write mode.

        Special types may require item, block, face or owner. Paper validates
        each type's supported options before mutation. No automatic retries run
        if the response is lost after sending the operation.
        """
        if isinstance(entityType, str):
            entityType = EntityTypeKey(entityType)
        if not isinstance(entityType, EntityTypeKey):
            raise TypeError("entityType must be EntityTypeKey or a namespace:path string")
        position = [normalize_real_coordinate(value) for value in (x, y, z)]
        if world is not None and not isinstance(world, str):
            raise TypeError("world must be a world name or key, or None")
        if world is not None and (not world.strip() or "\x00" in world):
            raise ValueError("world must be a nonempty world name or key")
        if face is not None and not isinstance(face, str):
            raise TypeError("face must be one of north, south, east, west, up or down")
        if face is not None and face not in _FACES:
            raise ValueError("face must be one of north, south, east, west, up or down")
        item_value = None if item is None else item_to_wire(normalize_item(item))
        block_value = None if block is None else normalize_block(block)
        response = self._transport.exchange("entities.spawn", {
            "world": self._world, "destinationWorld": world, "position": position,
            "entity": {"key": entityType.key},
            "options": {
                "item": item_value,
                "block": None if block_value is None else {
                    "key": block_value.key, "states": dict(block_value.states)},
                "face": face, "owner": None if owner is None else player_target(owner),
            },
        }, mutation=True)
        value = cast(dict[str, Any], response.result)["entity"]
        if value["key"] != entityType.key:
            self._transport.close()
            error = ProtocolError("Spawn result does not match the requested entity type",
                                  outcome="unknown")
            error.request_id = response.request_id
            error.method = "entities.spawn"
            raise error
        entity_class = LivingEntityRef if value["living"] else EntityRef
        return entity_class(UUID(value["uuid"]), _integer(value["entityId"]), key=value["key"])
