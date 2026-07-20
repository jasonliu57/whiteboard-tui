from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.core.validate import validate_result
from tools.textart_notes.template_note import render


HERE = Path(__file__).resolve().parent


def fixture() -> dict[str, object]:
    return json.loads((HERE / "fixtures/template/input.json").read_text(encoding="utf-8"))


class TemplateRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 48, 40, True)
            first = render(fixture(), options)
            self.assertEqual(first, render(fixture(), options))
            validate_result(first, options)
            expected = (HERE / f"golden/template/{theme}.txt").read_text(encoding="utf-8")
            self.assertEqual(first.cards[0].text + "\n", expected)

    def test_blank_required_values_remain_valid_and_visible(self) -> None:
        data = fixture()
        data["values"]["fields"] = {}
        data["values"]["repeatable_sections"] = {"actions": []}
        result = render(data, RenderOptions("unicode-light", 48, 40, True))
        self.assertGreater(result.cards[0].metadata["incomplete_required"], 0)
        self.assertIn("<enter topic>", result.cards[0].text)

    def test_schema_error_and_empty_template(self) -> None:
        invalid = fixture()
        invalid["schema"]["fields"][1]["id"] = "topic"
        with self.assertRaises(InputError):
            render(invalid, RenderOptions())
        empty = fixture()
        empty["schema"]["fields"] = []
        empty["schema"]["repeatable_sections"] = []
        with self.assertRaises(InputError):
            render(empty, RenderOptions())

    def test_pagination_uses_complete_units_and_single_card_fails(self) -> None:
        data = fixture()
        base = copy.deepcopy(data["schema"]["fields"][0])
        data["schema"]["fields"] = []
        data["schema"]["repeatable_sections"] = []
        data["values"]["fields"] = {}
        data["values"]["repeatable_sections"] = {}
        for index in range(10):
            field = copy.deepcopy(base)
            field["id"] = f"field-{index}"
            field["label"] = f"Field {index} / 欄位"
            data["schema"]["fields"].append(field)
        result = render(data, RenderOptions("unicode-light", 40, 12, False))
        self.assertGreater(len(result.cards), 1)
        self.assertEqual(sum(len(card.metadata["unit_keys"]) for card in result.cards), 10)
        with self.assertRaises(FitError):
            render(data, RenderOptions("unicode-light", 40, 12, True))

    def test_page_numbering_is_not_limited_to_three_digits(self) -> None:
        data = fixture()
        base = copy.deepcopy(data["schema"]["fields"][0])
        data["schema"]["fields"] = []
        data["schema"]["repeatable_sections"] = []
        data["values"]["fields"] = {}
        data["values"]["repeatable_sections"] = {}
        for index in range(1001):
            field = copy.deepcopy(base)
            field["id"] = f"f-{index}"
            field["label"] = "F"
            data["schema"]["fields"].append(field)
        result = render(data, RenderOptions("ascii", 40, 10, False))
        self.assertGreaterEqual(len(result.cards), 1000)
        self.assertTrue(any(card.logical_id.endswith("-1000") for card in result.cards))

    def test_indivisible_record_fails_without_cropping(self) -> None:
        data = fixture()
        data["values"]["repeatable_sections"]["actions"][0]["next"] = "中文 long " * 100
        with self.assertRaises(FitError):
            render(data, RenderOptions("unicode-light", 32, 20, False))


if __name__ == "__main__":
    unittest.main()
