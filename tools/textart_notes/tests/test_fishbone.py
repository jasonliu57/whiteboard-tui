from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.fishbone_note import MAX_CAUSES_PER_BRANCH, render


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "fishbone" / "input.json"
GOLDEN = HERE / "golden" / "fishbone"


def fixture() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


class FishboneRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_determinism_and_shape(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 160, 70)
            first = render(fixture(), options)
            self.assertEqual(first, render(copy.deepcopy(fixture()), options))
            self.assertEqual(first.renderer, "fishbone-note")
            self.assertEqual(len(first.cards), 1)
            card = first.cards[0]
            self.assertEqual(
                card.text + "\n",
                (GOLDEN / f"{theme}.txt").read_text(encoding="utf-8"),
            )
            self.assertNotIn("\t", card.text)
            self.assertEqual(
                [item["side"] for item in card.metadata["branch_ownership"]],
                ["top", "top", "bottom", "bottom"],
            )
            self.assertTrue(all(text_width(line) <= card.width for line in card.text.split("\n")))

    def test_layout_variants_are_distinct_and_themes_preserve_geometry(self) -> None:
        base = {
            "effect": "slow release",
            "branches": [
                {"name": "people", "nodes": ["training", "capacity"]},
                {"name": "process", "nodes": ["review", "handoff"]},
            ],
        }
        variant_texts = []
        for variant in ("classic", "boxed", "compact"):
            variant_texts.append(
                render(
                    {**base, "layout": variant},
                    RenderOptions("ascii", 120, 60),
                ).cards[0].text
            )
        self.assertEqual(len(set(variant_texts)), 3)
        self.assertLess(variant_texts[2].count("\n"), variant_texts[0].count("\n"))

        geometry = []
        text = []
        for theme in ("ascii", "unicode-light", "unicode-rich"):
            card = render(base, RenderOptions(theme, 120, 60)).cards[0]
            geometry.append(
                (
                    card.width,
                    card.height,
                    [
                        (item["segment_x"], item["segment_width"], item["joint_x"])
                        for item in card.metadata["branch_ownership"]
                    ],
                )
            )
            text.append(card.text)
        self.assertEqual(geometry[0], geometry[1])
        self.assertEqual(geometry[1], geometry[2])
        self.assertEqual(len(set(text)), 3)

    def test_explicit_auto_sides_and_source_aliases_are_global(self) -> None:
        data = {
            "effect": "E",
            "branches": [
                {"name": "explicit-bottom", "side": "bottom"},
                {"name": "auto-0", "nodes": ["a"]},
                {"name": "auto-1", "side": "auto", "causes": ["b"]},
                {"name": "explicit-top", "side": "top"},
                {"name": "auto-2"},
            ],
        }
        result = render(data, RenderOptions(max_width=160, max_height=60))
        ownership = [
            item for card in result.cards for item in card.metadata["branch_ownership"]
        ]
        self.assertEqual(
            [item["side"] for item in ownership],
            ["bottom", "top", "bottom", "top", "top"],
        )
        self.assertEqual(
            [item["source_field"] for item in ownership],
            ["nodes", "nodes", "causes", "nodes", "nodes"],
        )

    def test_width_split_is_contiguous_repeats_effect_and_single_card_fails(self) -> None:
        data = {
            "effect": "deployment delayed",
            "branches": [
                {"name": f"category-{index}", "nodes": [f"cause-{index}"]}
                for index in range(8)
            ],
        }
        options = RenderOptions("ascii", 58, 35)
        result = render(data, options)
        self.assertGreater(len(result.cards), 1)
        cursor = 0
        for index, card in enumerate(result.cards):
            branch_range = card.metadata["branch_range"]
            self.assertEqual(branch_range["start_index"], cursor)
            cursor = branch_range["end_index_exclusive"]
            self.assertIn("deployment", card.text)
            self.assertIn(f"FISHBONE {index + 1}/{len(result.cards)}", card.text)
            self.assertLessEqual(card.width, options.max_width)
            self.assertEqual(card.x, sum(item.width + 4 for item in result.cards[:index]))
        self.assertEqual(cursor, 8)
        with self.assertRaises(FitError):
            render(data, RenderOptions("ascii", 58, 35, True))

    def test_height_split_preserves_complete_branch_ownership_and_auto_side(self) -> None:
        data = {
            "effect": "E",
            "branches": [
                {"name": "auto-top", "nodes": ["cause-a"]},
                {"name": "auto-bottom", "nodes": ["cause-b"]},
            ],
        }
        self.assertEqual(
            len(render(data, RenderOptions("ascii", 160, 100)).cards), 1
        )
        constrained = render(data, RenderOptions("ascii", 160, 9))
        self.assertEqual(len(constrained.cards), 2)
        self.assertEqual(
            [card.metadata["branch_range"] for card in constrained.cards],
            [
                {"start_index": 0, "end_index_exclusive": 1, "total": 2},
                {"start_index": 1, "end_index_exclusive": 2, "total": 2},
            ],
        )
        self.assertEqual(
            [card.metadata["branch_ownership"][0]["side"] for card in constrained.cards],
            ["top", "bottom"],
        )

    def test_indivisible_width_height_and_cause_limit_fail_cleanly(self) -> None:
        too_wide = {
            "effect": "E",
            "branches": [{"name": "deep", "nodes": [f"n{x}" for x in range(30)]}],
        }
        with self.assertRaisesRegex(FitError, "too wide"):
            render(too_wide, RenderOptions("ascii", 60, 100))
        too_high = {
            "effect": "E",
            "branches": [{"name": "deep", "nodes": [f"cause {x}" for x in range(8)]}],
        }
        with self.assertRaisesRegex(FitError, "too high"):
            render(too_high, RenderOptions("ascii", 120, 12))
        with self.assertRaises(InputError):
            render(
                {
                    "effect": "E",
                    "branches": [
                        {"name": "many", "nodes": ["x"] * (MAX_CAUSES_PER_BRANCH + 1)}
                    ],
                },
                RenderOptions(),
            )

    def test_closed_schema_combining_spacing_mark_tabs_and_multiline(self) -> None:
        for invalid in (
            {"effect": "E", "branches": [{"name": "B"}], "extra": True},
            {"effect": "E", "branches": [{"name": "B", "extra": True}]},
            {
                "effect": "E",
                "branches": [{"name": "B", "nodes": [], "causes": []}],
            },
            {"effect": "́orphan", "branches": [{"name": "B"}]},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(InputError):
                render(invalid, RenderOptions())

        data = {
            "effect": "中Ａ",
            "layout": "boxed",
            "branches": [
                {"name": "Aः中", "nodes": ["é", "A⃝", "欄\tA", "line\n第二行"]}
            ],
        }
        card = render(data, RenderOptions("unicode-rich", 80, 50)).cards[0]
        self.assertEqual(text_width("Aः中"), 4)
        self.assertEqual(text_width("中Ａ"), 4)
        self.assertEqual(text_width("é"), 1)
        self.assertEqual(text_width("A⃝"), 1)
        self.assertIn("Aः中", card.text)
        self.assertNotIn("\t", card.text)
        self.assertTrue(all(text_width(line) <= card.width for line in card.text.split("\n")))


if __name__ == "__main__":
    unittest.main()
