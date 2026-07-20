from __future__ import annotations

import unittest

from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.wrap import (
    wrap_clusters,
    wrap_line,
    wrap_preserving_line,
    wrap_text,
)


class WrapTests(unittest.TestCase):
    def test_mixed_text_never_exceeds_width(self) -> None:
        lines = wrap_line("alpha 中文內容 beta", 8)
        self.assertTrue(all(text_width(line) <= 8 for line in lines))
        self.assertEqual("".join(lines).replace(" ", ""), "alpha中文內容beta")

    def test_hanging_indent(self) -> None:
        lines = wrap_text(
            "A fairly long English sentence 中文段落",
            18,
            initial_indent="- ",
            subsequent_indent="  ",
        )
        self.assertTrue(lines[0].startswith("- "))
        self.assertTrue(all(line.startswith("  ") for line in lines[1:]))
        self.assertTrue(all(text_width(line) <= 18 for line in lines))

    def test_tab_expands_from_actual_content_column(self) -> None:
        self.assertEqual(wrap_line("A\tB", 8, start_column=2), ["A B"])

    def test_leading_and_continuation_tabs_reuse_physical_origin(self) -> None:
        self.assertEqual(wrap_line("\tX", 8, start_column=1), ["   X"])
        self.assertEqual(wrap_line("\tX", 8, start_column=3), [" X"])
        self.assertEqual(
            wrap_line("1234567\tD", 7, start_column=1),
            ["1234567", "   D"],
        )

    def test_spacing_mark_cluster_is_never_split_from_anchor(self) -> None:
        spacing_mark = "\u0903"
        lines = wrap_preserving_line("x" * 29 + f"A{spacing_mark}", 30)
        self.assertEqual(lines, ["x" * 29, f"A{spacing_mark}"])
        self.assertTrue(all(text_width(line) <= 30 for line in lines))

    def test_cluster_wrap_is_character_greedy_and_restarts_tab_phase(self) -> None:
        self.assertEqual(wrap_clusters("clustered", 4), ["clus", "tere", "d"])
        self.assertEqual(wrap_clusters("1234567\tD", 7, start_column=1), ["1234567", "   D"])
        self.assertEqual(wrap_clusters("xA\u0903", 2), ["x", "A\u0903"])


if __name__ == "__main__":
    unittest.main()
