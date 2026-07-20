from __future__ import annotations

import unittest

from tools.textart_notes.layouts.evidence_pair import SourceAnchor, SourceSlice, resolve_source_anchors
from tools.textart_notes.layouts.schema_blocks import Block, place_blocks


class AnchorAndBlockLayoutTests(unittest.TestCase):
    def test_anchor_order_overlap_and_original_numbers(self) -> None:
        source = SourceSlice(999, ("a", "b", "c", "d"))
        anchors = (
            SourceAnchor("later", 1001, 1002),
            SourceAnchor("outer", 999, 1002),
            SourceAnchor("nested", 1000, 1000),
        )
        resolved = resolve_source_anchors(source, anchors)
        self.assertEqual([item.key for item in resolved], ["later", "outer", "nested"])
        self.assertEqual(resolved[0].excerpt, ((1001, "c"), (1002, "d")))
        self.assertEqual(resolved[1].excerpt[0][0], 999)

    def test_invalid_anchors_and_block_placement(self) -> None:
        source = SourceSlice(10, ("x", "y"))
        with self.assertRaises(ValueError):
            resolve_source_anchors(source, (SourceAnchor("bad", 11, 10),))
        with self.assertRaises(ValueError):
            resolve_source_anchors(source, (SourceAnchor("bad", 9, 10),))
        placements = place_blocks(
            [Block("a", ("1", "2")), Block("b", ("3",))],
            start_y=4,
            gap=2,
        )
        self.assertEqual([(item.key, item.y, item.height) for item in placements], [("a", 4, 2), ("b", 8, 1)])


if __name__ == "__main__":
    unittest.main()
