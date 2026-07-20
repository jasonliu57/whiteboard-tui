from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.core.validate import validate_result
from tools.textart_notes.outline_note import MAX_INPUT_DEPTH, render


HERE = Path(__file__).resolve().parent


def fixture() -> dict[str, object]:
    return json.loads((HERE / "fixtures/outline/input.json").read_text(encoding="utf-8"))


class OutlineRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 46, 30, True)
            first = render(fixture(), options)
            self.assertEqual(first, render(fixture(), options))
            validate_result(first, options)
            expected = (HERE / f"golden/outline/{theme}.txt").read_text(encoding="utf-8")
            self.assertEqual(first.cards[0].text + "\n", expected)

    def test_schema_errors_and_empty_children(self) -> None:
        with self.assertRaises(InputError):
            render({"title": "x", "children": []}, RenderOptions())
        invalid = fixture()
        invalid["children"][0]["status"] = "unknown"
        with self.assertRaises(InputError):
            render(invalid, RenderOptions())

    def test_input_depth_guard_is_separate_from_semantic_depth(self) -> None:
        root: dict[str, object] = {"text": "root"}
        current = root
        for index in range(MAX_INPUT_DEPTH + 1):
            child: dict[str, object] = {"text": f"n{index}"}
            current["children"] = [child]
            current = child
        with self.assertRaisesRegex(InputError, "safety depth"):
            render({"title": "deep", "children": [root], "depth_limit": 2}, RenderOptions())

    def test_height_split_preserves_complete_top_level_branches(self) -> None:
        data = fixture()
        data["children"] = [
            {"text": f"Branch {index} 中文", "children": [{"text": "one complete leaf"}]}
            for index in range(8)
        ]
        result = render(data, RenderOptions("unicode-light", 38, 12, False))
        self.assertGreater(len(result.cards), 1)
        with self.assertRaises(FitError):
            render(data, RenderOptions("unicode-light", 38, 12, True))

    def test_depth_split_promotes_subtree_with_context(self) -> None:
        data = fixture()
        data["depth_limit"] = 1
        result = render(data, RenderOptions("unicode-light", 46, 20, False))
        self.assertTrue(any(card.metadata["split_reason"] == "depth" for card in result.cards))
        self.assertTrue(any(card.metadata["section_path"] for card in result.cards))

    def test_indivisible_leaf_fails_without_cropping(self) -> None:
        data = {"title": "x", "children": [{"text": "very long 中文 " * 200}]}
        with self.assertRaisesRegex(FitError, "indivisible leaf"):
            render(data, RenderOptions("ascii", 20, 8, False))


if __name__ == "__main__":
    unittest.main()
