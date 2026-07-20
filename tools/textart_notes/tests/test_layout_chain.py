from __future__ import annotations

import unittest

from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.models import FitError
from tools.textart_notes.layouts.chain import ChainEntry, measure_chain, paginate_chain


class ChainLayoutTests(unittest.TestCase):
    def test_hanging_lines_align_after_stable_prefix(self) -> None:
        measured = measure_chain(
            (ChainEntry("s-10", "10.", "A long English sentence with 中文內容"),),
            18,
            start_column=1,
        )[0]
        self.assertGreater(measured.height, 1)
        self.assertTrue(measured.lines[0].startswith("10. "))
        self.assertTrue(all(line.startswith("    ") for line in measured.lines[1:]))
        self.assertTrue(all(text_width(line) <= 18 for line in measured.lines))

    def test_tabs_restart_at_hanging_body_column(self) -> None:
        measured = measure_chain(
            (ChainEntry("s", "1.", "1234567\tD"),),
            11,
            start_column=0,
        )[0]
        self.assertEqual(measured.lines, ("1. 1234567", "    D"))

    def test_pagination_preserves_complete_entry_order(self) -> None:
        entries = measure_chain(
            tuple(ChainEntry(f"s-{index}", f"{index}.", "alpha beta gamma") for index in range(1, 6)),
            12,
        )
        pages = paginate_chain(entries, 7, reserved_rows=2, separator_rows=1)
        self.assertEqual([entry.key for page in pages for entry in page], [f"s-{index}" for index in range(1, 6)])
        with self.assertRaises(FitError):
            paginate_chain(entries, 2, reserved_rows=1)


if __name__ == "__main__":
    unittest.main()
