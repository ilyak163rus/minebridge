"""Проверки координат, не зависящие от версии или высоты мира сервера."""

import math
from dataclasses import dataclass
from typing import Final

__all__ = ["Location", "normalize_coordinate", "normalize_position", "normalize_real_coordinate"]

_INT32_MIN: Final = -(2**31)
_INT32_MAX: Final = 2**31 - 1


def normalize_real_coordinate(value: int | float) -> float:
    """Validate an entity coordinate without rounding it to a block."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("Coordinate must be int or float; bool is not supported")
    if not _INT32_MIN <= value <= _INT32_MAX or not math.isfinite(value):
        raise ValueError("Coordinate must be finite and within int32 bounds")
    return float(value)


@dataclass(frozen=True, slots=True)
class Location:
    """Absolute entity coordinates in a named world, including orientation."""

    world: str
    x: float
    y: float
    z: float
    yaw: float | None = None
    pitch: float | None = None


def normalize_coordinate(value: int | float) -> int:
    """Округлить вниз конечный int/float и проверить диапазон int32."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("Координата должна быть int или float; bool не допускается")
    # Не преобразуем int во float: даже очень большие целые проверяются точно.
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Координата должна быть конечным числом")
    result = math.floor(value)
    if not _INT32_MIN <= result <= _INT32_MAX:
        raise ValueError("Координата после округления должна помещаться в int32")
    return result


def normalize_position(x: int | float, y: int | float, z: int | float) -> tuple[int, int, int]:
    """Проверить три оси; высоту/мир позднее проверяет сервер."""

    return normalize_coordinate(x), normalize_coordinate(y), normalize_coordinate(z)

