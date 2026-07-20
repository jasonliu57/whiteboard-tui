from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.concept_map_note import render
from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.models import FitError, InputError, RenderOptions


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "concept_map" / "input.json"
GOLDEN = HERE / "golden" / "concept_map"


def fixture() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def concept(key: str) -> dict[str, str]:
    return {"id": key, "label": f"Label {key}", "detail": f"Detail {key}"}


def edge(key: str, source: str, target: str, relation: str = "relates") -> dict[str, str]:
    return {"id": key, "from": source, "to": target, "relation": relation}


def graph(concepts: list[dict[str, str]], edges: list[dict[str, str]]) -> dict[str, object]:
    return {"id": "map", "title": "概念 Map", "concepts": concepts, "edges": edges}


class ConceptMapRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 120, 70)
            result = render(fixture(), options)
            self.assertEqual(result, render(copy.deepcopy(fixture()), options))
            self.assertEqual(
                result.cards[0].text + "\n",
                (GOLDEN / f"{theme}.txt").read_text(encoding="utf-8"),
            )
            self.assertNotIn("\t", result.cards[0].text)

    def test_cycles_scc_forward_edges_self_loop_and_parallel_relations(self) -> None:
        value = graph(
            [concept("a"), concept("b"), concept("c"), concept("d")],
            [
                edge("ab", "a", "b"),
                edge("bc", "b", "c"),
                edge("ca", "c", "a"),
                edge("ad", "a", "d"),
                edge("ad-two", "a", "d", "questions"),
                edge("loop", "d", "d", "reflects"),
            ],
        )
        metadata = render(value, RenderOptions(max_width=160, max_height=100)).cards[0].metadata
        by_node = {node["id"]: node["scc_id"] for node in metadata["nodes"]}
        self.assertEqual(len({by_node[key] for key in ("a", "b", "c")}), 1)
        self.assertNotEqual(by_node["a"], by_node["d"])
        by_edge = {item["id"]: item for item in metadata["edges"]}
        self.assertEqual(by_edge["ad"]["kind"], "forward")
        self.assertEqual(by_edge["ad-two"]["kind"], "forward")
        for key in ("ab", "bc", "ca", "loop"):
            self.assertEqual(by_edge[key]["kind"], "cycle")
            self.assertGreater(by_edge[key]["lane_x"], by_edge["ad"]["lane_x"])

    def test_routes_labels_nodes_and_physical_spans_are_auditable(self) -> None:
        card = render(fixture(), RenderOptions()).cards[0]
        node_cells = {
            (x, y)
            for node in card.metadata["nodes"]
            for y in range(node["rect"]["y"], node["rect"]["y"] + node["rect"]["height"])
            for x in range(node["rect"]["x"], node["rect"]["x"] + node["rect"]["width"])
        }
        all_labels: set[tuple[int, int]] = set()
        for item in card.metadata["edges"]:
            label = item["label"]
            rect = label["rect"]
            cells = {(x, rect["y"]) for x in range(rect["x"], rect["x"] + rect["width"])}
            all_labels.update(cells)
            self.assertEqual(text_width(label["text"], start=rect["x"]), label["physical_span"])
        for item in card.metadata["edges"]:
            route = {tuple(point) for point in item["painted_route_cells"]}
            self.assertTrue(route.isdisjoint(all_labels))
            allowed = {tuple(item["source_port"]), tuple(item["target_port"])}
            self.assertTrue((route & node_cells) <= allowed)

    def test_complete_weak_components_are_the_only_split_boundary(self) -> None:
        value = graph(
            [concept("z"), concept("a"), concept("y"), concept("b")],
            [edge("zy", "z", "y"), edge("ab", "a", "b")],
        )
        result = render(value, RenderOptions())
        self.assertEqual(
            [card.logical_id for card in result.cards],
            ["concept-map-map-z", "concept-map-map-a"],
        )
        self.assertEqual(result.cards[0].metadata["source_node_order"], ["z", "y"])
        self.assertEqual(result.cards[1].metadata["source_node_order"], ["a", "b"])
        with self.assertRaises(FitError):
            render(value, RenderOptions(single_card=True))
        connected = graph([concept("a"), concept("b")], [edge("ab", "a", "b")])
        natural = render(connected, RenderOptions()).cards[0]
        with self.assertRaises(FitError):
            render(connected, RenderOptions(max_width=natural.width - 1))

    def test_schema_duplicate_relation_marks_and_controls(self) -> None:
        duplicate = graph(
            [concept("a"), concept("b")],
            [edge("one", "a", "b", "same"), edge("two", "a", "b", "same")],
        )
        dangling = graph([concept("a")], [edge("bad", "a", "missing")])
        unknown = graph([concept("a")], [])
        unknown["extra"] = True
        bad_mark = graph([concept("a")], [])
        bad_mark["title"] = " \u0301bad"
        bad_control = graph([concept("a")], [])
        bad_control["concepts"][0]["label"] = "bad\nline"
        for value in (duplicate, dangling, unknown, bad_mark, bad_control):
            with self.subTest(value=value), self.assertRaises(InputError):
                render(value, RenderOptions())

    def test_themes_preserve_geometry_metadata_and_deep_chain_does_not_recurse(self) -> None:
        results = {
            theme: render(fixture(), RenderOptions(theme, 120, 70)).cards[0]
            for theme in ("ascii", "unicode-light", "unicode-rich")
        }
        for theme in ("unicode-light", "unicode-rich"):
            self.assertEqual(results[theme].metadata, results["ascii"].metadata)
            self.assertEqual(
                (results[theme].width, results[theme].height),
                (results["ascii"].width, results["ascii"].height),
            )
        count = 1100
        value = graph(
            [concept(f"n-{index}") for index in range(count)],
            [edge(f"e-{index}", f"n-{index}", f"n-{index + 1}") for index in range(count - 1)],
        )
        with self.assertRaises(FitError):
            render(value, RenderOptions())


if __name__ == "__main__":
    unittest.main()
