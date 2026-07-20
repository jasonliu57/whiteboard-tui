from __future__ import annotations

import unittest
from fractions import Fraction

from tools.textart_notes.layouts.axis import (
    AxisPoint,
    AxisRange,
    quantize,
    quantize_points,
    round_half_up,
)


class AxisLayoutTests(unittest.TestCase):
    def test_half_up_and_inclusive_endpoints_are_exact(self) -> None:
        bounds = AxisRange(Fraction(0), Fraction(10))
        self.assertEqual(quantize(Fraction(0), bounds, 19), 0)
        self.assertEqual(quantize(Fraction(10), bounds, 19), 19)
        self.assertEqual(quantize(Fraction(5), bounds, 19), 10)
        self.assertEqual(round_half_up(Fraction(-3, 2)), -2)

    def test_collision_groups_keep_first_cell_and_point_order(self) -> None:
        bounds = AxisRange(Fraction(0), Fraction(10))
        groups = quantize_points(
            (
                AxisPoint("alpha", Fraction(5), Fraction(5)),
                AxisPoint("beta", Fraction(5), Fraction(5)),
                AxisPoint("origin", Fraction(0), Fraction(0)),
            ),
            bounds,
            bounds,
            plot_width=20,
            plot_height=5,
        )
        self.assertEqual([point.key for point in groups[0].points], ["alpha", "beta"])
        self.assertEqual((groups[1].qx, groups[1].qy), (0, 4))

    def test_invalid_range_duplicate_key_and_outside_value_fail(self) -> None:
        with self.assertRaises(ValueError):
            AxisRange(Fraction(1), Fraction(1))
        bounds = AxisRange(Fraction(0), Fraction(1))
        with self.assertRaises(ValueError):
            quantize(Fraction(2), bounds, 10)
        with self.assertRaises(ValueError):
            quantize_points(
                (AxisPoint("same", Fraction(0), Fraction(0)), AxisPoint("same", Fraction(1), Fraction(1))),
                bounds,
                bounds,
                plot_width=2,
                plot_height=2,
            )


if __name__ == "__main__":
    unittest.main()
