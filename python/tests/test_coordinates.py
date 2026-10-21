"""Coordinate validation before any request can be sent to a server."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
import math
import unittest

from minebridge.models.coordinates import normalize_coordinate, normalize_position


INT32_MIN = -(2 ** 31)
INT32_MAX = 2 ** 31 - 1


class CoordinateTests(unittest.TestCase):
    def test_fractional_coordinates_use_floor_including_negatives(self) -> None:
        cases = (
            (0, 0), (1, 1), (-1, -1),
            (0.0, 0), (-0.0, 0),
            (0.2, 0), (0.999, 0), (1.999, 1),
            (-0.2, -1), (-0.999, -1), (-1.001, -2),
            (16.5, 16), (-16.5, -17),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                actual = normalize_coordinate(value)
                self.assertEqual(actual, expected)
                self.assertIs(type(actual), int)

    def test_int32_boundaries_apply_after_floor(self) -> None:
        cases = (
            (INT32_MIN, INT32_MIN),
            (INT32_MAX, INT32_MAX),
            (float(INT32_MIN), INT32_MIN),
            (float(INT32_MAX), INT32_MAX),
            (INT32_MIN + 0.25, INT32_MIN),
            (INT32_MAX + 0.75, INT32_MAX),
            (math.nextafter(0.0, -math.inf), -1),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(normalize_coordinate(value), expected)

    def test_out_of_range_numbers_raise_value_error_even_for_enormous_integers(self) -> None:
        for value in (INT32_MIN - 1, INT32_MAX + 1,
                      INT32_MIN - 0.25, float(INT32_MAX + 1),
                      -(10 ** 1000), 10 ** 1000, -1e308, 1e308):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_coordinate(value)

    def test_nan_and_both_infinities_raise_value_error(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_coordinate(value)

    def test_only_int_or_float_are_accepted_and_bool_is_rejected(self) -> None:
        for value in (True, False, None, "1", b"1", complex(1, 0),
                      Decimal("1"), Fraction(1, 1), [], {}, object()):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    normalize_coordinate(value)  # type: ignore[arg-type]

    def test_position_preserves_axis_order_and_returns_integer_tuple(self) -> None:
        position = normalize_position(1.9, -0.2, -16.5)
        self.assertEqual(position, (1, -1, -17))
        self.assertIs(type(position), tuple)
        self.assertTrue(all(type(value) is int for value in position))

    def test_each_axis_is_validated(self) -> None:
        for axis in range(3):
            for invalid, error in ((True, TypeError), ("1", TypeError),
                                   (math.nan, ValueError), (math.inf, ValueError),
                                   (INT32_MAX + 1, ValueError)):
                coordinates = [0, 0, 0]
                coordinates[axis] = invalid
                with self.subTest(axis=axis, value=invalid):
                    with self.assertRaises(error):
                        normalize_position(*coordinates)  # type: ignore[arg-type]

    def test_world_specific_height_limits_are_not_guessed_by_client(self) -> None:
        self.assertEqual(normalize_position(0, -1000, 0), (0, -1000, 0))
        self.assertEqual(normalize_position(0, 1000, 0), (0, 1000, 0))


if __name__ == "__main__":
    unittest.main()
