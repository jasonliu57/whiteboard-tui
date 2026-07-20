from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.sketchnote import ICON_PATTERNS, render


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "sketchnote" / "input.json"
GOLDEN = HERE / "golden" / "sketchnote"


def fixture() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def block(
    identifier: str,
    *,
    body: str = "body 中文",
    icon: str = "note",
    importance: str = "normal",
) -> dict[str, object]:
    return {
        "id": identifier,
        "keyword": f"Keyword {identifier}",
        "body": body,
        "icon": icon,
        "importance": importance,
    }


def document(
    blocks: list[dict[str, object]],
    *,
    relations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": "doc",
        "title": "Sketch 測試",
        "groups": [
            {"id": "group", "title": "Group 群", "blocks": blocks}
        ],
        "relations": relations or [],
    }


def rect_cells(rect: dict[str, int]) -> set[tuple[int, int]]:
    return {
        (x, y)
        for y in range(rect["y"], rect["y"] + rect["height"])
        for x in range(rect["x"], rect["x"] + rect["width"])
    }


class SketchnoteRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 120, 70)
            result = render(fixture(), options)
            self.assertEqual(result, render(copy.deepcopy(fixture()), options))
            self.assertEqual(len(result.cards), 1)
            self.assertEqual(
                result.cards[0].text + "\n",
                (GOLDEN / f"{theme}.txt").read_text(encoding="utf-8"),
            )
            self.assertNotIn("\t", result.cards[0].text)

    def test_icons_are_fixed_five_by_three_and_importance_is_visible(self) -> None:
        self.assertEqual(
            set(ICON_PATTERNS),
            {"idea", "person", "action", "warning", "question", "note"},
        )
        for rows in ICON_PATTERNS.values():
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(text_width(row) == 5 for row in rows))
        text = render(fixture(), RenderOptions()).cards[0].text
        self.assertIn("│* .-. ", text)
        self.assertIn("│!-->  ", text)

    def test_routes_are_ordered_disjoint_auditable_and_inside_group(self) -> None:
        value = document(
            [block("one"), block("two"), block("three")],
            relations=[
                {"id": "first", "source": "one", "target": "two", "label": "一"},
                {"id": "second", "source": "two", "target": "three", "label": "two\t二"},
            ],
        )
        card = render(value, RenderOptions(max_width=70)).cards[0]
        routes = card.metadata["routes"]
        self.assertEqual([(item["id"], item["order"]) for item in routes], [("first", 0), ("second", 1)])
        blocks = card.metadata["groups"][0]["blocks"]
        by_id = {item["id"]: rect_cells(item["rect"]) for item in blocks}
        occupied: set[tuple[int, int]] = set()
        labels: set[tuple[int, int]] = set()
        for route in routes:
            path = [tuple(point) for point in route["path"]]
            cells = set(path)
            label_cells = rect_cells(route["label_rect"])
            self.assertEqual(len(path), len(cells))
            self.assertTrue(
                all(
                    abs(first[0] - second[0]) + abs(first[1] - second[1]) == 1
                    for first, second in zip(path, path[1:])
                )
            )
            self.assertTrue(cells.isdisjoint(occupied))
            self.assertTrue(label_cells.isdisjoint(cells | labels))
            self.assertTrue((cells & by_id[route["source"]]) <= {path[0]})
            self.assertTrue((cells & by_id[route["target"]]) <= {path[-1]})
            for identifier, block_cells in by_id.items():
                if identifier not in {route["source"], route["target"]}:
                    self.assertTrue(cells.isdisjoint(block_cells))
            occupied.update(cells)
            labels.update(label_cells)

    def test_split_preserves_global_block_and_relation_order(self) -> None:
        value = document(
            [block(f"item-{index}") for index in range(8)],
            relations=[
                {"id": "first", "source": "item-0", "target": "item-7"},
                {"id": "second", "source": "item-1", "target": "item-6"},
            ],
        )
        cards = render(value, RenderOptions(max_width=45, max_height=28)).cards
        self.assertGreater(len(cards), 1)
        blocks = [
            (item["id"], item["order"])
            for card in cards
            for item in card.metadata["groups"][0]["blocks"]
        ]
        self.assertEqual(blocks, [(f"item-{index}", index) for index in range(8)])
        endpoints = [card.metadata["continuations"] for card in cards if card.metadata["continuations"]]
        self.assertEqual(len(endpoints), 2)
        for entries in endpoints:
            self.assertEqual(
                [(item["id"], item["order"]) for item in entries],
                [("first", 0), ("second", 1)],
            )
        self.assertEqual(
            {item["role"] for entries in endpoints for item in entries},
            {"source", "target"},
        )

    def test_routes_keep_global_author_order_across_groups(self) -> None:
        value = {
            "id": "doc",
            "title": "Two groups",
            "groups": [
                {
                    "id": "first-group",
                    "title": "First",
                    "blocks": [block("first-a"), block("first-b")],
                },
                {
                    "id": "second-group",
                    "title": "Second",
                    "blocks": [block("second-a"), block("second-b")],
                },
            ],
            "relations": [
                {
                    "id": "second-first",
                    "source": "second-a",
                    "target": "second-b",
                },
                {
                    "id": "first-second",
                    "source": "first-a",
                    "target": "first-b",
                },
            ],
        }
        card = render(value, RenderOptions(max_width=120, max_height=70)).cards[0]
        self.assertEqual(
            [(item["id"], item["order"]) for item in card.metadata["routes"]],
            [("second-first", 0), ("first-second", 1)],
        )

    def test_themes_change_glyphs_not_geometry_ids_or_metadata(self) -> None:
        results = {
            theme: render(fixture(), RenderOptions(theme, 120, 70))
            for theme in ("ascii", "unicode-light", "unicode-rich")
        }
        baseline = results["ascii"]
        for result in results.values():
            self.assertEqual(
                [
                    (card.logical_id, card.width, card.height, card.x, card.y, card.metadata)
                    for card in result.cards
                ],
                [
                    (card.logical_id, card.width, card.height, card.x, card.y, card.metadata)
                    for card in baseline.cards
                ],
            )
        self.assertNotEqual(baseline.cards[0].text, results["unicode-light"].cards[0].text)

    def test_null_label_stable_ids_and_wrong_typed_enums(self) -> None:
        value = document(
            [block("one"), block("two")],
            relations=[{"id": "link", "source": "one", "target": "two", "label": None}],
        )
        self.assertIsNone(render(value, RenderOptions()).cards[0].metadata["routes"][0]["label"])
        bad_ids = []
        for identifier in ("1doc", "-doc", "Doc"):
            changed = copy.deepcopy(value)
            changed["id"] = identifier
            bad_ids.append(changed)
        bad_icon = copy.deepcopy(value)
        bad_icon["groups"][0]["blocks"][0]["icon"] = []
        bad_importance = copy.deepcopy(value)
        bad_importance["groups"][0]["blocks"][0]["importance"] = {}
        for changed in (*bad_ids, bad_icon, bad_importance):
            with self.subTest(value=changed), self.assertRaises(InputError):
                render(changed, RenderOptions())

    def test_schema_density_cross_group_and_fit_failures_are_explicit(self) -> None:
        unknown = fixture()
        unknown["extra"] = True
        bad_mark = fixture()
        bad_mark["title"] = " \u0301bad"
        density = document(
            [block(f"b-{index}") for index in range(4)],
            relations=[
                {"id": "r-one", "source": "b-0", "target": "b-1"},
                {"id": "r-two", "source": "b-1", "target": "b-2"},
                {"id": "r-three", "source": "b-2", "target": "b-3"},
            ],
        )
        for changed in (unknown, bad_mark, density):
            with self.subTest(value=changed), self.assertRaises(InputError):
                render(changed, RenderOptions())

        cross = {
            "id": "doc",
            "title": "Cross",
            "groups": [
                {"id": "left", "title": "Left", "blocks": [block("one")]},
                {"id": "right", "title": "Right", "blocks": [block("two")]},
            ],
            "relations": [{"id": "link", "source": "one", "target": "two"}],
        }
        with self.assertRaisesRegex(FitError, "cross-group"):
            render(cross, RenderOptions())
        with self.assertRaises(FitError):
            render(fixture(), RenderOptions(max_width=21))
        with self.assertRaises(FitError):
            render(fixture(), RenderOptions(max_width=1))
        with self.assertRaises(FitError):
            render(
                document([block(f"item-{index}") for index in range(8)]),
                RenderOptions(max_width=45, max_height=28, single_card=True),
            )


if __name__ == "__main__":
    unittest.main()
