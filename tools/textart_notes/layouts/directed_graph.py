"""Deterministic SCC layering and outer-lane routing for directed graphs.

The engine keeps graph semantics separate from style painting.  It preserves
cycles, self-loops, parallel edge identities, and author order; callers supply
already measured node rectangles and a physical-cell label measurer.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, Mapping, Sequence

from ..core.models import FitError


TAB_PHASES = 4


@dataclass(frozen=True)
class DirectedNode:
    key: str
    width: int
    height: int
    order: int


@dataclass(frozen=True)
class DirectedEdge:
    key: str
    source: str
    target: str
    order: int


@dataclass(frozen=True)
class GraphRect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width - 1

    @property
    def bottom(self) -> int:
        return self.y + self.height - 1

    def contains(self, point: tuple[int, int], *, interior: bool = False) -> bool:
        inset = 1 if interior else 0
        x, y = point
        return (
            self.x + inset <= x <= self.right - inset
            and self.y + inset <= y <= self.bottom - inset
        )

    def cells(self) -> frozenset[tuple[int, int]]:
        return frozenset(
            (x, y)
            for y in range(self.y, self.bottom + 1)
            for x in range(self.x, self.right + 1)
        )


@dataclass(frozen=True)
class GraphPort:
    edge_key: str
    role: str
    point: tuple[int, int]


@dataclass(frozen=True)
class SccGroup:
    key: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class CondensationArc:
    source_scc: str
    target_scc: str
    edge_keys: tuple[str, ...]


@dataclass(frozen=True)
class RoutedDirectedEdge:
    edge: DirectedEdge
    kind: str
    lane_x: int
    source_port: tuple[int, int]
    target_port: tuple[int, int]
    label_rect: GraphRect
    segments: tuple[tuple[tuple[int, int], ...], ...]
    cells: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class DirectedScene:
    completion_order: tuple[tuple[str, ...], ...]
    sccs: tuple[SccGroup, ...]
    scc_by_node: Mapping[str, str]
    condensation: tuple[CondensationArc, ...]
    layers: tuple[tuple[str, ...], ...]
    node_order: tuple[str, ...]
    edge_order: tuple[str, ...]
    rects: Mapping[str, GraphRect]
    ports: Mapping[str, tuple[GraphPort, ...]]
    routes: tuple[RoutedDirectedEdge, ...]
    width: int
    height: int


@dataclass(frozen=True)
class _Analysis:
    completion: tuple[tuple[str, ...], ...]
    canonical_sccs: tuple[tuple[str, ...], ...]
    scc_index: Mapping[str, int]
    scc_keys: Mapping[int, str]
    layers: tuple[tuple[str, ...], ...]
    condensation: tuple[CondensationArc, ...]


LabelMeasure = Callable[[DirectedEdge, int], int]


def _validate_graph(nodes: Sequence[DirectedNode], edges: Sequence[DirectedEdge]) -> None:
    if not nodes:
        raise ValueError("directed graph needs at least one node")
    node_keys = [node.key for node in nodes]
    edge_keys = [edge.key for edge in edges]
    if len(set(node_keys)) != len(node_keys):
        raise ValueError("directed node keys must be unique")
    if len(set(edge_keys)) != len(edge_keys):
        raise ValueError("directed edge keys must be unique")
    if len({node.order for node in nodes}) != len(nodes):
        raise ValueError("directed node author orders must be unique")
    if len({edge.order for edge in edges}) != len(edges):
        raise ValueError("directed edge author orders must be unique")
    if any(node.width < 4 or node.height < 3 for node in nodes):
        raise ValueError("directed node rectangles must be at least 4x3")
    known = set(node_keys)
    for edge in edges:
        if edge.source not in known or edge.target not in known:
            raise ValueError(f"directed edge {edge.key!r} references an unknown node")


def weak_components(
    nodes: Sequence[DirectedNode],
    edges: Sequence[DirectedEdge],
) -> tuple[tuple[str, ...], ...]:
    """Return WCCs in first-author-member order, with author-ordered members."""

    _validate_graph(nodes, edges)
    ordered_nodes = sorted(nodes, key=lambda node: node.order)
    author = {node.key: node.order for node in ordered_nodes}
    adjacent: dict[str, set[str]] = {node.key: set() for node in ordered_nodes}
    for edge in sorted(edges, key=lambda item: item.order):
        adjacent[edge.source].add(edge.target)
        adjacent[edge.target].add(edge.source)
    unseen = set(adjacent)
    components: list[tuple[str, ...]] = []
    for node in ordered_nodes:
        if node.key not in unseen:
            continue
        unseen.remove(node.key)
        pending = [node.key]
        members: list[str] = []
        while pending:
            current = pending.pop()
            members.append(current)
            for neighbor in sorted(adjacent[current], key=author.__getitem__, reverse=True):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    pending.append(neighbor)
        members.sort(key=author.__getitem__)
        components.append(tuple(members))
    return tuple(components)


def _iterative_tarjan(
    nodes: Sequence[DirectedNode],
    edges: Sequence[DirectedEdge],
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    ordered_nodes = sorted(nodes, key=lambda node: node.order)
    ordered_edges = sorted(edges, key=lambda edge: edge.order)
    author = {node.key: node.order for node in ordered_nodes}
    outgoing: dict[str, list[str]] = {node.key: [] for node in ordered_nodes}
    for edge in ordered_edges:
        outgoing[edge.source].append(edge.target)

    next_index = 0
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    tarjan_stack: list[str] = []
    on_stack: set[str] = set()
    completion: list[tuple[str, ...]] = []

    def enter(key: str) -> None:
        nonlocal next_index
        indexes[key] = next_index
        lowlinks[key] = next_index
        next_index += 1
        tarjan_stack.append(key)
        on_stack.add(key)

    for root in (node.key for node in ordered_nodes):
        if root in indexes:
            continue
        enter(root)
        frames: list[tuple[str, int]] = [(root, 0)]
        while frames:
            current, cursor = frames[-1]
            if cursor < len(outgoing[current]):
                target = outgoing[current][cursor]
                frames[-1] = (current, cursor + 1)
                if target not in indexes:
                    enter(target)
                    frames.append((target, 0))
                elif target in on_stack:
                    lowlinks[current] = min(lowlinks[current], indexes[target])
                continue

            frames.pop()
            if lowlinks[current] == indexes[current]:
                members: list[str] = []
                while True:
                    member = tarjan_stack.pop()
                    on_stack.remove(member)
                    members.append(member)
                    if member == current:
                        break
                members.sort(key=author.__getitem__)
                completion.append(tuple(members))
            if frames:
                parent = frames[-1][0]
                lowlinks[parent] = min(lowlinks[parent], lowlinks[current])

    canonical = tuple(
        sorted(completion, key=lambda group: min(author[node] for node in group))
    )
    return tuple(completion), canonical


def strongly_connected_components(
    nodes: Sequence[DirectedNode],
    edges: Sequence[DirectedEdge],
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """Return iterative Tarjan completion order and canonical SCC order."""

    _validate_graph(nodes, edges)
    return _iterative_tarjan(nodes, edges)


def _analyze(nodes: Sequence[DirectedNode], edges: Sequence[DirectedEdge]) -> _Analysis:
    completion, sccs = _iterative_tarjan(nodes, edges)
    author = {node.key: node.order for node in nodes}
    scc_index = {node: index for index, members in enumerate(sccs) for node in members}
    scc_keys = {index: f"scc-{members[0]}" for index, members in enumerate(sccs)}
    incoming: dict[int, set[int]] = {index: set() for index in range(len(sccs))}
    outgoing: dict[int, set[int]] = {index: set() for index in range(len(sccs))}
    condensation_edges: dict[tuple[int, int], list[str]] = {}
    for edge in sorted(edges, key=lambda item: item.order):
        source = scc_index[edge.source]
        target = scc_index[edge.target]
        if source == target:
            continue
        incoming[target].add(source)
        outgoing[source].add(target)
        condensation_edges.setdefault((source, target), []).append(edge.key)

    author_key = {
        index: min(author[node] for node in members)
        for index, members in enumerate(sccs)
    }
    indegree = {index: len(incoming[index]) for index in incoming}
    ready = [(author_key[index], index) for index, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    topological: list[int] = []
    rank = {index: 0 for index in range(len(sccs))}
    while ready:
        _, current = heapq.heappop(ready)
        topological.append(current)
        for target in sorted(outgoing[current], key=author_key.__getitem__):
            rank[target] = max(rank[target], rank[current] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, (author_key[target], target))
    if len(topological) != len(sccs):
        raise AssertionError("SCC condensation graph is cyclic")

    layers: list[list[int]] = [
        sorted(
            (index for index in topological if rank[index] == level),
            key=author_key.__getitem__,
        )
        for level in range(max(rank.values(), default=0) + 1)
    ]
    for _ in range(2):
        positions = {item: position for layer in layers for position, item in enumerate(layer)}
        for level in range(1, len(layers)):
            layers[level].sort(
                key=lambda item: (
                    Fraction(
                        sum(positions[parent] for parent in incoming[item]),
                        len(incoming[item]),
                    ),
                    author_key[item],
                )
            )
            positions.update({item: position for position, item in enumerate(layers[level])})
        positions = {item: position for layer in layers for position, item in enumerate(layer)}
        for level in range(len(layers) - 2, -1, -1):
            layers[level].sort(
                key=lambda item: (
                    Fraction(
                        sum(positions[child] for child in outgoing[item]),
                        len(outgoing[item]),
                    )
                    if outgoing[item]
                    else Fraction(author_key[item], 1),
                    author_key[item],
                )
            )
            positions.update({item: position for position, item in enumerate(layers[level])})

    flattened = tuple(
        tuple(node for index in layer for node in sccs[index])
        for layer in layers
    )
    condensation = tuple(
        CondensationArc(scc_keys[source], scc_keys[target], tuple(edge_keys))
        for (source, target), edge_keys in condensation_edges.items()
    )
    return _Analysis(
        completion,
        sccs,
        scc_index,
        scc_keys,
        flattened,
        condensation,
    )


def _align_x(value: int, residue: int = 2) -> int:
    return value + (residue - value) % TAB_PHASES


def axis_segment(
    start: tuple[int, int],
    end: tuple[int, int],
) -> tuple[tuple[int, int], ...]:
    x, y = start
    target_x, target_y = end
    if x != target_x and y != target_y:
        raise ValueError("directed route segment must be orthogonal")
    step_x = 0 if x == target_x else (1 if target_x > x else -1)
    step_y = 0 if y == target_y else (1 if target_y > y else -1)
    cells = [(x, y)]
    while (x, y) != end:
        x += step_x
        y += step_y
        cells.append((x, y))
    return tuple(cells)


def _deduplicate_segments(
    segments: Sequence[Sequence[tuple[int, int]]],
) -> tuple[tuple[int, int], ...]:
    seen: set[tuple[int, int]] = set()
    cells: list[tuple[int, int]] = []
    for segment in segments:
        for point in segment:
            if point not in seen:
                seen.add(point)
                cells.append(point)
    return tuple(cells)


def _overlap(first: GraphRect, second: GraphRect) -> bool:
    return not (
        first.right < second.x
        or second.right < first.x
        or first.bottom < second.y
        or second.bottom < first.y
    )


def layout_directed_component(
    nodes: Sequence[DirectedNode],
    edges: Sequence[DirectedEdge],
    *,
    label_measure: LabelMeasure,
    header_width: int,
    max_width: int,
    max_height: int,
    layer_gap: int = 8,
    node_gap: int = 2,
) -> DirectedScene:
    """Place one complete WCC and route each edge in a distinct outer lane."""

    _validate_graph(nodes, edges)
    if header_width < 0 or max_width < 1 or max_height < 1:
        raise ValueError("invalid directed scene bounds")
    if layer_gap < 1 or node_gap < 0:
        raise ValueError("invalid directed layout gaps")
    ordered_nodes = tuple(sorted(nodes, key=lambda node: node.order))
    ordered_edges = tuple(sorted(edges, key=lambda edge: edge.order))
    node_by_key = {node.key: node for node in ordered_nodes}
    analysis = _analyze(ordered_nodes, ordered_edges)

    layer_widths = [max(node_by_key[key].width for key in layer) for layer in analysis.layers]
    layer_x: list[int] = []
    cursor_x = 2
    for width in layer_widths:
        x = _align_x(cursor_x)
        layer_x.append(x)
        cursor_x = x + width + layer_gap

    rects: dict[str, GraphRect] = {}
    node_order: list[str] = []
    cursor_y = 4
    for level, layer in enumerate(analysis.layers):
        for key in layer:
            node = node_by_key[key]
            rects[key] = GraphRect(layer_x[level], cursor_y, node.width, node.height)
            node_order.append(key)
            cursor_y += node.height + node_gap

    graph_right = max(rect.right for rect in rects.values())
    height = max(rect.bottom for rect in rects.values()) + 1
    minimum_width = max(graph_right + 2, header_width)
    if minimum_width > max_width or height > max_height:
        raise FitError(
            f"indivisible directed component needs at least {minimum_width}x{height}, "
            f"limit is {max_width}x{max_height}"
        )

    events: dict[str, list[tuple[int, int, str, str]]] = {
        node.key: [] for node in ordered_nodes
    }
    for edge in ordered_edges:
        events[edge.source].append((edge.order, 0, edge.key, "source"))
        events[edge.target].append((edge.order, 1, edge.key, "target"))
    for values in events.values():
        values.sort()

    ports: dict[str, tuple[GraphPort, ...]] = {}
    endpoint: dict[tuple[str, str], tuple[int, int]] = {}
    for node in ordered_nodes:
        rect = rects[node.key]
        gathered: list[GraphPort] = []
        for slot, (_, _, edge_key, role) in enumerate(events[node.key]):
            point = (rect.right, rect.y + 1 + slot)
            if point[1] >= rect.bottom:
                raise FitError(f"node {node.key!r} has insufficient rows for edge ports")
            port = GraphPort(edge_key, role, point)
            gathered.append(port)
            endpoint[(edge_key, role)] = point
        ports[node.key] = tuple(gathered)

    label_x = graph_right + 3
    label_width = {edge.key: label_measure(edge, label_x) for edge in ordered_edges}
    if any(width < 1 for width in label_width.values()):
        raise ValueError("directed relation labels must occupy at least one cell")
    maximum_label = max(label_width.values(), default=0)
    lane_start = label_x + maximum_label + 3
    forward = [
        edge
        for edge in ordered_edges
        if analysis.scc_index[edge.source] != analysis.scc_index[edge.target]
    ]
    cyclic = [
        edge
        for edge in ordered_edges
        if analysis.scc_index[edge.source] == analysis.scc_index[edge.target]
    ]
    lane_by_edge = {
        edge.key: lane_start + 2 * index
        for index, edge in enumerate(forward + cyclic)
    }
    route_right = max(lane_by_edge.values(), default=graph_right)
    width = max(minimum_width, route_right + 2)
    if width > max_width:
        raise FitError(
            f"indivisible directed component needs {width}x{height}, "
            f"limit is {max_width}x{max_height}"
        )

    routes: list[RoutedDirectedEdge] = []
    for edge in ordered_edges:
        source_port = endpoint[(edge.key, "source")]
        target_port = endpoint[(edge.key, "target")]
        label = GraphRect(label_x, source_port[1], label_width[edge.key], 1)
        lane_x = lane_by_edge[edge.key]
        segments = (
            axis_segment(source_port, (label.x - 1, source_port[1])),
            axis_segment((label.right + 1, source_port[1]), (lane_x, source_port[1])),
            axis_segment((lane_x, source_port[1]), (lane_x, target_port[1])),
            axis_segment((lane_x, target_port[1]), target_port),
        )
        routes.append(
            RoutedDirectedEdge(
                edge,
                "cycle"
                if analysis.scc_index[edge.source] == analysis.scc_index[edge.target]
                else "forward",
                lane_x,
                source_port,
                target_port,
                label,
                segments,
                _deduplicate_segments(segments),
            )
        )

    _validate_scene(rects, routes, width, height)
    scc_groups = tuple(
        SccGroup(analysis.scc_keys[index], members)
        for index, members in enumerate(analysis.canonical_sccs)
    )
    scc_by_node = {
        node: analysis.scc_keys[index]
        for node, index in analysis.scc_index.items()
    }
    return DirectedScene(
        analysis.completion,
        scc_groups,
        scc_by_node,
        analysis.condensation,
        analysis.layers,
        tuple(node_order),
        tuple(edge.key for edge in ordered_edges),
        rects,
        ports,
        tuple(routes),
        width,
        height,
    )


def _validate_scene(
    rects: Mapping[str, GraphRect],
    routes: Sequence[RoutedDirectedEdge],
    width: int,
    height: int,
) -> None:
    items = list(rects.items())
    for index, (first_key, first) in enumerate(items):
        for second_key, second in items[index + 1 :]:
            if _overlap(first, second):
                raise FitError(f"directed nodes {first_key!r} and {second_key!r} overlap")
    labels = [(route.edge.key, route.label_rect) for route in routes]
    for index, (first_key, first) in enumerate(labels):
        for second_key, second in labels[index + 1 :]:
            if _overlap(first, second):
                raise FitError(
                    f"directed labels {first_key!r} and {second_key!r} overlap"
                )
    label_cells = set().union(*(label.cells() for _, label in labels)) if labels else set()
    for route in routes:
        allowed = {route.source_port, route.target_port}
        for point in route.cells:
            x, y = point
            if not (0 <= x < width and 0 <= y < height):
                raise FitError(f"directed edge {route.edge.key!r} leaves the card")
            if point in label_cells:
                raise FitError(f"directed edge {route.edge.key!r} crosses a label")
            for node_key, rect in rects.items():
                if rect.contains(point) and point not in allowed:
                    raise FitError(
                        f"directed edge {route.edge.key!r} crosses node {node_key!r}"
                    )
                if rect.contains(point, interior=True):
                    raise FitError(
                        f"directed edge {route.edge.key!r} enters node {node_key!r}"
                    )
