from __future__ import annotations

import unittest

from tools.textart_notes.core.models import InputError
from tools.textart_notes.layouts.hierarchy import analyze_hierarchy
from tools.textart_notes.layouts.radial import RadialSize, layout_radial


class RadialLayoutTests(unittest.TestCase):
    def facts(self):
        children = {"root": ("a", "b", "c"), "a": ("a1",), "b": (), "c": (), "a1": ()}
        return children, analyze_hierarchy("root", tuple(children), children)

    def test_stable_sides_rings_and_routes_avoid_nodes(self) -> None:
        children, facts = self.facts()
        sizes = {key: RadialSize(7 + len(key), 3) for key in children}
        first = layout_radial(facts, children, sizes, anchor_id="root")
        self.assertEqual(first, layout_radial(facts, children, sizes, anchor_id="root"))
        self.assertEqual(dict(first.top_level_sides), {"a": "right", "b": "left", "c": "right"})
        rects = [item.rect for item in first.placements]
        for edge in first.edges:
            self.assertTrue(edge.cells)
            self.assertTrue(all(not rect.contains(cell) for rect in rects for cell in edge.cells))
        for index, rect in enumerate(rects):
            self.assertTrue(all(not (
                rect.x < other.x + other.width and other.x < rect.x + rect.width
                and rect.y < other.y + other.height and other.y < rect.y + rect.height
            ) for other in rects[index + 1 :]))

    def test_summary_and_invalid_hierarchy(self) -> None:
        children, facts = self.facts()
        sizes = {key: RadialSize(7, 3) for key in children}
        summary = layout_radial(facts, children, sizes, anchor_id="root", summary_children=("a", "b"))
        self.assertEqual([item.key for item in summary.placements], ["root", "a", "b"])
        with self.assertRaises(InputError):
            analyze_hierarchy("root", ("root", "a"), {"root": ("a",), "a": ("root",)})
        with self.assertRaises(InputError):
            analyze_hierarchy("root", ("root", "a", "b"), {"root": ("a", "b"), "a": (), "b": ("a",)})


if __name__ == "__main__":
    unittest.main()
