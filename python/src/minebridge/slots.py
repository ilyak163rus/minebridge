"""Public player equipment slots; storage and chest slots use integer indices."""

from enum import StrEnum
from typing import Final, TypeAlias

__all__ = ["EquipmentSlot", "Slot", "HEAD", "CHEST", "LEGS", "FEET", "OFF_HAND"]


class EquipmentSlot(StrEnum):
    HEAD = "head"
    CHEST = "chest"
    LEGS = "legs"
    FEET = "feet"
    OFF_HAND = "off_hand"


Slot: TypeAlias = int | EquipmentSlot
HEAD: Final = EquipmentSlot.HEAD
CHEST: Final = EquipmentSlot.CHEST
LEGS: Final = EquipmentSlot.LEGS
FEET: Final = EquipmentSlot.FEET
OFF_HAND: Final = EquipmentSlot.OFF_HAND
