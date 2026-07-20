from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.boxed_note import render
from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.models import FitError, InputError, RenderOptions


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "boxed" / "input.json"
GOLDEN = HERE / "golden" / "boxed"


def fixture() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def topic(key: str, body: list[str] | None = None) -> dict[str, object]:
    return {"id": key, "heading": f"Topic {key}", "body": body or ["Body 中文"]}


class BoxedRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 72, 40)
            result = render(fixture(), options)
            self.assertEqual(result, render(copy.deepcopy(fixture()), options))
            self.assertEqual(len(result.cards), 1)
            self.assertEqual(result.cards[0].text + "\n", (GOLDEN / f"{theme}.txt").read_text(encoding="utf-8"))
            self.assertNotIn("\t", result.cards[0].text)

    def test_regions_boxes_extents_and_emphasis_metadata(self) -> None:
        card = render(fixture(), RenderOptions(max_width=72, max_height=40)).cards[0]
        boxes = card.metadata["boxes"]
        regions = card.metadata["regions"]
        self.assertEqual([region["id"] for region in regions], ["discover", "decide"])
        self.assertEqual(next(item for item in boxes if item["id"] == "signals")["emphasis"], "strong")
        self.assertIn("┌!", card.text)
        for index, box in enumerate(boxes):
            self.assertLessEqual(box["x"] + box["width"], card.width)
            self.assertLessEqual(box["y"] + box["height"], card.height)
            for other in boxes[index + 1 :]:
                self.assertTrue(
                    box["x"] + box["width"] <= other["x"]
                    or other["x"] + other["width"] <= box["x"]
                    or box["y"] + box["height"] <= other["y"]
                    or other["y"] + other["height"] <= box["y"]
                )
        for index, region in enumerate(regions):
            for other in regions[index + 1 :]:
                self.assertTrue(region["y"] + region["height"] <= other["y"] or other["y"] + other["height"] <= region["y"])
            members = [box for box in boxes if box["group_id"] == region["id"]]
            foreign = [box for box in boxes if box["group_id"] != region["id"]]
            for box in members:
                self.assertLess(region["x"], box["x"])
                self.assertLess(region["y"], box["y"])
                self.assertLess(box["x"] + box["width"], region["x"] + region["width"])
                self.assertLess(box["y"] + box["height"], region["y"] + region["height"])
            for box in foreign:
                self.assertTrue(
                    region["x"] + region["width"] <= box["x"]
                    or box["x"] + box["width"] <= region["x"]
                    or region["y"] + region["height"] <= box["y"]
                    or box["y"] + box["height"] <= region["y"]
                )

    def test_spacing_mark_wrap_boundary_and_visible_emphasis(self) -> None:
        spacing_mark = "\u0903"
        data = {"id": "doc", "title": "Document", "topics": [topic("a", ["x" * 29 + f"A{spacing_mark}"])]}
        card = render(data, RenderOptions(max_width=40, max_height=50)).cards[0]
        self.assertIn(f"A{spacing_mark}", card.text)
        self.assertFalse(any(line.startswith(spacing_mark) for line in card.text.splitlines()))

        normal = {"id": "doc", "title": "Document", "topics": [topic("a")]}
        strong = copy.deepcopy(normal)
        strong["topics"][0]["emphasis"] = "strong"
        self.assertNotEqual(
            render(normal, RenderOptions(max_width=40)).cards[0].text,
            render(strong, RenderOptions(max_width=40)).cards[0].text,
        )

    def test_ungrouped_and_oversized_group_split_at_topic_boundaries(self) -> None:
        ungrouped = {"id": "doc", "title": "Document", "topics": [topic(f"t-{index}") for index in range(10)]}
        result = render(ungrouped, RenderOptions(max_width=30, max_height=14))
        observed = [item for card in result.cards for item in card.metadata["topic_ids"]]
        self.assertEqual(observed, [f"t-{index}" for index in range(10)])
        with self.assertRaises(FitError):
            render(ungrouped, RenderOptions(max_width=30, max_height=14, single_card=True))

        grouped = {"id": "doc", "title": "Document", "groups": [{"id": "large", "heading": "Large", "topics": [topic(f"g-{index}") for index in range(8)]}]}
        split = render(grouped, RenderOptions(max_width=40, max_height=16))
        self.assertGreater(len(split.cards), 1)
        self.assertEqual([item for card in split.cards for item in card.metadata["topic_ids"]], [f"g-{index}" for index in range(8)])
        self.assertEqual([card.metadata["regions"][0]["segment_index"] for card in split.cards], list(range(1, len(split.cards) + 1)))

    def test_schema_marks_and_indivisible_fit(self) -> None:
        invalid = fixture()
        invalid["title"] = " \u0301bad"
        with self.assertRaises(InputError):
            render(invalid, RenderOptions())
        valid = fixture()
        valid["title"] = "中\u0903 Box"
        self.assertGreaterEqual(text_width(valid["title"]), 4)
        self.assertTrue(render(valid, RenderOptions(max_width=72, max_height=40)).cards)
        unknown = fixture()
        unknown["extra"] = True
        with self.assertRaises(InputError):
            render(unknown, RenderOptions())
        too_tall = {"id": "doc", "title": "Document", "topics": [topic("huge", [f"line {index}" for index in range(30)])]}
        with self.assertRaises(FitError):
            render(too_tall, RenderOptions(max_width=30, max_height=12))


if __name__ == "__main__":
    unittest.main()
