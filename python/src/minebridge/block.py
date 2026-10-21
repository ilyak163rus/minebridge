"""Знакомые константы mcpi. Доступны подсказки IDE без подключения к серверу."""

from typing import Final

from .models.blocks import LegacyBlock

__all__ = ["AIR", "STONE", "COBBLESTONE"]

AIR: Final[LegacyBlock] = LegacyBlock(0, 0)
"""Воздух: legacy ID 0, minecraft:air."""

STONE: Final[LegacyBlock] = LegacyBlock(1, 0)
"""Камень: legacy ID 1, minecraft:stone."""

COBBLESTONE: Final[LegacyBlock] = LegacyBlock(4, 0)
"""Булыжник: legacy ID 4, minecraft:cobblestone."""

