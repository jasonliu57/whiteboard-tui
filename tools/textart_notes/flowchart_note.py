#!/usr/bin/env python3
"""Render one strict connected flow DAG as an indivisible text-art card."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.canvas import Canvas
from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.router import Rect, shortest_grid_route, validate_cell_route
from tools.textart_notes.core.schema import array_value, check_keys, int_value, object_value, slug_value, string_value
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.layouts.flow import FlowArc, FlowNode, layer_dag, place_flow


RENDERER = "flowchart-note"
NODE_KINDS = ("start", "process", "decision", "end")
TARGET_PORTS = ("north-west", "north", "north-east")
MAX_NODES = 64
MAX_EDGES = 128
MAX_DETAILS = 16


@dataclass(frozen=True)
class Node:
    node_id: str
    kind: str
    label: str
    details: tuple[str, ...]
    order: int


@dataclass(frozen=True)
class Edge:
    edge_id: str
    source: str
    target: str
    source_port: str
    target_port: str
    label: str | None
    order: int


@dataclass(frozen=True)
class FlowChart:
    flow_id: str
    title: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]


@dataclass(frozen=True)
class LabelPlacement:
    edge_id: str
    x: int
    y: int
    width: int

    @property
    def cells(self) -> frozenset[tuple[int, int]]:
        return frozenset((x, self.y) for x in range(self.x, self.x + self.width))


@dataclass(frozen=True)
class RoutedEdge:
    edge: Edge
    cells: tuple[tuple[int, int], ...]
    source_boundary: tuple[int, int]
    source_external: tuple[int, int]
    target_boundary: tuple[int, int]
    target_external: tuple[int, int]


@dataclass(frozen=True)
class Scene:
    width: int
    height: int
    layers: tuple[tuple[str, ...], ...]
    rects: Mapping[str, Rect]
    labels: Mapping[str, LabelPlacement]
    routes: tuple[RoutedEdge, ...]


def _text(value: object, path: str) -> str:
    result = string_value(value, path, single_line=True, allow_tabs=True)
    if not any(not character.isspace() for character in result):
        raise InputError(f"{path} must contain visible text")
    if len(result) > 256:
        raise InputError(f"{path} may contain at most 256 code points")
    return result


def _source_rank(port: str) -> int:
    return {"west": 0, "south": 1, "east": 2}[port]


def _normalize(data: dict[str, object]) -> FlowChart:
    root = object_value(data, "input")
    check_keys(root, "input", required={"schema_version", "id", "title", "nodes", "edges"}, allowed={"schema_version", "id", "title", "nodes", "edges"})
    if int_value(root["schema_version"], "schema_version", minimum=1, maximum=1) != 1:
        raise InputError("schema_version must equal 1")
    values = array_value(root["nodes"], "nodes")
    if not 1 <= len(values) <= MAX_NODES:
        raise InputError(f"nodes must contain 1..{MAX_NODES} entries")
    nodes: list[Node] = []
    node_ids: set[str] = set()
    for index, value in enumerate(values):
        path = f"nodes[{index}]"
        record = object_value(value, path)
        check_keys(record, path, required={"id", "kind", "label", "details"}, allowed={"id", "kind", "label", "details"})
        node_id = slug_value(record["id"], f"{path}.id", max_length=48)
        if node_id in node_ids:
            raise InputError(f"duplicate node id {node_id!r}")
        node_ids.add(node_id)
        kind = record["kind"]
        if kind not in NODE_KINDS:
            raise InputError(f"{path}.kind must be one of {', '.join(NODE_KINDS)}")
        details_raw = array_value(record["details"], f"{path}.details")
        if len(details_raw) > MAX_DETAILS:
            raise InputError(f"{path}.details may contain at most {MAX_DETAILS} entries")
        nodes.append(
            Node(
                node_id,
                str(kind),
                _text(record["label"], f"{path}.label"),
                tuple(_text(item, f"{path}.details[{item_index}]") for item_index, item in enumerate(details_raw)),
                index,
            )
        )
    starts = [node for node in nodes if node.kind == "start"]
    ends = [node for node in nodes if node.kind == "end"]
    if len(starts) != 1 or len(ends) != 1:
        raise InputError("flowchart requires exactly one start and one end node")

    raw_edges = array_value(root["edges"], "edges")
    if len(raw_edges) > MAX_EDGES:
        raise InputError(f"edges may contain at most {MAX_EDGES} entries")
    node_by_id = {node.node_id: node for node in nodes}
    edges: list[Edge] = []
    edge_ids: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    source_ports: set[tuple[str, str]] = set()
    target_ports: set[tuple[str, str]] = set()
    for index, value in enumerate(raw_edges):
        path = f"edges[{index}]"
        record = object_value(value, path)
        check_keys(record, path, required={"id", "from", "to", "source_port", "target_port", "label"}, allowed={"id", "from", "to", "source_port", "target_port", "label"})
        edge_id = slug_value(record["id"], f"{path}.id", max_length=64)
        if edge_id in edge_ids:
            raise InputError(f"duplicate edge id {edge_id!r}")
        edge_ids.add(edge_id)
        source = slug_value(record["from"], f"{path}.from", max_length=48)
        target = slug_value(record["to"], f"{path}.to", max_length=48)
        if source not in node_by_id or target not in node_by_id:
            raise InputError(f"{path} references an unknown node")
        if source == target or (source, target) in pairs:
            raise InputError(f"duplicate or self edge {source!r}->{target!r}")
        pairs.add((source, target))
        source_port = record["source_port"]
        target_port = record["target_port"]
        legal_sources = {
            "start": ("south",),
            "process": ("south",),
            "decision": ("west", "east"),
            "end": (),
        }[node_by_id[source].kind]
        if source_port not in legal_sources:
            raise InputError(f"{path}.source_port is illegal for {node_by_id[source].kind}")
        if node_by_id[target].kind == "start" or target_port not in TARGET_PORTS:
            raise InputError(f"{path}.target_port is illegal")
        if (source, str(source_port)) in source_ports or (target, str(target_port)) in target_ports:
            raise InputError(f"{path} exceeds a port capacity")
        source_ports.add((source, str(source_port)))
        target_ports.add((target, str(target_port)))
        if node_by_id[source].kind == "decision":
            label = _text(record["label"], f"{path}.label")
        else:
            if record["label"] is not None:
                raise InputError(f"{path}.label must be null outside a decision")
            label = None
        edges.append(Edge(edge_id, source, target, str(source_port), str(target_port), label, index))

    arcs = [FlowArc(edge.edge_id, edge.source, edge.target, _source_rank(edge.source_port), edge.order) for edge in edges]
    layer_dag([FlowNode(node.node_id, 3, 3, node.order) for node in nodes], arcs)
    outgoing = {node.node_id: [] for node in nodes}
    incoming = {node.node_id: [] for node in nodes}
    for edge in edges:
        outgoing[edge.source].append(edge)
        incoming[edge.target].append(edge)
    reachable = {starts[0].node_id}
    pending = [starts[0].node_id]
    while pending:
        source = pending.pop()
        for edge in outgoing[source]:
            if edge.target not in reachable:
                reachable.add(edge.target)
                pending.append(edge.target)
    missing = [node.node_id for node in nodes if node.node_id not in reachable]
    if missing:
        raise InputError("nodes unreachable from start: " + ", ".join(missing))
    for node in nodes:
        ins, outs = incoming[node.node_id], outgoing[node.node_id]
        if node.kind == "start" and (ins or len(outs) != 1):
            raise InputError("start must have no incoming and exactly one outgoing edge")
        if node.kind == "end" and (not ins or outs):
            raise InputError("end must have incoming edges and no outgoing edge")
        if node.kind == "process" and (not ins or len(outs) != 1):
            raise InputError(f"process {node.node_id!r} needs incoming and exactly one outgoing edge")
        if node.kind == "decision":
            if not ins or len(outs) != 2 or {edge.source_port for edge in outs} != {"west", "east"}:
                raise InputError(f"decision {node.node_id!r} needs one west and one east branch")
            labels = [edge.label.strip().casefold() for edge in outs if edge.label is not None]
            if len(set(labels)) != 2 or len({edge.target for edge in outs}) != 2:
                raise InputError(f"decision {node.node_id!r} has ambiguous branches")
    return FlowChart(slug_value(root["id"], "id", max_length=48), _text(root["title"], "title"), tuple(nodes), tuple(edges))


def _node_lines(node: Node) -> tuple[str, ...]:
    prefix = {"start": "(START) ", "process": "", "decision": "<?> ", "end": "(END) "}[node.kind]
    return (f"{prefix}[{node.node_id}] {node.label}",) + tuple(f"- {line}" for line in node.details)


def _size(node: Node) -> tuple[int, int]:
    width = max(text_width(line, start=phase) for line in _node_lines(node) for phase in range(4)) + 4
    return max(11, width + (2 if node.kind == "decision" else 0)), len(_node_lines(node)) + 2


def _tag(edge: Edge, theme: str = "ascii") -> str:
    assert edge.label is not None
    if theme == "ascii":
        return f"[{edge.label}]"
    return f"‹{edge.label}›"


def _source_port(rect: Rect, port: str) -> tuple[tuple[int, int], tuple[int, int]]:
    if port == "south":
        boundary = (rect.x + rect.width // 2, rect.y + rect.height - 1)
        return boundary, (boundary[0], boundary[1] + 1)
    y = rect.y + rect.height // 2
    if port == "west":
        return (rect.x, y), (rect.x - 1, y)
    return (rect.x + rect.width - 1, y), (rect.x + rect.width, y)


def _target_port(rect: Rect, port: str) -> tuple[tuple[int, int], tuple[int, int]]:
    fraction = {"north-west": 1, "north": 2, "north-east": 3}[port]
    x = rect.x + fraction * rect.width // 4
    return (x, rect.y), (x, rect.y - 1)


def _scene(model: FlowChart, options: RenderOptions) -> Scene:
    outgoing = {node.node_id: [] for node in model.nodes}
    for edge in model.edges:
        outgoing[edge.source].append(edge)
    flow_nodes: list[FlowNode] = []
    for node in model.nodes:
        width, height = _size(node)
        left = right = 0
        if node.kind == "decision":
            for edge in outgoing[node.node_id]:
                clearance = max(text_width(_tag(edge), start=phase) for phase in range(4)) + 3
                if edge.source_port == "west":
                    left = clearance
                else:
                    right = clearance
        flow_nodes.append(FlowNode(node.node_id, width, height, node.order, left, right))
    arcs = [FlowArc(edge.edge_id, edge.source, edge.target, _source_rank(edge.source_port), edge.order) for edge in model.edges]
    layout = place_flow(flow_nodes, arcs)
    header_width = text_width(f"[{model.flow_id}] {model.title}")
    width = max(layout.width, header_width)
    shift = (width - layout.width) // 2
    rects = {item.key: Rect(item.rect.x + shift, item.rect.y, item.rect.width, item.rect.height) for item in layout.placements}
    if width > options.max_width or layout.height > options.max_height:
        raise FitError(f"indivisible flowchart needs {width}x{layout.height}, limit is {options.max_width}x{options.max_height}")

    node_cells = set().union(*(set((x, y) for y in range(rect.y, rect.y + rect.height) for x in range(rect.x, rect.x + rect.width)) for rect in rects.values()))
    labels: dict[str, LabelPlacement] = {}
    label_cells: set[tuple[int, int]] = set()
    for edge in model.edges:
        if edge.label is None:
            continue
        _, external = _source_port(rects[edge.source], edge.source_port)
        geometry = _tag(edge)
        label_width = max(text_width(geometry, start=phase) for phase in range(4))
        x = external[0] - label_width if edge.source_port == "west" else external[0] + 1
        y = external[1] + 1
        actual = text_width(geometry, start=x)
        placement = LabelPlacement(edge.edge_id, x, y, actual)
        if x < 0 or x + actual > width or y >= layout.height:
            raise FitError(f"branch label {edge.edge_id!r} leaves the flowchart")
        if placement.cells & (node_cells | label_cells):
            raise FitError(f"branch label {edge.edge_id!r} overlaps another object")
        labels[edge.edge_id] = placement
        label_cells.update(placement.cells)

    port_geometry: dict[str, tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]] = {}
    terminals: set[tuple[int, int]] = set()
    for edge in model.edges:
        source_boundary, source_external = _source_port(rects[edge.source], edge.source_port)
        target_boundary, target_external = _target_port(rects[edge.target], edge.target_port)
        if source_external in terminals or target_external in terminals:
            raise FitError("two ports resolve to the same route cell")
        terminals.update((source_external, target_external))
        port_geometry[edge.edge_id] = source_boundary, source_external, target_boundary, target_external

    layer_by_node = {key: index for index, layer in enumerate(layout.layers) for key in layer}
    route_order = sorted(model.edges, key=lambda edge: (layer_by_node[edge.source], rects[edge.source].x, _source_rank(edge.source_port), edge.order))
    reserved: set[tuple[int, int]] = set()
    routes: list[RoutedEdge] = []
    for edge in route_order:
        source_boundary, source_external, target_boundary, target_external = port_geometry[edge.edge_id]
        try:
            path = shortest_grid_route(
                source_external,
                target_external,
                width=width,
                height=layout.height,
                blocked=node_cells | label_cells | reserved | (terminals - {source_external, target_external}),
                monotone_vertical=True,
            )
        except ValueError as error:
            raise FitError(f"edge {edge.edge_id!r} cannot be routed: {error}") from error
        validate_cell_route(path, start=source_external, end=target_external)
        if set(path) & (node_cells | label_cells | reserved):
            raise AssertionError("flow router crossed an occupied cell")
        reserved.update(path)
        routes.append(RoutedEdge(edge, path, source_boundary, source_external, target_boundary, target_external))
    return Scene(width, layout.height, layout.layers, rects, labels, tuple(routes))


def _route_stub(canvas: Canvas, route: RoutedEdge, theme: str) -> None:
    path = route.cells
    arrow = "v" if theme == "ascii" else "▼"
    stem = (route.source_boundary,) + path
    canvas.draw_path(stem)
    canvas.put_text(path[-1][0], path[-1][1], arrow, overwrite=True)


def _paint(model: FlowChart, scene: Scene, theme: str) -> str:
    canvas = Canvas(scene.width, scene.height, theme)
    canvas.put_text(0, 0, f"[{model.flow_id}] {model.title}")
    canvas.draw_path(((0, 1), (scene.width - 1, 1)))
    by_node = {node.node_id: node for node in model.nodes}
    for layer in scene.layers:
        for node_id in layer:
            node = by_node[node_id]
            rect = scene.rects[node_id]
            canvas.draw_box(rect.x, rect.y, rect.width, rect.height)
            for row, line in enumerate(_node_lines(node), start=rect.y + 1):
                canvas.put_text(rect.x + 2, row, line)
    for route in scene.routes:
        _route_stub(canvas, route, theme)
    by_edge = {edge.edge_id: edge for edge in model.edges}
    for edge_id, placement in scene.labels.items():
        canvas.put_text(placement.x, placement.y, _tag(by_edge[edge_id], theme))
    return canvas.to_text()


def _metadata(model: FlowChart, scene: Scene, single_card: bool) -> dict[str, object]:
    route_by_id = {route.edge.edge_id: route for route in scene.routes}
    return {
        "schema_version": 1,
        "flow_id": model.flow_id,
        "split_policy": "strict-indivisible-diagram",
        "single_card_requested": single_card,
        "node_order": [node.node_id for node in model.nodes],
        "edge_order": [edge.edge_id for edge in model.edges],
        "route_order": [route.edge.edge_id for route in scene.routes],
        "layers": [list(layer) for layer in scene.layers],
        "node_rects": {
            node.node_id: {
                "kind": node.kind,
                "x": scene.rects[node.node_id].x,
                "y": scene.rects[node.node_id].y,
                "width": scene.rects[node.node_id].width,
                "height": scene.rects[node.node_id].height,
            }
            for node in model.nodes
        },
        "routes": [
            {
                "id": edge.edge_id,
                "from": edge.source,
                "to": edge.target,
                "source_port": edge.source_port,
                "target_port": edge.target_port,
                "source_boundary": list(route_by_id[edge.edge_id].source_boundary),
                "source_external": list(route_by_id[edge.edge_id].source_external),
                "target_boundary": list(route_by_id[edge.edge_id].target_boundary),
                "target_external": list(route_by_id[edge.edge_id].target_external),
                "cells": [list(cell) for cell in route_by_id[edge.edge_id].cells],
                "label": edge.label,
            }
            for edge in model.edges
        ],
        "labels": {
            edge_id: {
                "x": placement.x,
                "y": placement.y,
                "width": placement.width,
                "cells": [list(cell) for cell in sorted(placement.cells)],
            }
            for edge_id, placement in scene.labels.items()
        },
        "continuation": {"part": 1, "parts": 1, "incoming_boundary_edges": [], "outgoing_boundary_edges": []},
    }


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    model = _normalize(data)
    scene = _scene(model, options)
    card = CardDraft(
        f"{model.flow_id}-000",
        _paint(model, scene, options.theme),
        scene.width,
        scene.height,
        0,
        0,
        _metadata(model, scene, options.single_card),
    )
    result = RenderResult(RENDERER, options.theme, (card,))
    validate_result(result, options)
    return result


if __name__ == "__main__":
    raise SystemExit(run_renderer(RENDERER, render))
