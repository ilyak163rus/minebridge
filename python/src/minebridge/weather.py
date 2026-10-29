"""Weather constants available without connecting to Paper."""

from typing import Final
from .models.controls import Weather

CLEAR: Final[Weather] = Weather.CLEAR
RAIN: Final[Weather] = Weather.RAIN
THUNDER: Final[Weather] = Weather.THUNDER

__all__ = ["CLEAR", "RAIN", "THUNDER"]
