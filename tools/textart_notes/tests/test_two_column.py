from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.core.validate import validate_result
from tools.textart_notes.two_column_note import render


HERE = Path(__file__).resolve().parent


def fixture() -> dict[str, object]:
    return json.loads((HERE / "fixtures/two_column/input.json").read_text(encoding="utf-8"))


class TwoColumnRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 72, 24, True)
            result = render(fixture(), options)
            self.assertEqual(result, render(fixture(), options))
            validate_result(result, options)
            expected = (HERE / f"golden/two_column/{theme}.txt").read_text(encoding="utf-8")
            self.assertEqual(result.cards[0].text + "\n", expected)

    def test_complete_pairs_are_the_only_split_boundary(self) -> None:
        data = fixture()
        result = render(data, RenderOptions("unicode-light", 72, 8, False))
        self.assertEqual([pair for card in result.cards for pair in card.metadata["pair_ids"]], ["ev-01", "ev-02", "ev-03"])
        self.assertTrue(all(len(card.metadata["pair_ids"]) == 1 for card in result.cards))
        self.assertTrue(all("原文 / Evidence" in card.text and "解釋 / Commentary" in card.text for card in result.cards))
        with self.assertRaises(FitError):
            render(data, RenderOptions("unicode-light", 72, 8, True))

    def test_nowrap_fails_and_tabs_use_each_physical_side_origin(self) -> None:
        data = {
            "title": "\tTitle",
            "columns": {
                "left": {"label": "\tLabel", "wrap": False},
                "right": {"label": "\tLabel", "wrap": False},
            },
            "width_ratio": {"left": 1, "right": 1},
            "pairs": [{"id": "tabs", "left": "\tX", "right": "\tX"}],
        }
        card = render(data, RenderOptions("ascii", 29, 20, True)).cards[0]
        fields = next(line for line in card.text.splitlines() if line.count("|") == 3 and "X" in line).split("|")
        self.assertTrue(fields[1].startswith("   X"))
        self.assertTrue(fields[2].startswith(" X"))
        self.assertNotIn("\t", card.text)
        invalid = copy.deepcopy(data)
        invalid["pairs"][0]["left"] = "x" * 20
        with self.assertRaises(FitError):
            render(invalid, RenderOptions("ascii", 29, 20, True))

    def test_duplicate_pair_id_is_invalid(self) -> None:
        data = fixture()
        data["pairs"].append(copy.deepcopy(data["pairs"][0]))
        with self.assertRaises(InputError):
            render(data, RenderOptions())


if __name__ == "__main__":
    unittest.main()
