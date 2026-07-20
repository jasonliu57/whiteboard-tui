from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.core.validate import validate_result
from tools.textart_notes.qa_note import render


HERE = Path(__file__).resolve().parent


def fixture() -> dict[str, object]:
    return json.loads((HERE / "fixtures/qa/input.json").read_text(encoding="utf-8"))


class QaRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_expanded_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 72, 60, True)
            result = render(fixture(), options)
            self.assertEqual(result, render(fixture(), options))
            validate_result(result, options)
            expected = (HERE / f"golden/qa/{theme}.txt").read_text(encoding="utf-8")
            self.assertEqual(result.cards[0].text + "\n", expected)
            self.assertFalse(result.cards[0].metadata["interactive_reveal"])

    def test_expanded_splits_only_between_whole_items(self) -> None:
        data = fixture()
        template = data["items"][0]
        data["items"] = []
        for index in range(8):
            item = copy.deepcopy(template)
            item["pair_id"] = f"pair-{index}"
            item["question"] = f"Question {index} 中文"
            item["answer"] = f"Answer {index} with words"
            data["items"].append(item)
        result = render(data, RenderOptions("unicode-light", 48, 18, False))
        self.assertGreater(len(result.cards), 1)
        self.assertEqual([pair for card in result.cards for pair in card.metadata["pair_ids"]], [f"pair-{index}" for index in range(8)])
        with self.assertRaises(FitError):
            render(data, RenderOptions("unicode-light", 48, 18, True))

    def test_separate_mode_has_reciprocal_multpart_metadata_and_order(self) -> None:
        data = {
            "title": "Long pair",
            "mode": "separate",
            "items": [
                {
                    "pair_id": "long-pair",
                    "question": "Q0\nQ1\nQ2\nQ3\nQ4",
                    "answer": "A0\nA1\nA2\nA3\nA4\nA5",
                    "hint": "H0\nH1",
                    "tags": [],
                    "difficulty": "hard"
                }
            ]
        }
        result = render(data, RenderOptions("ascii", 32, 15, False))
        ids = {card.logical_id for card in result.cards}
        self.assertEqual([card.metadata["card_order"] for card in result.cards], list(range(len(result.cards))))
        self.assertEqual([card.metadata["side"] for card in result.cards], sorted([card.metadata["side"] for card in result.cards], reverse=True))
        for card in result.cards:
            self.assertTrue(set(card.metadata["counterpart_ids"]) <= ids)
            self.assertTrue(all(card.logical_id in next(other for other in result.cards if other.logical_id == counterpart).metadata["counterpart_ids"] for counterpart in card.metadata["counterpart_ids"]))
        self.assertEqual(result.cards[0].x, 0)
        first_answer = next(card for card in result.cards if card.metadata["side"] == "answer")
        self.assertEqual(first_answer.x, 36)
        with self.assertRaises(FitError):
            render(data, RenderOptions("ascii", 32, 15, True))

    def test_actual_prefix_tabs_schema_and_oversize(self) -> None:
        data = fixture()
        data["items"] = [copy.deepcopy(data["items"][0])]
        data["items"][0]["question"] = "12345678901234567890\tX"
        data["items"][0]["answer"] = "é 與 中文"
        card = render(data, RenderOptions("ascii", 32, 30, True)).cards[0]
        self.assertNotIn("\t", card.text)
        invalid = fixture()
        invalid["items"][0]["pair_id"] = "中文 id"
        with self.assertRaises(InputError):
            render(invalid, RenderOptions())
        huge = fixture()
        huge["items"] = [copy.deepcopy(huge["items"][0])]
        huge["items"][0]["answer"] = "answer 中文 " * 300
        with self.assertRaises(FitError):
            render(huge, RenderOptions("ascii", 32, 15, False))


if __name__ == "__main__":
    unittest.main()
