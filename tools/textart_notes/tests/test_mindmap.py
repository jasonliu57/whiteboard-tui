from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.mindmap_note import render


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "mindmap" / "input.json"
GOLDEN = HERE / "golden" / "mindmap"


def fixture() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def node(key: str, children: list[str] | None = None) -> dict[str, object]:
    return {"id": key, "label": f"Node {key}", "children": children or []}


class MindMapRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_and_visible_ids(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 160, 70)
            result = render(fixture(), options)
            self.assertEqual(result, render(copy.deepcopy(fixture()), options))
            self.assertEqual(len(result.cards), 1)
            self.assertEqual(result.cards[0].text + "\n", (GOLDEN / f"{theme}.txt").read_text(encoding="utf-8"))
            self.assertIn("[mindmap]", result.cards[0].text)
            self.assertNotIn("\t", result.cards[0].text)

    def test_strict_tree_and_optional_detail(self) -> None:
        shared = {"root_id": "root", "nodes": [node("root", ["a", "b"]), node("a", ["leaf"]), node("b", ["leaf"]), node("leaf")]}
        cycle = {"root_id": "root", "nodes": [node("root", ["a"]), node("a", ["root"])]}
        orphan = {"root_id": "root", "nodes": [node("root"), node("loose")]}
        explicit_null = {"root_id": "root", "nodes": [{"id": "root", "label": "Root", "detail": None, "children": []}]}
        whitespace = {"root_id": "root", "nodes": [{"id": "root", "label": " \u0301bad", "children": []}]}
        for value in (shared, cycle, orphan, explicit_null, whitespace):
            with self.subTest(value=value), self.assertRaises(InputError):
                render(value, RenderOptions())

    def test_wide_tree_branch_safe_ownership_and_counterparts(self) -> None:
        branches = [f"b-{index}" for index in range(12)]
        values = [node("root", branches)]
        expected = {"root"}
        for branch in branches:
            leaves = [f"{branch}-x", f"{branch}-y"]
            values.append(node(branch, leaves))
            values.extend(node(leaf) for leaf in leaves)
            expected.update((branch, *leaves))
        result = render({"root_id": "root", "nodes": values}, RenderOptions(max_width=48, max_height=12))
        self.assertGreater(len(result.cards), 1)
        owners = [key for card in result.cards for key in card.metadata["owned_node_ids"]]
        self.assertEqual(set(owners), expected)
        self.assertEqual(len(owners), len(expected))
        card_ids = {card.logical_id for card in result.cards}
        for card in result.cards:
            self.assertTrue(set(card.metadata["child_card_ids"]).issubset(card_ids))
            self.assertTrue(set(card.metadata["counterpart_card_ids"]).issubset(card_ids))
        with self.assertRaises(FitError):
            render({"root_id": "root", "nodes": values}, RenderOptions(max_width=48, max_height=12, single_card=True))

    def test_routes_do_not_enter_nodes_and_themes_keep_geometry(self) -> None:
        results = {theme: render(fixture(), RenderOptions(theme, 160, 70)) for theme in ("ascii", "unicode-light", "unicode-rich")}
        first = results["ascii"].cards[0].metadata
        for theme in ("unicode-light", "unicode-rich"):
            metadata = results[theme].cards[0].metadata
            self.assertEqual(first["node_rects"], metadata["node_rects"])
            self.assertEqual(first["edges"], metadata["edges"])
        rects = first["node_rects"].values()
        for edge in first["edges"]:
            for x, y in edge["cells"]:
                self.assertTrue(all(not (rect["x"] <= x < rect["x"] + rect["width"] and rect["y"] <= y < rect["y"] + rect["height"]) for rect in rects))

    def test_mark_width_root_only_and_deep_chain_ownership(self) -> None:
        root_only = {
            "root_id": "root",
            "nodes": [{"id": "root", "label": "中\u034f\u0903 Root", "children": []}],
        }
        only = render(root_only, RenderOptions(max_width=40, max_height=8)).cards[0]
        self.assertIn("中\u034f\u0903 Root", only.text)
        self.assertEqual(only.metadata["owned_node_ids"], ["root"])

        count = 12
        values = [node(f"n-{index}", [f"n-{index + 1}"] if index + 1 < count else []) for index in range(count)]
        result = render(
            {"root_id": "n-0", "nodes": values},
            RenderOptions(max_width=24, max_height=6),
        )
        owners = [item for card in result.cards for item in card.metadata["owned_node_ids"]]
        self.assertEqual(owners, [f"n-{index}" for index in range(count)])
        card_ids = [card.logical_id for card in result.cards]
        for card in result.cards:
            self.assertEqual(
                card.metadata["counterpart_card_ids"],
                [card_id for card_id in card_ids if card_id != card.logical_id],
            )


if __name__ == "__main__":
    unittest.main()
