#!/usr/bin/env python3
"""Render general directed concept maps as deterministic text-art cards."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.canvas import Canvas
from tools.textart_notes.core.cell_width import cell_clusters, expand_tabs, text_width
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import (
    CardDraft,
    FitError,
    InputError,
    RenderOptions,
    RenderResult,
)
from tools.textart_notes.core.schema import (
    array_value,
    check_keys,
    object_value,
    slug_value,
    string_value,
)
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_clusters
from tools.textart_notes.layouts.directed_graph import (
    DirectedEdge,
    DirectedNode,
    DirectedScene,
    GraphRect,
    layout_directed_component,
    weak_components,
)


RENDERER = "concept-map"
CARD_GAP = 2
_STYLE_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_ARROW_LEFT = {"ascii": "<", "unicode-light": "←", "unicode-rich": "⇐"}


@dataclass(frozen=True)
class Concept:
    concept_id: str
    label: str
    detail: str
    order: int


@dataclass(frozen=True)
class Relation:
    edge_id: str
    source: str
    target: str
    relation: str
    order: int


@dataclass(frozen=True)
class ConceptMap:
    map_id: str
    title: str
    concepts: tuple[Concept, ...]
    edges: tuple[Relation, ...]


@dataclass(frozen=True)
class MeasuredConcept:
    concept: Concept
    lines: tuple[str, ...]
    interior_width: int
    width: int
    height: int


def _id(value: object, path: str) -> str:
    result = slug_value(value, path, max_length=48)
    if _STYLE_ID.fullmatch(result) is None:
        raise InputError(f"{path} must start with a lowercase ASCII letter")
    return result


def _visible(value: object, path: str) -> str:
    result = string_value(value, path, single_line=True, allow_tabs=True)
    if not any(not character.isspace() for character in result):
        raise InputError(f"{path} must contain visible text")
    for character in result:
        if character in {"\u2028", "\u2029"}:
            raise InputError(f"{path} contains unsupported line-separator text")
    return result


def _normalize(data: dict[str, object]) -> ConceptMap:
    root = object_value(data, "input")
    check_keys(
        root,
        "input",
        required={"id", "title", "concepts", "edges"},
        allowed={"id", "title", "concepts", "edges"},
    )
    map_id = _id(root["id"], "id")
    title = _visible(root["title"], "title")
    raw_concepts = array_value(root["concepts"], "concepts")
    if not raw_concepts:
        raise InputError("concepts must be a non-empty array")

    seen = {map_id}
    concepts: list[Concept] = []
    for index, value in enumerate(raw_concepts):
        path = f"concepts[{index}]"
        record = object_value(value, path)
        check_keys(
            record,
            path,
            required={"id", "label", "detail"},
            allowed={"id", "label", "detail"},
        )
        concept_id = _id(record["id"], f"{path}.id")
        if concept_id in seen:
            raise InputError(f"duplicate global id {concept_id!r}")
        seen.add(concept_id)
        concepts.append(
            Concept(
                concept_id,
                _visible(record["label"], f"{path}.label"),
                _visible(record["detail"], f"{path}.detail"),
                index,
            )
        )

    known = {concept.concept_id for concept in concepts}
    raw_edges = array_value(root["edges"], "edges")
    edges: list[Relation] = []
    semantic: set[tuple[str, str, str]] = set()
    for index, value in enumerate(raw_edges):
        path = f"edges[{index}]"
        record = object_value(value, path)
        check_keys(
            record,
            path,
            required={"id", "from", "to", "relation"},
            allowed={"id", "from", "to", "relation"},
        )
        edge_id = _id(record["id"], f"{path}.id")
        if edge_id in seen:
            raise InputError(f"duplicate global id {edge_id!r}")
        seen.add(edge_id)
        source = _id(record["from"], f"{path}.from")
        target = _id(record["to"], f"{path}.to")
        if source not in known or target not in known:
            raise InputError(f"{path} references an unknown concept")
        relation = _visible(record["relation"], f"{path}.relation")
        key = (source, target, relation)
        if key in semantic:
            raise InputError(f"{path} duplicates directed relation {source!r}->{target!r}")
        semantic.add(key)
        edges.append(Relation(edge_id, source, target, relation, index))
    return ConceptMap(map_id, title, tuple(concepts), tuple(edges))


def _maximum_cluster_width(text: str) -> int:
    return max(
        (
            text_width(cluster, start=phase)
            for cluster in cell_clusters(text)
            for phase in range(4)
        ),
        default=0,
    )


def _measure_concept(concept: Concept, endpoint_count: int) -> MeasuredConcept:
    raw_lines = (
        f"{concept.concept_id} | {concept.label}",
        f"detail: {concept.detail}",
    )
    natural = max(text_width(line) for line in raw_lines)
    indivisible = max(_maximum_cluster_width(line) for line in raw_lines)
    interior = max(16, min(32, natural), indivisible)
    lines = tuple(
        visual
        for line in raw_lines
        for visual in wrap_clusters(line, interior, start_column=0)
    )
    return MeasuredConcept(
        concept,
        lines,
        interior,
        interior + 4,
        max(len(lines), endpoint_count, 1) + 2,
    )


def _relation_text(edge: Relation) -> str:
    return f"[{edge.edge_id}: {edge.relation}]"


def _component_scene(
    model: ConceptMap,
    component: tuple[str, ...],
    component_index: int,
    component_count: int,
    options: RenderOptions,
) -> tuple[DirectedScene, Mapping[str, MeasuredConcept], Mapping[str, Relation]]:
    members = set(component)
    relations = tuple(
        edge for edge in model.edges if edge.source in members and edge.target in members
    )
    endpoint_counts = {key: 0 for key in component}
    for edge in relations:
        endpoint_counts[edge.source] += 1
        endpoint_counts[edge.target] += 1
    measured = {
        concept.concept_id: _measure_concept(
            concept,
            endpoint_counts[concept.concept_id],
        )
        for concept in model.concepts
        if concept.concept_id in members
    }
    layout_nodes = tuple(
        DirectedNode(key, measured[key].width, measured[key].height, measured[key].concept.order)
        for key in component
    )
    layout_edges = tuple(
        DirectedEdge(edge.edge_id, edge.source, edge.target, edge.order)
        for edge in relations
    )
    relation_by_id = {edge.edge_id: edge for edge in relations}
    header0 = expand_tabs(f"concept-map {model.map_id}: {model.title}")
    header1 = (
        f"component {component_index + 1}/{component_count} | "
        f"{len(component)} concepts | {len(relations)} relations"
    )

    def measure_label(edge: DirectedEdge, x: int) -> int:
        return text_width(_relation_text(relation_by_id[edge.key]), start=x)

    scene = layout_directed_component(
        layout_nodes,
        layout_edges,
        label_measure=measure_label,
        header_width=max(text_width(header0), text_width(header1)),
        max_width=options.max_width,
        max_height=options.max_height,
    )
    return scene, measured, relation_by_id


def _paint(
    model: ConceptMap,
    scene: DirectedScene,
    measured: Mapping[str, MeasuredConcept],
    relations: Mapping[str, Relation],
    component_index: int,
    component_count: int,
    theme: str,
) -> str:
    canvas = Canvas(scene.width, scene.height, theme)
    for rect in scene.rects.values():
        canvas.draw_box(rect.x, rect.y, rect.width, rect.height)
    for route in scene.routes:
        for segment in route.segments:
            canvas.draw_path(segment)

    canvas.put_text(0, 0, expand_tabs(f"concept-map {model.map_id}: {model.title}"))
    canvas.put_text(
        0,
        1,
        f"component {component_index + 1}/{component_count} | "
        f"{len(scene.node_order)} concepts | {len(scene.edge_order)} relations",
    )
    for key in scene.node_order:
        rect = scene.rects[key]
        for row, line in enumerate(measured[key].lines, start=rect.y + 1):
            canvas.put_text(rect.x + 2, row, line)
    for route in scene.routes:
        relation = relations[route.edge.key]
        label = expand_tabs(_relation_text(relation), start=route.label_rect.x)
        canvas.put_text(route.label_rect.x, route.label_rect.y, label)
    for route in scene.routes:
        canvas.put_text(
            route.target_port[0],
            route.target_port[1],
            _ARROW_LEFT[theme],
            overwrite=True,
        )
    return canvas.to_text()


def _rect_data(rect: GraphRect) -> dict[str, int]:
    return {"x": rect.x, "y": rect.y, "width": rect.width, "height": rect.height}


def _metadata(
    model: ConceptMap,
    scene: DirectedScene,
    relations: Mapping[str, Relation],
    component: tuple[str, ...],
    component_index: int,
    component_count: int,
) -> dict[str, object]:
    members = set(component)
    source_nodes = [concept for concept in model.concepts if concept.concept_id in members]
    layer_by_node = {
        key: level for level, layer in enumerate(scene.layers) for key in layer
    }
    return {
        "map_id": model.map_id,
        "title": model.title,
        "component_index": component_index,
        "component_count": component_count,
        "component_policy": "complete-weak-component-indivisible",
        "source_node_order": [concept.concept_id for concept in source_nodes],
        "source_edge_order": list(scene.edge_order),
        "layout_node_order": list(scene.node_order),
        "tarjan_completion_order": [list(group) for group in scene.completion_order],
        "layers": [list(layer) for layer in scene.layers],
        "sccs": [
            {"id": group.key, "members": list(group.members)} for group in scene.sccs
        ],
        "condensation_edges": [
            {
                "from_scc": arc.source_scc,
                "to_scc": arc.target_scc,
                "edge_ids": list(arc.edge_keys),
            }
            for arc in scene.condensation
        ],
        "nodes": [
            {
                "id": concept.concept_id,
                "label": concept.label,
                "detail": concept.detail,
                "source_order": concept.order,
                "scc_id": scene.scc_by_node[concept.concept_id],
                "layer": layer_by_node[concept.concept_id],
                "rect": _rect_data(scene.rects[concept.concept_id]),
                "ports": [
                    {
                        "edge_id": port.edge_key,
                        "role": port.role,
                        "point": list(port.point),
                    }
                    for port in scene.ports[concept.concept_id]
                ],
            }
            for concept in source_nodes
        ],
        "edges": [
            {
                "id": relations[route.edge.key].edge_id,
                "from": relations[route.edge.key].source,
                "to": relations[route.edge.key].target,
                "relation": relations[route.edge.key].relation,
                "source_order": relations[route.edge.key].order,
                "kind": route.kind,
                "source_port": list(route.source_port),
                "target_port": list(route.target_port),
                "lane_x": route.lane_x,
                "label": {
                    "text": expand_tabs(
                        _relation_text(relations[route.edge.key]),
                        start=route.label_rect.x,
                    ),
                    "rect": _rect_data(route.label_rect),
                    "physical_span": route.label_rect.width,
                },
                "route_segments": [
                    [list(point) for point in segment] for segment in route.segments
                ],
                "painted_route_cells": [list(point) for point in route.cells],
            }
            for route in scene.routes
        ],
    }


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    model = _normalize(data)
    endpoint_counts = {concept.concept_id: 0 for concept in model.concepts}
    for edge in model.edges:
        endpoint_counts[edge.source] += 1
        endpoint_counts[edge.target] += 1
    measured_all = {
        concept.concept_id: _measure_concept(concept, endpoint_counts[concept.concept_id])
        for concept in model.concepts
    }
    layout_nodes = tuple(
        DirectedNode(
            concept.concept_id,
            measured_all[concept.concept_id].width,
            measured_all[concept.concept_id].height,
            concept.order,
        )
        for concept in model.concepts
    )
    layout_edges = tuple(
        DirectedEdge(edge.edge_id, edge.source, edge.target, edge.order)
        for edge in model.edges
    )
    components = weak_components(layout_nodes, layout_edges)
    if options.single_card and len(components) != 1:
        raise FitError(
            f"{len(components)} complete weak components require multiple cards"
        )

    cards: list[CardDraft] = []
    y = 0
    for index, component in enumerate(components):
        scene, measured, relations = _component_scene(
            model,
            component,
            index,
            len(components),
            options,
        )
        first = min(
            (concept for concept in model.concepts if concept.concept_id in set(component)),
            key=lambda concept: concept.order,
        )
        cards.append(
            CardDraft(
                f"concept-map-{model.map_id}-{first.concept_id}",
                _paint(
                    model,
                    scene,
                    measured,
                    relations,
                    index,
                    len(components),
                    options.theme,
                ),
                scene.width,
                scene.height,
                0,
                y,
                _metadata(
                    model,
                    scene,
                    relations,
                    component,
                    index,
                    len(components),
                ),
            )
        )
        y += scene.height + CARD_GAP
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


if __name__ == "__main__":
    raise SystemExit(run_renderer(RENDERER, render))
