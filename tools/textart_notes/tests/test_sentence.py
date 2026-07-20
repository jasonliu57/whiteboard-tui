from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.core.validate import validate_result
from tools.textart_notes.sentence_note import render


HERE = Path(__file__).resolve().parent


def fixture() -> dict[str, object]:
    return json.loads((HERE / "fixtures/sentence/input.json").read_text(encoding="utf-8"))


class SentenceRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 64, 20, True)
            result = render(fixture(), options)
            self.assertEqual(result, render(fixture(), options))
            validate_result(result, options)
            expected = (HERE / f"golden/sentence/{theme}.txt").read_text(encoding="utf-8")
            self.assertEqual(result.cards[0].text + "\n", expected)

    def test_numbering_never_restarts_at_complete_sentence_splits(self) -> None:
        data = {"title": "Lecture", "sentences": [{"text": f"Point {index}."} for index in range(1, 9)]}
        result = render(data, RenderOptions("ascii", 30, 5, False))
        self.assertEqual(
            [line[:3] for card in result.cards for line in card.text.splitlines() if line[:3].isdigit()],
            [f"{index:03d}" for index in range(1, 9)],
        )
        self.assertEqual([card.metadata["range_start"] for card in result.cards], [1, 3, 5, 7])
        with self.assertRaises(FitError):
            render(data, RenderOptions("ascii", 30, 5, True))

    def test_global_number_width_and_full_metadata_tab_origin(self) -> None:
        data = {
            "title": "Tabs",
            "sentences": [
                {"text": "1234567\t中é", "timestamp": "09:00", "speaker": "王", "tags": ["x"]}
                for _ in range(1001)
            ],
        }
        result = render(data, RenderOptions("unicode-light", 40, 100, False))
        self.assertEqual(result.cards[0].metadata["number_width"], 4)
        self.assertTrue(result.cards[0].text.splitlines()[3].startswith("0001."))
        self.assertTrue(any("1001." in card.text for card in result.cards))
        self.assertNotIn("\t", "".join(card.text for card in result.cards))

    def test_schema_and_indivisible_sentence_failures(self) -> None:
        invalid = fixture()
        invalid["sentences"][0]["unknown"] = True
        with self.assertRaises(InputError):
            render(invalid, RenderOptions())
        data = {"title": "Tall", "sentences": [{"text": "界" * 200}]}
        with self.assertRaises(FitError):
            render(data, RenderOptions("ascii", 20, 6, False))


if __name__ == "__main__":
    unittest.main()
