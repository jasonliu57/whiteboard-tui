from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.core.validate import validate_result
from tools.textart_notes.cornell_note import render


HERE = Path(__file__).resolve().parent


def fixture() -> dict[str, object]:
    return json.loads((HERE / "fixtures/cornell/input.json").read_text(encoding="utf-8"))


class CornellRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 64, 30, True)
            result = render(fixture(), options)
            self.assertEqual(result, render(fixture(), options))
            validate_result(result, options)
            expected = (HERE / f"golden/cornell/{theme}.txt").read_text(encoding="utf-8")
            self.assertEqual(result.cards[0].text + "\n", expected)

    def test_only_complete_pairs_split_and_summary_repeats(self) -> None:
        data = fixture()
        data["pairs"] = [
            {"id": f"pair-{index}", "cue": f"線索 {index}", "note": "long note 中文 words " * 4}
            for index in range(7)
        ]
        data["summary"] = "共享 summary"
        result = render(data, RenderOptions("unicode-light", 48, 20, False))
        self.assertGreater(len(result.cards), 1)
        self.assertEqual(
            [pair_id for card in result.cards for pair_id in card.metadata["pair_ids"]],
            [f"pair-{index}" for index in range(7)],
        )
        self.assertTrue(all(card.text.count("SUMMARY: 共享 summary") == 1 for card in result.cards))
        self.assertTrue(all("TOPIC:" in card.text and "CUE / 線索" in card.text for card in result.cards))
        with self.assertRaises(FitError):
            render(data, RenderOptions("unicode-light", 48, 20, True))

    def test_ratio_boundaries_tabs_and_invalid_ratio(self) -> None:
        for ratio in (0.25, 0.35):
            data = fixture()
            data["cue_ratio"] = ratio
            data["topic"] = "\tTopic"
            data["pairs"] = [{"id": "tabs", "cue": "A\tB", "note": "1234567\tC"}]
            data["summary"] = "\tSummary"
            card = render(data, RenderOptions("ascii", 48, 30, True)).cards[0]
            self.assertNotIn("\t", card.text)
            self.assertEqual(sum(card.metadata["column_widths"]), 41)
        invalid = fixture()
        invalid["cue_ratio"] = 0.36
        with self.assertRaises(InputError):
            render(invalid, RenderOptions())

    def test_indivisible_pair_and_summary_fail_without_crop(self) -> None:
        data = fixture()
        data["pairs"] = [{"id": "huge", "cue": "cue", "note": "資料 " * 300}]
        with self.assertRaises(FitError):
            render(data, RenderOptions("ascii", 40, 18, False))
        data = fixture()
        data["summary"] = "摘要 " * 400
        with self.assertRaises(FitError):
            render(data, RenderOptions("ascii", 48, 20, False))


if __name__ == "__main__":
    unittest.main()
