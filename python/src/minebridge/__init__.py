"""Python API для Paper: Minecraft.create, setBlock и типизированные блоки."""

from . import block, selector, items, effects, entity, gamemode, weather, gamerule, events, damageCause, slots
from .minecraft import Minecraft

__all__ = ["Minecraft", "block", "selector", "items", "effects", "entity", "gamemode", "weather", "gamerule", "events", "damageCause", "slots"]
__version__ = "0.3.1"

