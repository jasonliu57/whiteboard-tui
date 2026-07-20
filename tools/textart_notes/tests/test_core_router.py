from __future__ import annotations

import unittest

from tools.textart_notes.core.router import shortest_grid_route, validate_cell_route


class GridRouterTests(unittest.TestCase):
    def test_bounded_monotone_route_is_deterministic_and_valid(self) -> None:
        blocked = {(3, y) for y in range(1, 5)}
        first = shortest_grid_route((1, 0), (5, 5), width=7, height=6, blocked=blocked, monotone_vertical=True)
        self.assertEqual(first, shortest_grid_route((1, 0), (5, 5), width=7, height=6, blocked=blocked, monotone_vertical=True))
        validate_cell_route(first, start=(1, 0), end=(5, 5))
        self.assertFalse(set(first) & blocked)
        self.assertTrue(all(0 <= y <= 5 for _, y in first))

    def test_no_route_and_invalid_path(self) -> None:
        with self.assertRaises(ValueError):
            shortest_grid_route((0, 0), (2, 2), width=3, height=3, blocked={(0, 1), (1, 0)}, monotone_vertical=True)
        with self.assertRaises(ValueError):
            validate_cell_route(((0, 0), (2, 0)))
        with self.assertRaises(ValueError):
            validate_cell_route(((0, 0), (1, 0), (0, 0)))


if __name__ == "__main__":
    unittest.main()
