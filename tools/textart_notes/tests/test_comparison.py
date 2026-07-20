from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.comparison_table_note import render
from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.core.validate import validate_result


HERE = Path(__file__).resolve().parent


def fixture() -> dict[str, object]:
    return json.loads((HERE / "fixtures/comparison/input.json").read_text(encoding="utf-8"))


class ComparisonRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 88, 40, True)
            result = render(fixture(), options)
            self.assertEqual(result, render(fixture(), options))
            validate_result(result, options)
            expected = (HERE / f"golden/comparison/{theme}.txt").read_text(encoding="utf-8")
            self.assertEqual(result.cards[0].text + "\n", expected)

    def test_horizontal_pages_share_synchronized_vertical_bands(self) -> None:
        data = {
            "title": "Wide comparison",
            "key_header": "Item",
            "columns": [
                {"id": f"c{index}", "header": f"Criterion {index}"}
                for index in range(4)
            ],
            "column_groups": [
                {"id": f"g{index}", "header": f"Group {index}", "column_ids": [f"c{index}"]}
                for index in range(4)
            ],
            "rows": [
                {
                    "key": f"r{row}",
                    "label": f"Row {row} 中文",
                    "cells": {f"c{column}": f"value {row}-{column} with words" for column in range(4)},
                }
                for row in range(7)
            ],
        }
        result = render(data, RenderOptions("unicode-light", 34, 14, False))
        self.assertGreater(max(card.metadata["horizontal_count"] for card in result.cards), 1)
        self.assertGreater(max(card.metadata["vertical_count"] for card in result.cards), 1)
        bands: dict[int, set[tuple[int, int, tuple[str, ...]]]] = {}
        for card in result.cards:
            bands.setdefault(card.metadata["vertical_index"], set()).add(
                (card.metadata["row_start"], card.metadata["row_end"], tuple(card.metadata["row_keys"]))
            )
        self.assertTrue(all(len(values) == 1 for values in bands.values()))
        with self.assertRaises(FitError):
            render(data, RenderOptions("unicode-light", 34, 14, True))

    def test_scalar_alignment_and_absolute_tabs(self) -> None:
        data = {
            "title": "A\tX",
            "key_header": "A\tX",
            "columns": [{"id": "value", "header": "A\tX", "align": "auto"}],
            "column_groups": [{"id": "g", "header": "G", "column_ids": ["value"]}],
            "rows": [{"key": "r", "label": "A\tX", "cells": {"value": 42}}],
        }
        card = render(data, RenderOptions("unicode-light", 40, 20, True)).cards[0]
        self.assertNotIn("\t", card.text)
        self.assertEqual(card.text.splitlines()[0], "A   X")
        numeric_line = next(line for line in card.text.splitlines() if "42" in line)
        self.assertIn(" 42 ", numeric_line)

    def test_schema_requires_complete_cells_and_atomic_groups(self) -> None:
        invalid = copy.deepcopy(fixture())
        del invalid["rows"][0]["cells"]["status"]
        with self.assertRaises(InputError):
            render(invalid, RenderOptions())
        narrow = copy.deepcopy(fixture())
        narrow["column_groups"] = [
            {"id": "all", "header": "All", "column_ids": [column["id"] for column in narrow["columns"]]}
        ]
        with self.assertRaises(FitError):
            render(narrow, RenderOptions("ascii", 25, 40, False))


if __name__ == "__main__":
    unittest.main()
