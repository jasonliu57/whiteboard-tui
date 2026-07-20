from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.kanban_note import render


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "kanban" / "input.json"
GOLDEN = HERE / "golden" / "kanban"


def fixture() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def item(item_id: str, title: str | None = None, **extra: object) -> dict[str, object]:
    value: dict[str, object] = {"id": item_id, "title": title or f"Task {item_id}"}
    value.update(extra)
    return value


def lane(lane_id: str, items: list[dict[str, object]], **extra: object) -> dict[str, object]:
    value: dict[str, object] = {"id": lane_id, "name": f"Lane {lane_id}", "items": items}
    value.update(extra)
    return value


def board(lanes: list[dict[str, object]]) -> dict[str, object]:
    return {"board_id": "test-board", "title": "測試 Board", "lanes": lanes}


class KanbanRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            result = render(fixture(), RenderOptions(theme, 72, 40))
            self.assertEqual(result, render(copy.deepcopy(fixture()), RenderOptions(theme, 72, 40)))
            self.assertEqual(result.cards[0].text + "\n", (GOLDEN / f"{theme}.txt").read_text(encoding="utf-8"))
            self.assertNotIn("\t", result.cards[0].text)
            self.assertIn("API  文件", result.cards[0].text)

    def test_wip_snapshot_order_and_duplicate_tags_are_preserved(self) -> None:
        data = board([lane("doing", [item("a-1", tags=["same", "same"])], wip_limit=0)])
        result = render(data, RenderOptions(max_width=40, max_height=30))
        card = result.cards[0]
        self.assertIn("[count:1/WIP:0]", card.text)
        self.assertIn("!WIP-EXCEEDED", card.text)
        self.assertIn("#same #same", card.text)
        self.assertEqual(card.metadata["wip_exceeded_lane_ids"], ["doing"])

    def test_horizontal_groups_vertical_bands_cover_each_item_once(self) -> None:
        lanes = [lane(f"lane-{lane_index}", [item(f"item-{lane_index}-{item_index}") for item_index in range(5)]) for lane_index in range(5)]
        result = render(board(lanes), RenderOptions(max_width=42, max_height=18))
        self.assertGreater(len({card.metadata["group_index"] for card in result.cards}), 1)
        self.assertGreater(max(card.metadata["band_index"] for card in result.cards), 1)
        self.assertEqual(
            [(card.metadata["group_index"], card.metadata["band_index"]) for card in result.cards],
            sorted((card.metadata["group_index"], card.metadata["band_index"]) for card in result.cards),
        )
        observed = [
            item_id
            for card in result.cards
            for lane_id in card.metadata["lane_ids"]
            for item_id in card.metadata["item_ids_by_lane"][lane_id]
        ]
        expected = [f"item-{lane_index}-{item_index}" for lane_index in range(5) for item_index in range(5)]
        self.assertCountEqual(observed, expected)
        self.assertEqual(len(observed), len(set(observed)))

    def test_empty_done_single_card_and_oversized_boundaries(self) -> None:
        data = board([
            lane("empty", []),
            lane("short", [item("short-1")]),
            lane("long", [item(f"long-{index}") for index in range(6)]),
        ])
        result = render(data, RenderOptions(max_width=64, max_height=18))
        first_group = [card for card in result.cards if card.metadata["group_index"] == 1]
        self.assertTrue(all("[empty]" in card.text for card in first_group))
        self.assertIn("[done]", first_group[-1].text)
        with self.assertRaises(FitError):
            render(data, RenderOptions(max_width=64, max_height=18, single_card=True))
        too_big = board([lane("a", [item("oversized", "中文" * 200)])])
        with self.assertRaises(FitError):
            render(too_big, RenderOptions(max_width=42, max_height=18))
        duplicate = board([lane("a", [item("same")]), lane("b", [item("same")])])
        with self.assertRaises(InputError):
            render(duplicate, RenderOptions())


if __name__ == "__main__":
    unittest.main()
