from __future__ import annotations

import unittest
from fractions import Fraction

from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.models import FitError
from tools.textart_notes.layouts.grid import (
    Column,
    GridRow,
    ShelfItem,
    allocate_toward_demands,
    allocate_weighted,
    allocate_widths,
    measure_rows,
    pack_row_major,
    paginate_rows,
    render_table,
    split_column_groups,
    table_content_budget,
)


class GridLayoutTests(unittest.TestCase):
    def test_row_major_card_packing_uses_actual_width_and_row_height(self) -> None:
        placements = pack_row_major(
            (
                ShelfItem("a", 56, 8),
                ShelfItem("b", 80, 13),
                ShelfItem("c", 48, 9),
                ShelfItem("d", 60, 7),
            ),
            columns=3,
            gutter_x=4,
            gutter_y=2,
        )
        self.assertEqual(
            [(item.key, item.x, item.y, item.row, item.column) for item in placements],
            [("a", 0, 0, 0, 0), ("b", 60, 0, 0, 1), ("c", 144, 0, 0, 2), ("d", 0, 15, 1, 0)],
        )

    def setUp(self) -> None:
        self.columns = (
            Column("item", "Item / 項目", 6, 2),
            Column("a", "A", 4, 1),
            Column("b", "B", 4, 1),
        )

    def test_weighted_allocation_is_exact(self) -> None:
        allocation = allocate_widths(24, self.columns)
        self.assertEqual(allocation, (11, 7, 6))
        self.assertEqual(sum(allocation), 24)

    def test_fractional_and_demand_allocators_are_exact(self) -> None:
        weighted = allocate_weighted(
            28,
            (Fraction(1), Fraction(2), Fraction(1)),
            (2, 2, 2),
        )
        self.assertEqual(weighted, (7, 14, 7))
        demanded = allocate_toward_demands(20, (3, 3, 3), (4, 12, 5))
        self.assertEqual(sum(demanded), 20)
        self.assertGreater(demanded[1], demanded[0])

    def test_cjk_rows_measure_independently(self) -> None:
        widths = allocate_widths(table_content_budget(40, 3), self.columns)
        rows = measure_rows(
            (GridRow("r1", ("中文 item", "short", "a much longer explanation")),),
            self.columns,
            widths,
        )
        self.assertGreater(rows[0].height, 1)
        table = render_table(self.columns, widths, rows, "unicode-light")
        self.assertTrue(all(text_width(line) == 40 for line in table))

    def test_pagination_never_splits_a_measured_row(self) -> None:
        widths = allocate_widths(table_content_budget(40, 3), self.columns)
        rows = measure_rows(
            tuple(GridRow(f"r{i}", (str(i), "alpha beta", "中文內容")) for i in range(5)),
            self.columns,
            widths,
        )
        pages = paginate_rows(rows, 5)
        self.assertEqual([row.key for page in pages for row in page], [f"r{i}" for i in range(5)])
        with self.assertRaises(FitError):
            paginate_rows(rows, 1)

    def test_column_groups_always_repeat_key_column(self) -> None:
        columns = (self.columns[0],) + tuple(
            Column(f"c{i}", f"Column {i}", 9) for i in range(5)
        )
        groups = split_column_groups(columns, 32)
        self.assertGreater(len(groups), 1)
        self.assertTrue(all(group[0] == 0 for group in groups))
        self.assertEqual([index for group in groups for index in group[1:]], list(range(1, 6)))

    def test_nowrap_cell_fails_instead_of_cropping(self) -> None:
        columns = (Column("x", "X", 3, wrap=False),)
        with self.assertRaisesRegex(FitError, "nowrap"):
            measure_rows((GridRow("r", ("too-wide",)),), columns, (3,))

    def test_row_alignment_overrides_header_alignment(self) -> None:
        columns = (Column("value", "Value", 6, align="center"),)
        rows = measure_rows((GridRow("r", ("42",), ("right",)),), columns, (6,))
        table = render_table(columns, (6,), rows, "ascii", padding=0)
        self.assertIn("|    42|", table)


if __name__ == "__main__":
    unittest.main()
