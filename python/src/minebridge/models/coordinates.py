"""Проверки координат, не зависящие от версии или высоты мира сервера."""

import math
from typing import Final

__all__ = ["normalize_coordinate", "normalize_position"]

_INT32_MIN: Final = -(2**31)
_INT32_MAX: Final = 2**31 - 1


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

