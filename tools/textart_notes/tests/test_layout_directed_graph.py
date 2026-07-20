from __future__ import annotations

import unittest

from tools.textart_notes.core.models import FitError
from tools.textart_notes.layouts.directed_graph import (
    DirectedEdge,
    DirectedNode,
    layout_directed_component,
    strongly_connected_components,
    weak_components,
)


class DirectedGraphLayoutTests(unittest.TestCase):
    def test_weak_components_keep_first_member_and_author_order(self) -> None:
        nodes = tuple(DirectedNode(key, 12, 4, order) for order, key in enumerate(("z", "a", "y", "b")))
        edges = (
            DirectedEdge("zy", "z", "y", 0),
            DirectedEdge("ab", "a", "b", 1),
        )
        self.assertEqual(weak_components(nodes, edges), (("z", "y"), ("a", "b")))

    def test_iterative_tarjan_handles_depth_and_preserves_orders(self) -> None:
        count = 1200
        nodes = tuple(DirectedNode(f"n-{index}", 12, 4, index) for index in range(count))
        chain = tuple(
            DirectedEdge(f"e-{index}", f"n-{index}", f"n-{index + 1}", index)
            for index in range(count - 1)
        )
        completion, canonical = strongly_connected_components(nodes, chain)
        self.assertEqual(completion[0], (f"n-{count - 1}",))
        self.assertEqual(completion[-1], ("n-0",))
        self.assertEqual(canonical[0], ("n-0",))
        cycle = chain + (DirectedEdge("close", f"n-{count - 1}", "n-0", count - 1),)
        cycle_completion, cycle_canonical = strongly_connected_components(nodes, cycle)
        expected = tuple(f"n-{index}" for index in range(count))
        self.assertEqual(cycle_completion, (expected,))
        self.assertEqual(cycle_canonical, (expected,))

    def test_cycles_forward_lanes_ports_labels_and_bounds(self) -> None:
        nodes = tuple(
            DirectedNode(key, 18, height, order)
            for order, (key, height) in enumerate((("a", 7), ("b", 6), ("c", 6), ("d", 5)))
        )
        edges = (
            DirectedEdge("ab", "a", "b", 0),
            DirectedEdge("bc", "b", "c", 1),
            DirectedEdge("ca", "c", "a", 2),
            DirectedEdge("ad", "a", "d", 3),
            DirectedEdge("loop", "d", "d", 4),
        )
        scene = layout_directed_component(
            nodes,
            edges,
            label_measure=lambda edge, x: 6 + (x % 4),
            header_width=24,
            max_width=160,
            max_height=100,
        )
        self.assertEqual(scene.scc_by_node["a"], scene.scc_by_node["b"])
        self.assertNotEqual(scene.scc_by_node["a"], scene.scc_by_node["d"])
        routes = {route.edge.key: route for route in scene.routes}
        self.assertEqual(routes["ad"].kind, "forward")
        for key in ("ab", "bc", "ca", "loop"):
            self.assertEqual(routes[key].kind, "cycle")
            self.assertGreater(routes[key].lane_x, routes["ad"].lane_x)
        label_cells = set().union(*(route.label_rect.cells() for route in scene.routes))
        for route in scene.routes:
            self.assertTrue(set(route.cells).isdisjoint(label_cells))
            self.assertEqual(route.cells[0], route.source_port)
            self.assertEqual(route.cells[-1], route.target_port)
        self.assertLessEqual(scene.width, 160)
        self.assertLessEqual(scene.height, 100)

    def test_indivisible_scene_reports_fit_before_building_huge_routes(self) -> None:
        count = 1100
        nodes = tuple(DirectedNode(f"n-{index}", 12, 4, index) for index in range(count))
        edges = tuple(
            DirectedEdge(f"e-{index}", f"n-{index}", f"n-{index + 1}", index)
            for index in range(count - 1)
        )
        with self.assertRaises(FitError):
            layout_directed_component(
                nodes,
                edges,
                label_measure=lambda edge, x: 8,
                header_width=10,
                max_width=160,
                max_height=100,
            )


if __name__ == "__main__":
    unittest.main()
