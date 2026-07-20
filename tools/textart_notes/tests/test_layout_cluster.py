from __future__ import annotations

import unittest

from tools.textart_notes.core.models import FitError
from tools.textart_notes.layouts.cluster import ClusterItem, ClusterSize, pack_shelves, rectangles_overlap


class ClusterLayoutTests(unittest.TestCase):
    def test_phase_variants_and_actual_shelves_are_deterministic(self) -> None:
        items = (
            ClusterItem("a", (ClusterSize(4, 2), ClusterSize(5, 2), ClusterSize(6, 2), ClusterSize(7, 2)), 2),
            ClusterItem("b", (ClusterSize(3, 4),), 0),
            ClusterItem("c", (ClusterSize(5, 1),), 0),
        )
        first = pack_shelves(items, max_width=11, gutter_x=1, gutter_y=2)
        self.assertEqual(first, pack_shelves(items, max_width=11, gutter_x=1, gutter_y=2))
        self.assertEqual([(item.key, item.x, item.y, item.width, item.height) for item in first.placements], [
            ("a", 0, 0, 6, 2),
            ("b", 7, 0, 3, 4),
            ("c", 0, 6, 5, 1),
        ])
        for index, item in enumerate(first.placements):
            self.assertTrue(all(not rectangles_overlap(item, other) for other in first.placements[index + 1 :]))

    def test_empty_duplicate_invalid_and_too_wide(self) -> None:
        self.assertEqual(pack_shelves((), max_width=10).placements, ())
        with self.assertRaises(ValueError):
            pack_shelves((ClusterItem("x", (ClusterSize(1, 1),)), ClusterItem("x", (ClusterSize(1, 1),))), max_width=10)
        with self.assertRaises(FitError):
            pack_shelves((ClusterItem("x", (ClusterSize(11, 1),)),), max_width=10)


if __name__ == "__main__":
    unittest.main()
