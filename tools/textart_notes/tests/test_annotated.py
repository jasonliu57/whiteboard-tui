from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.textart_notes.annotated_note import render
from tools.textart_notes.core.models import FitError, InputError, RenderOptions


HERE = Path(__file__).parent
FIXTURE = HERE / "fixtures" / "annotated" / "input.json"
GOLDEN = HERE / "golden" / "annotated"


def fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class AnnotatedTests(unittest.TestCase):
    def test_two_theme_goldens_and_determinism(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 78, 42, False)
            result = render(fixture(), options)
            self.assertEqual(result, render(fixture(), options))
            self.assertEqual(result.cards[0].text + "\n", (GOLDEN / f"{theme}.txt").read_text(encoding="utf-8"))

    def test_original_numbers_overlap_and_input_order(self) -> None:
        data = {"title": "Anchors", "source": {"id": "source", "label": "s.txt", "first_line": 999, "lines": ["a", "", "c", "d"]}, "annotations": [
            {"id": "later", "start_line": 1001, "end_line": 1002, "kind": "question", "body": "later"},
            {"id": "outer", "start_line": 999, "end_line": 1002, "kind": "important", "body": "outer"},
            {"id": "nested", "start_line": 1000, "end_line": 1000, "kind": "comment", "body": "nested"},
        ]}
        card = render(data, RenderOptions("ascii", 64, 60, False)).cards[0]
        self.assertEqual(card.metadata["annotation_ids"], ["later", "outer", "nested"])
        self.assertIn(" 999 a", card.text)
        self.assertIn("1000 ", card.text)

    def test_pagination_preserves_order_context_and_single_card(self) -> None:
        data = {"title": "Pages", "source": {"id": "source", "label": "s.txt", "first_line": 700, "lines": [f"line {index}" for index in range(5)]}, "annotations": [
            {"id": f"a-{index}", "start_line": 700 + index, "end_line": 700 + index, "kind": "comment", "body": "body"}
            for index in range(5)
        ]}
        result = render(data, RenderOptions("ascii", 48, 12, False))
        self.assertGreater(len(result.cards), 1)
        self.assertEqual([item for card in result.cards for item in card.metadata["annotation_ids"]], [f"a-{index}" for index in range(5)])
        self.assertTrue(all("original lines" in card.text and "700-704" in card.text for card in result.cards))
        with self.assertRaises(FitError):
            render(data, RenderOptions("ascii", 48, 12, True))

    def test_invalid_and_oversized_ranges_fail_without_crop(self) -> None:
        data = fixture()
        data["annotations"][0]["start_line"] = 140  # type: ignore[index]
        data["annotations"][0]["end_line"] = 139  # type: ignore[index]
        with self.assertRaises(InputError):
            render(data, RenderOptions())
        oversized = fixture()
        oversized["annotations"][0]["body"] = "long " * 200  # type: ignore[index]
        with self.assertRaises(FitError):
            render(oversized, RenderOptions("ascii", 48, 12, False))

    def test_exact_height_and_physical_tabs(self) -> None:
        data = {"title": "Tab", "source": {"id": "source", "label": "s", "first_line": 37, "lines": ["\tX é"]}, "annotations": [{"id": "tab", "start_line": 37, "end_line": 37, "kind": "important", "body": "A\tB"}]}
        first = render(data, RenderOptions("unicode-light", 60, 100, False)).cards[0]
        exact = render(data, RenderOptions("unicode-light", 60, first.height, False)).cards[0]
        self.assertEqual(first.text, exact.text)
        with self.assertRaises(FitError):
            render(data, RenderOptions("unicode-light", 60, first.height - 1, False))
        self.assertNotIn("\t", first.text)
        self.assertIn("37", first.text)

    def test_slug_and_unknown_key_are_rejected(self) -> None:
        data = fixture()
        data["annotations"][0]["id"] = "Bad_ID"  # type: ignore[index]
        with self.assertRaises(InputError):
            render(data, RenderOptions())
        unknown = fixture()
        unknown["source"]["uri"] = "x"  # type: ignore[index]
        with self.assertRaises(InputError):
            render(unknown, RenderOptions())


if __name__ == "__main__":
    unittest.main()
