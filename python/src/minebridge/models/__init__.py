"""Неизменяемые описания и нормализация аргументов."""

from .blocks import BlockInput, BlockSpec, LegacyBlock, normalize_block
from .coordinates import normalize_coordinate, normalize_position

__all__ = [
    "BlockInput",
    "BlockSpec",
    "LegacyBlock",
    "normalize_block",
    "normalize_coordinate",
    "normalize_position",
]

