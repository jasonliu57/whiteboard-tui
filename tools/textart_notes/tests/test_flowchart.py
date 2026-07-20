from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.textart_notes.core.models import FitError, InputError, RenderOptions
from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.flowchart_note import render


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "flowchart" / "input.json"
GOLDEN = HERE / "golden" / "flowchart"


def fixture() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def minimal() -> dict[str, object]:
    return {
        "schema_version": 1,
        "id": "minimal",
        "title": "Minimal",
        "nodes": [
            {"id": "start", "kind": "start", "label": "Start", "details": []},
            {"id": "end", "kind": "end", "label": "End", "details": []},
        ],
        "edges": [{"id": "go", "from": "start", "to": "end", "source_port": "south", "target_port": "north", "label": None}],
    }


class FlowchartRendererTests(unittest.TestCase):
    def test_ascii_and_unicode_goldens_are_deterministic(self) -> None:
        for theme in ("ascii", "unicode-light"):
            options = RenderOptions(theme, 120, 70)
            result = render(fixture(), options)
            self.assertEqual(result, render(copy.deepcopy(fixture()), options))
            self.assertEqual(result.cards[0].text + "\n", (GOLDEN / f"{theme}.txt").read_text(encoding="utf-8"))
            self.assertNotIn("\t", result.cards[0].text)

    def test_minimal_typed_nodes_and_strict_fit(self) -> None:
        card = render(minimal(), RenderOptions(theme="ascii")).cards[0]
        self.assertIn("(START)", card.text)
        self.assertIn("(END)", card.text)
        self.assertEqual(card.metadata["layers"], [["start"], ["end"]])
        with self.assertRaises(FitError):
            render(fixture(), RenderOptions(max_width=120, max_height=20))
        with self.assertRaises(FitError):
            render(fixture(), RenderOptions(max_width=120, max_height=20, single_card=True))

    def test_route_invariants_and_decision_merge_order(self) -> None:
        card = render(fixture(), RenderOptions(max_width=120, max_height=70)).cards[0]
        metadata = card.metadata
        self.assertEqual(metadata["layers"][3], ["repair", "run"])
        rect_cells = {
            (x, y)
            for rect in metadata["node_rects"].values()
            for y in range(rect["y"], rect["y"] + rect["height"])
            for x in range(rect["x"], rect["x"] + rect["width"])
        }
        occupied: set[tuple[int, int]] = set()
        for route in metadata["routes"]:
            cells = [tuple(item) for item in route["cells"]]
            self.assertEqual(cells[0], tuple(route["source_external"]))
            self.assertEqual(cells[-1], tuple(route["target_external"]))
            self.assertEqual(len(cells), len(set(cells)))
            self.assertTrue(all(abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1 for a, b in zip(cells, cells[1:])))
            self.assertFalse(set(cells) & rect_cells)
            self.assertFalse(set(cells) & occupied)
            occupied.update(cells)

    def test_invalid_cycle_unreachable_ports_schema_and_marks(self) -> None:
        cycle = fixture()
        cycle["edges"][-1]["to"] = "read"
        cycle["edges"][-1]["target_port"] = "north-east"
        unreachable = minimal()
        unreachable["nodes"].append({"id": "orphan", "kind": "process", "label": "Orphan", "details": []})
        bad_port = fixture()
        bad_port["edges"][2]["source_port"] = "south"
        bad_schema = fixture()
        bad_schema["unknown"] = True
        bad_mark = fixture()
        bad_mark["title"] = " \u0301bad"
        for value in (cycle, unreachable, bad_port, bad_schema, bad_mark):
            with self.subTest(value=value), self.assertRaises(InputError):
                render(value, RenderOptions())

    def test_themes_keep_route_and_rectangle_geometry(self) -> None:
        results = {theme: render(fixture(), RenderOptions(theme, 120, 70)).cards[0] for theme in ("ascii", "unicode-light", "unicode-rich")}
        for theme in ("unicode-light", "unicode-rich"):
            self.assertEqual(results["ascii"].metadata["node_rects"], results[theme].metadata["node_rects"])
            self.assertEqual(results["ascii"].metadata["routes"], results[theme].metadata["routes"])
            self.assertEqual(results["ascii"].metadata["labels"], results[theme].metadata["labels"])
        self.assertNotEqual(results["ascii"].text, results["unicode-light"].text)

    def test_tabbed_cjk_mark_labels_reserve_their_physical_cells(self) -> None:
        value = fixture()
        value["edges"][2]["label"] = "否\tNo\u20dd"
        value["edges"][3]["label"] = "是\tYes\u0903"
        card = render(value, RenderOptions(max_width=120, max_height=70)).cards[0]
        route_cells = {
            tuple(cell)
            for route in card.metadata["routes"]
            for cell in route["cells"]
        }
        for edge_id, label in (("e-invalid", "否\tNo\u20dd"), ("e-valid", "是\tYes\u0903")):
            placement = card.metadata["labels"][edge_id]
            cells = {tuple(cell) for cell in placement["cells"]}
            self.assertEqual(len(cells), placement["width"])
            self.assertEqual(text_width(f"[{label}]", start=placement["x"]), placement["width"])
            self.assertFalse(cells & route_cells)


if __name__ == "__main__":
    unittest.main()
