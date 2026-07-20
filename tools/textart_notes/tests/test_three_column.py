from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.core.validate import validate_result
from tools.textart_notes.three_column_note import render


HERE = Path(__file__).resolve().parent


def fixture() -> dict[str, object]:
    return json.loads((HERE / "fixtures/three_column/input.json").read_text(encoding="utf-8"))


class ThreeColumnRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 60, 30, True)
            result = render(fixture(), options)
            self.assertEqual(result, render(fixture(), options))
            validate_result(result, options)
            expected = (HERE / f"golden/three_column/{theme}.txt").read_text(encoding="utf-8")
            self.assertEqual(result.cards[0].text + "\n", expected)

    def test_complete_rows_split_and_repeat_footer(self) -> None:
        data = fixture()
        result = render(data, RenderOptions("unicode-light", 60, 10, False))
        self.assertEqual([(card.metadata["row_start"], card.metadata["row_end"]) for card in result.cards], [(0, 1), (1, 2), (2, 3)])
        self.assertTrue(all("來源 Source" in card.text for card in result.cards))
        with self.assertRaises(FitError):
            render(data, RenderOptions("unicode-light", 60, 10, True))

    def test_ratio_tabs_use_all_three_absolute_origins(self) -> None:
        data = {
            "title": "\tTitle",
            "columns": [
                {"key": "a", "label": "\tA"},
                {"key": "b", "label": "\tB"},
                {"key": "c", "label": "\tC"},
            ],
            "rows": [{"a": "\tD", "b": "\tE", "c": "\tF"}],
            "widths": {"mode": "ratio", "ratios": [1, 2, 1]},
        }
        card = render(data, RenderOptions("ascii", 32, 20, True)).cards[0]
        self.assertEqual(card.metadata["column_widths"], [7, 14, 7])
        row = next(line for line in card.text.splitlines() if "D" in line and "E" in line and "F" in line)
        fields = row.split("|")[1:4]
        self.assertTrue(fields[0].startswith("   D"))
        self.assertTrue(fields[1].startswith("   E"))
        self.assertTrue(fields[2].startswith("    F"))

    def test_measured_mode_and_schema_failures(self) -> None:
        data = fixture()
        data["widths"] = {"mode": "measured"}
        result = render(data, RenderOptions("unicode-light", 60, 30, True))
        self.assertEqual(sum(result.cards[0].metadata["column_widths"]), 56)
        invalid = copy.deepcopy(data)
        del invalid["rows"][0]["action"]
        with self.assertRaises(InputError):
            render(invalid, RenderOptions())
        nonfinite = fixture()
        nonfinite["widths"] = {"mode": "ratio", "ratios": [1, float("nan"), 1]}
        with self.assertRaises(InputError):
            render(nonfinite, RenderOptions())


if __name__ == "__main__":
    unittest.main()
