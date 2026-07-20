from __future__ import annotations

import unittest

from tools.textart_notes.core.models import FitError
from tools.textart_notes.layouts.lanes import (
    LaneItem,
    allocate_lane_widths,
    lane_positions,
    synchronized_bands,
)


class LaneLayoutTests(unittest.TestCase):
    def test_widths_positions_and_remainders_are_stable(self) -> None:
        widths = allocate_lane_widths(50, 3, gutter=1, minimum=16)
        self.assertEqual(widths, (16, 16, 16))
        self.assertEqual(lane_positions(widths, gutter=1), (0, 17, 34))

    def test_synchronized_bands_preserve_complete_lane_ranges(self) -> None:
        bands = synchronized_bands(
            (
                (LaneItem("a", 3), LaneItem("b", 3), LaneItem("c", 3)),
                (),
                (LaneItem("x", 5),),
            ),
            7,
        )
        self.assertEqual(
            [band.ranges for band in bands],
            [((0, 2), (0, 0), (0, 1)), ((2, 3), (0, 0), (1, 1))],
        )
        self.assertEqual([band.content_height for band in bands], [7, 3])

    def test_all_empty_lanes_still_make_one_context_band(self) -> None:
        self.assertEqual(synchronized_bands(((), ()), 5)[0].ranges, ((0, 0), (0, 0)))
        with self.assertRaises(FitError):
            synchronized_bands(((LaneItem("too-tall", 6),),), 5)


if __name__ == "__main__":
    unittest.main()
