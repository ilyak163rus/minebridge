"""Game modes available in offline IDE completion."""

from typing import Final
from .models.controls import GameMode

SURVIVAL: Final[GameMode] = GameMode.SURVIVAL
CREATIVE: Final[GameMode] = GameMode.CREATIVE
ADVENTURE: Final[GameMode] = GameMode.ADVENTURE
SPECTATOR: Final[GameMode] = GameMode.SPECTATOR

__all__ = ["SURVIVAL", "CREATIVE", "ADVENTURE", "SPECTATOR"]
