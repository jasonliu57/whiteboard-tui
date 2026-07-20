from __future__ import annotations

import unittest

from tools.textart_notes.core.cell_width import (
    cell_clusters,
    char_width,
    expand_tabs,
    pad_cells,
    split_prefix,
    text_width,
    validate_combining_anchors,
)


class CellWidthTests(unittest.TestCase):
    def test_ascii_cjk_fullwidth_and_combining(self) -> None:
        self.assertEqual(text_width("abc中文Ａe\u0301"), 3 + 4 + 2 + 1)
        self.assertEqual(char_width("\u0301"), 0)

    def test_tabs_follow_cell_columns(self) -> None:
        self.assertEqual(expand_tabs("中\tX"), "中  X")
        self.assertEqual(text_width("中\tX"), 5)

    def test_prefix_never_splits_a_wide_character(self) -> None:
        self.assertEqual(split_prefix("A中B", 2), ("A", "中B"))
        self.assertEqual(split_prefix("A中B", 3), ("A中", "B"))

    def test_spacing_mark_stays_with_anchor_at_split_boundary(self) -> None:
        spacing_mark = "\u0903"
        self.assertEqual(char_width(spacing_mark), 1)
        self.assertEqual(cell_clusters(f"中{spacing_mark}X"), (f"中{spacing_mark}", "X"))
        self.assertEqual(split_prefix(f"中{spacing_mark}X", 2), ("", f"中{spacing_mark}X"))
        self.assertEqual(split_prefix(f"x中{spacing_mark}X", 3), ("x", f"中{spacing_mark}X"))
        validate_combining_anchors(f"A{spacing_mark}")
        with self.assertRaises(ValueError):
            validate_combining_anchors(f" {spacing_mark}")

    def test_padding_is_cell_aware(self) -> None:
        self.assertEqual(pad_cells("中", 4), "中  ")
        self.assertEqual(text_width(pad_cells("中", 4)), 4)


if __name__ == "__main__":
    unittest.main()
