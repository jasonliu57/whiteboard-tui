from __future__ import annotations

import unittest

from tools.textart_notes.core.canvas import Canvas, CanvasError


class CanvasTests(unittest.TestCase):
    def test_box_uses_merged_junctions(self) -> None:
        canvas = Canvas(7, 4, "unicode-light")
        canvas.draw_box(0, 0, 7, 4)
        self.assertEqual(canvas.to_lines(), ["┌─────┐", "│     │", "│     │", "└─────┘"])

    def test_crossing_paths_merge_bitmasks(self) -> None:
        canvas = Canvas(5, 5)
        canvas.draw_path(((0, 2), (4, 2)))
        canvas.draw_path(((2, 0), (2, 4)))
        self.assertEqual(canvas.to_lines()[2][2], "┼")

    def test_wide_continuation_rejects_collision(self) -> None:
        canvas = Canvas(5, 1)
        canvas.put_text(0, 0, "中")
        with self.assertRaisesRegex(CanvasError, "wide continuation"):
            canvas.put_text(1, 0, "X")
        self.assertEqual(canvas.to_text(), "中")

    def test_combining_mark_uses_anchor(self) -> None:
        canvas = Canvas(3, 1)
        canvas.put_text(0, 0, "e\u0301")
        self.assertEqual(canvas.to_text(), "e\u0301")

    def test_all_marks_require_non_whitespace_anchor(self) -> None:
        spacing_mark = "\u0903"
        for value in (spacing_mark, f" {spacing_mark}", f"\t{spacing_mark}"):
            with self.subTest(value=value), self.assertRaises(CanvasError):
                Canvas(5, 1).put_text(0, 0, value)
        canvas = Canvas(5, 1)
        self.assertEqual(canvas.put_text(0, 0, f"中{spacing_mark}X"), 4)
        self.assertEqual(canvas.to_text(), f"中{spacing_mark}X")


if __name__ == "__main__":
    unittest.main()
