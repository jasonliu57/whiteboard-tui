from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.atomic_card_note import render
from tools.textart_notes.core.models import FitError, InputError, RenderOptions


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "atomic_card" / "input.json"
GOLDEN = HERE / "golden" / "atomic_card"


def fixture() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def concept(concept_id: str, body: str = "body", references: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "id": concept_id,
        "title": f"Title {concept_id}",
        "body": body,
        "tags": [],
        "references": references or [],
    }


class AtomicCardRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            first = render(fixture(), RenderOptions(theme, 56, 40))
            second = render(copy.deepcopy(fixture()), RenderOptions(theme, 56, 40))
            self.assertEqual(first, second)
            self.assertEqual(first.cards[0].text + "\n", (GOLDEN / f"{theme}.txt").read_text(encoding="utf-8"))
            self.assertEqual(len(first.cards), len(fixture()["concepts"]))

    def test_references_are_visible_ordered_metadata_without_edges(self) -> None:
        result = render(fixture(), RenderOptions(max_width=56, max_height=40))
        first = result.cards[0]
        self.assertIn("[I:ok] amortized-analysis", first.text)
        self.assertIn("[I:?] missing-ring-buffer", first.text)
        self.assertIn("[E] clrs-4e", first.text)
        self.assertEqual(
            [(item["kind"], item["id"], item["resolved"]) for item in first.metadata["references"]],
            [
                ("internal", "amortized-analysis", True),
                ("internal", "missing-ring-buffer", False),
                ("external", "clrs-4e", False),
            ],
        )
        self.assertFalse(first.metadata["creates_board_edges"])

    def test_self_cycle_and_row_major_variable_geometry_remain_atomic(self) -> None:
        values = [
            concept("c-0", "word " * 10, [{"id": "c-0", "kind": "internal"}]),
            concept("c-1", "word " * 80, [{"id": "c-2", "kind": "internal"}]),
            concept("c-2", "word " * 20, [{"id": "c-1", "kind": "internal"}]),
            concept("c-3", "word " * 5, [{"id": "outside", "kind": "internal"}]),
        ]
        result = render(
            {"collection_title": "Collection", "concepts": values},
            RenderOptions(max_width=80, max_height=18),
        )
        self.assertEqual([(card.width, card.x, card.y) for card in result.cards], [(56, 0, 0), (80, 60, 0), (56, 144, 0), (56, 0, 20)])
        self.assertEqual([card.logical_id for card in result.cards], [f"c-{index}" for index in range(4)])
        self.assertTrue(result.cards[0].metadata["references"][0]["resolved"])

    def test_single_card_schema_and_indivisible_failure(self) -> None:
        values = fixture()
        with self.assertRaises(FitError):
            render(values, RenderOptions(single_card=True))
        one = copy.deepcopy(values)
        one["concepts"] = [one["concepts"][1]]
        self.assertEqual(len(render(one, RenderOptions(single_card=True)).cards), 1)
        one["concepts"][0]["body"] = "不可切割 indivisible " * 500
        with self.assertRaises(FitError):
            render(one, RenderOptions(max_width=160, max_height=20))
        duplicate = fixture()
        duplicate["concepts"][1]["id"] = duplicate["concepts"][0]["id"]
        with self.assertRaises(InputError):
            render(duplicate, RenderOptions())


if __name__ == "__main__":
    unittest.main()
