from __future__ import annotations

import copy
import json
import unittest
from decimal import Decimal
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.matrix_note import render


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "matrix" / "input.json"
GOLDEN = HERE / "golden" / "matrix"


def fixture() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def legend() -> list[dict[str, str]]:
    return [
        {"id": "ok", "label": "Okay 可接受", "marker": "circle"},
        {"id": "risk", "label": "Risk 風險", "marker": "alert"},
    ]


def axis(points: list[dict[str, object]]) -> dict[str, object]:
    return {
        "mode": "axis",
        "title": "Priority 優先",
        "x_axis": {"id": "effort", "label": "Effort 投入", "min": 0, "max": 10},
        "y_axis": {"id": "impact", "label": "Impact 影響", "min": 0, "max": 10},
        "plot_height": 5,
        "points": points,
        "legend": legend(),
    }


def grid(rows: int, columns: int) -> dict[str, object]:
    row_values = [{"id": f"row-{i}", "label": f"Row {i}"} for i in range(rows)]
    column_values = [{"id": f"col-{i}", "label": f"Col {i}"} for i in range(columns)]
    return {
        "mode": "grid",
        "title": "Large Matrix",
        "row_axis": {"id": "rows", "label": "Rows"},
        "column_axis": {"id": "columns", "label": "Columns"},
        "rows": row_values,
        "columns": column_values,
        "cells": [
            {"row_id": row["id"], "column_id": column["id"], "state_id": "ok", "label": f"{r},{c}"}
            for r, row in enumerate(row_values)
            for c, column in enumerate(column_values)
        ],
        "legend": legend(),
        "layout": {"row_label_width": 6, "min_cell_width": 6},
    }


def legend_tail(text: str) -> tuple[str, ...]:
    lines = text.splitlines()
    start = lines.index("Legend:")
    return tuple(lines[start:])


class MatrixRendererTests(unittest.TestCase):
    def test_grid_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            result = render(fixture(), RenderOptions(theme, 64, 30))
            self.assertEqual(result, render(copy.deepcopy(fixture()), RenderOptions(theme, 64, 30)))
            self.assertEqual(result.cards[0].text + "\n", (GOLDEN / f"{theme}.txt").read_text(encoding="utf-8"))

    def test_grid_rectangular_pages_repeat_context_and_never_split_rows(self) -> None:
        result = render(grid(5, 5), RenderOptions("ascii", 32, 18))
        self.assertGreater(len(result.cards), 3)
        rectangles = [
            (card.metadata["column_start"], card.metadata["row_start"], card.metadata["column_end"], card.metadata["row_end"])
            for card in result.cards
        ]
        self.assertEqual(rectangles, sorted(rectangles))
        self.assertEqual(len({legend_tail(card.text) for card in result.cards}), 1)
        observed = {
            (row_id, column_id)
            for card in result.cards
            for row_id in card.metadata["row_ids"]
            for column_id in card.metadata["column_ids"]
        }
        self.assertEqual(len(observed), 25)
        with self.assertRaises(FitError):
            render(grid(5, 5), RenderOptions("ascii", 32, 18, True))

    def test_axis_exact_endpoints_collisions_and_global_legend(self) -> None:
        points = [
            {"id": "minimum", "label": "Min", "x": Decimal("-0"), "y": 0, "state_id": "ok"},
            {"id": "middle-a", "label": "Middle A", "x": Decimal("5e0"), "y": 5, "state_id": "ok"},
            {"id": "middle-b", "label": "Middle B", "x": 5, "y": 5, "state_id": "risk"},
            {"id": "maximum", "label": "Max", "x": 10, "y": 10, "state_id": "risk"},
            *(
                {"id": f"extra-{index}", "label": f"Extra {index}", "x": value, "y": value, "state_id": "ok"}
                for index, value in enumerate((1, 2, 3, 4, 6, 7))
            ),
        ]
        result = render(axis(points), RenderOptions(max_width=40, max_height=22))
        self.assertGreater(len(result.cards), 1)
        flattened = [point for card in result.cards for point in card.metadata["point_ids"]]
        self.assertEqual(flattened, [point["id"] for point in points])
        middle_card = next(card for card in result.cards if "middle-a" in card.metadata["point_ids"])
        self.assertIn(["middle-a", "middle-b"], middle_card.metadata["collision_groups"])
        self.assertTrue(all("[collision]" in card.text for card in result.cards))
        quantized = {
            entry[0]: tuple(entry[1:])
            for card in result.cards
            for entry in card.metadata["quantized"]
        }
        self.assertEqual(quantized["minimum"], (0, 4))
        self.assertEqual(quantized["maximum"], (35, 0))
        with self.assertRaises(FitError):
            render(axis(points), RenderOptions(max_width=40, max_height=22, single_card=True))

    def test_invalid_rectangle_numeric_schema_and_indivisible_content(self) -> None:
        incomplete = fixture()
        incomplete["cells"].pop()
        with self.assertRaises(InputError):
            render(incomplete, RenderOptions())
        invalid = axis([{"id": "point", "label": "P", "x": True, "y": 0, "state_id": "ok"}])
        with self.assertRaises(InputError):
            render(invalid, RenderOptions())
        long_cell = grid(1, 1)
        long_cell["cells"][0]["label"] = "long prose 長篇 " * 100
        with self.assertRaises(FitError):
            render(long_cell, RenderOptions(max_width=24, max_height=18))


if __name__ == "__main__":
    unittest.main()
