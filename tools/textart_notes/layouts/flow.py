"""Stable DAG layering and rectangle placement for flow-like styles."""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Sequence

from ..core.models import InputError
from ..core.router import Rect


@dataclass(frozen=True)
class FlowNode:
    key: str
    width: int
    height: int
    order: int
    left_clearance: int = 0
    right_clearance: int = 0


@dataclass(frozen=True)
class FlowArc:
    key: str
    source: str
    target: str
    rank: int
    order: int


@dataclass(frozen=True)
class FlowPlacement:
    key: str
    rect: Rect
    layer: int


@dataclass(frozen=True)
class FlowLayout:
    layers: tuple[tuple[str, ...], ...]
    placements: tuple[FlowPlacement, ...]
    width: int
    height: int


def layer_dag(
    nodes: Sequence[FlowNode], arcs: Sequence[FlowArc]
) -> tuple[dict[str, int], tuple[tuple[str, ...], ...]]:
    """Assign longest-path layers and stable branch-aware within-layer order."""

    keys = [node.key for node in nodes]
    if not keys or len(set(keys)) != len(keys):
        raise InputError("flow nodes must be non-empty and unique")
    node_by_key = {node.key: node for node in nodes}
    incoming = {key: [] for key in keys}
    outgoing = {key: [] for key in keys}
    indegree = {key: 0 for key in keys}
    for arc in arcs:
        if arc.source not in node_by_key or arc.target not in node_by_key:
            raise InputError(f"flow arc {arc.key!r} references a missing node")
        incoming[arc.target].append(arc)
        outgoing[arc.source].append(arc)
        indegree[arc.target] += 1
    ready = [(node_by_key[key].order, key) for key in keys if indegree[key] == 0]
    heapq.heapify(ready)
    topo: list[str] = []
    while ready:
        _, key = heapq.heappop(ready)
        topo.append(key)
        for arc in sorted(outgoing[key], key=lambda item: (item.rank, item.order)):
            indegree[arc.target] -= 1
            if indegree[arc.target] == 0:
                heapq.heappush(ready, (node_by_key[arc.target].order, arc.target))
    if len(topo) != len(keys):
        raise InputError("flow graph contains a directed cycle")

    layer: dict[str, int] = {}
    path_key: dict[str, tuple[tuple[int, int], ...]] = {}
    for key in topo:
        sources = incoming[key]
        if not sources:
            layer[key] = 0
            path_key[key] = ()
        else:
            layer[key] = 1 + max(layer[arc.source] for arc in sources)
            path_key[key] = min(
                path_key[arc.source] + ((arc.rank, arc.order),)
                for arc in sources
            )
    output: list[tuple[str, ...]] = []
    for level in range(max(layer.values()) + 1):
        members = [key for key in keys if layer[key] == level]
        members.sort(key=lambda key: (path_key[key], node_by_key[key].order))
        output.append(tuple(members))
    return layer, tuple(output)


def place_flow(
    nodes: Sequence[FlowNode],
    arcs: Sequence[FlowArc],
    *,
    header_height: int = 3,
    horizontal_gap: int = 5,
    vertical_gap: int = 7,
    margin: int = 2,
    minimum_width: int = 12,
) -> FlowLayout:
    """Place stable DAG layers without owning routes or painter glyphs."""

    if header_height < 0 or horizontal_gap < 0 or vertical_gap < 1 or margin < 0:
        raise ValueError("invalid flow geometry")
    node_by_key = {node.key: node for node in nodes}
    if any(
        node.width < 3
        or node.height < 3
        or node.left_clearance < 0
        or node.right_clearance < 0
        for node in nodes
    ):
        raise ValueError("invalid flow node geometry")
    _, layers = layer_dag(nodes, arcs)
    spans = [
        sum(
            node_by_key[key].left_clearance
            + node_by_key[key].width
            + node_by_key[key].right_clearance
            for key in layer
        )
        + horizontal_gap * max(0, len(layer) - 1)
        for layer in layers
    ]
    width = max(minimum_width, max(spans) + 2 * margin)
    heights = [max(node_by_key[key].height for key in layer) for layer in layers]
    y_by_layer: list[int] = []
    cursor_y = header_height
    for index, height in enumerate(heights):
        y_by_layer.append(cursor_y)
        cursor_y += height
        if index + 1 < len(heights):
            cursor_y += vertical_gap
    placements: list[FlowPlacement] = []
    for level, layer in enumerate(layers):
        cursor_x = (width - spans[level]) // 2
        for index, key in enumerate(layer):
            node = node_by_key[key]
            cursor_x += node.left_clearance
            placements.append(
                FlowPlacement(key, Rect(cursor_x, y_by_layer[level], node.width, node.height), level)
            )
            cursor_x += node.width + node.right_clearance
            if index + 1 < len(layer):
                cursor_x += horizontal_gap
    return FlowLayout(layers, tuple(placements), width, cursor_y)
