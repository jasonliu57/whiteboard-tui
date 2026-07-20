from __future__ import annotations

import unittest

from tools.textart_notes.core.models import InputError
from tools.textart_notes.layouts.flow import FlowArc, FlowNode, layer_dag, place_flow


class FlowLayoutTests(unittest.TestCase):
    def graph(self):
        nodes = tuple(FlowNode(key, 9, 3, index) for index, key in enumerate(("start", "decision", "left", "right", "merge")))
        arcs = (
            FlowArc("a", "start", "decision", 1, 0),
            FlowArc("b", "decision", "right", 2, 1),
            FlowArc("c", "decision", "left", 0, 2),
            FlowArc("d", "left", "merge", 1, 3),
            FlowArc("e", "right", "merge", 1, 4),
        )
        return nodes, arcs

    def test_longest_layers_and_branch_order(self) -> None:
        nodes, arcs = self.graph()
        layers = layer_dag(nodes, arcs)[1]
        self.assertEqual(layers, (("start",), ("decision",), ("left", "right"), ("merge",)))
        layout = place_flow(nodes, arcs)
        self.assertEqual(layout.layers, layers)
        self.assertEqual(layout, place_flow(nodes, arcs))
        rects = [item.rect for item in layout.placements]
        for index, rect in enumerate(rects):
            self.assertTrue(all(not (
                rect.x < other.x + other.width and other.x < rect.x + rect.width
                and rect.y < other.y + other.height and other.y < rect.y + rect.height
            ) for other in rects[index + 1 :]))

    def test_cycle_and_missing_node_rejected(self) -> None:
        nodes = (FlowNode("a", 3, 3, 0), FlowNode("b", 3, 3, 1))
        with self.assertRaises(InputError):
            layer_dag(nodes, (FlowArc("a-b", "a", "b", 0, 0), FlowArc("b-a", "b", "a", 0, 1)))
        with self.assertRaises(InputError):
            layer_dag(nodes, (FlowArc("bad", "a", "missing", 0, 0),))


if __name__ == "__main__":
    unittest.main()
