from __future__ import annotations

import unittest

from tools.textart_notes.layouts.timeline import ceil_scaled_cells, scale_gap


class TimelineLayoutTests(unittest.TestCase):
    def test_exact_ceiling_boundaries(self) -> None:
        self.assertEqual([ceil_scaled_cells(value, 10) for value in (0, 1, 9, 10, 11)], [0, 1, 1, 1, 2])
        with self.assertRaises(ValueError):
            ceil_scaled_cells(-1, 10)
        with self.assertRaises(ValueError):
            ceil_scaled_cells(1, 0)

    def test_explicit_compression(self) -> None:
        self.assertEqual(scale_gap(25, 1, cap=6).raw_cells, 25)
        self.assertEqual(scale_gap(25, 1, cap=6).drawn_cells, 6)
        self.assertEqual(scale_gap(25, 1, cap=6).omitted_cells, 19)
        self.assertEqual(scale_gap(6, 1, cap=6).omitted_cells, 0)


if __name__ == "__main__":
    unittest.main()
