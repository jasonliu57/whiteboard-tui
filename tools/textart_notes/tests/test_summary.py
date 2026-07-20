from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.core.validate import validate_result
from tools.textart_notes.summary_card_note import render


HERE = Path(__file__).resolve().parent


def fixture() -> dict[str, object]:
    return json.loads((HERE / "fixtures/summary/input.json").read_text(encoding="utf-8"))


class SummaryRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 42, 60, True)
            first = render(fixture(), options)
            second = render(fixture(), options)
            self.assertEqual(first, second)
            validate_result(first, options)
            expected = (HERE / f"golden/summary/{theme}.txt").read_text(encoding="utf-8")
            self.assertEqual(first.cards[0].text + "\n", expected)

    def test_complete_records_are_the_only_split_boundary(self) -> None:
        data = fixture()
        data["summaries"] = [data["summaries"][0], copy.deepcopy(data["summaries"][0])]
        result = render(data, RenderOptions("unicode-light", 42, 60, False))
        self.assertEqual(len(result.cards), 2)
        self.assertNotEqual(result.cards[0].logical_id, result.cards[1].logical_id)
        with self.assertRaises(FitError):
            render(data, RenderOptions("unicode-light", 42, 60, True))

    def test_schema_errors_and_empty_collection(self) -> None:
        with self.assertRaises(InputError):
            render({"summaries": []}, RenderOptions())
        invalid = fixture()
        del invalid["summaries"][0]["source"]
        with self.assertRaises(InputError):
            render(invalid, RenderOptions())

    def test_oversized_record_fails_without_cropping(self) -> None:
        data = fixture()
        data["summaries"][0]["conclusion"] = "very long 中文 " * 200
        with self.assertRaisesRegex(FitError, "split the source"):
            render(data, RenderOptions("unicode-light", 30, 12, False))

    def test_minimal_record_and_empty_tags(self) -> None:
        data = fixture()
        data["summaries"][0]["tags"] = []
        result = render(data, RenderOptions("unicode-rich", 36, 60, True))
        self.assertIn("TAGS:", result.cards[0].text)
        self.assertIn("║ -", result.cards[0].text)


if __name__ == "__main__":
    unittest.main()
