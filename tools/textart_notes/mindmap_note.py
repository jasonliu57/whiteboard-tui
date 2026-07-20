#!/usr/bin/env python3
"""Render a strict rooted tree as deterministic radial mind-map cards."""

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
from tools.textart_notes.core.schema import array_value, check_keys, object_value, slug_value, string_value
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.layouts.hierarchy import HierarchyFacts, analyze_hierarchy
from tools.textart_notes.layouts.radial import RadialScene, RadialSize, layout_radial


RENDERER = "mindmap-note"
MAX_NODES = 512
MAX_DEPTH = 64
MAX_TEXT_CELLS = 60
CARD_GAP = 2


@dataclass(frozen=True)
class Node:
    node_id: str
    label: str
    detail: str | None
    children: tuple[str, ...]


@dataclass(frozen=True)
class MindMap:
    root_id: str
    nodes: Mapping[str, Node]
    order: tuple[str, ...]
    facts: HierarchyFacts


@dataclass(frozen=True)
class Plan:
    anchor_id: str
    breadcrumb: tuple[str, ...]
    role: str
    summary_children: tuple[str, ...] | None
    scene: RadialScene
    fragment_index: int = 0
    fragment_count: int = 1


def _text(value: object, path: str) -> str:
    result = string_value(value, path, single_line=True, allow_tabs=True)
    if not any(not character.isspace() for character in result):
        raise InputError(f"{path} must contain visible text")
    if max(text_width(result, start=phase) for phase in range(4)) > MAX_TEXT_CELLS:
        raise InputError(f"{path} exceeds {MAX_TEXT_CELLS} terminal cells")
    return result


def _normalize(data: dict[str, object]) -> MindMap:
    root = object_value(data, "input")
    check_keys(root, "input", required={"root_id", "nodes"}, allowed={"root_id", "nodes"})
    root_id = slug_value(root["root_id"], "root_id", max_length=64)
    values = array_value(root["nodes"], "nodes")
    if not 1 <= len(values) <= MAX_NODES:
        raise InputError(f"nodes must contain 1..{MAX_NODES} entries")
    nodes: dict[str, Node] = {}
    order: list[str] = []
    for index, value in enumerate(values):
        path = f"nodes[{index}]"
        record = object_value(value, path)
        check_keys(
            record,
            path,
            required={"id", "label", "children"},
            allowed={"id", "label", "children", "detail"},
        )
        node_id = slug_value(record["id"], f"{path}.id", max_length=64)
        if node_id in nodes:
            raise InputError(f"duplicate node id {node_id!r}")
        children = tuple(
            slug_value(child, f"{path}.children[{child_index}]", max_length=64)
            for child_index, child in enumerate(array_value(record["children"], f"{path}.children"))
        )
        detail = _text(record["detail"], f"{path}.detail") if "detail" in record else None
        nodes[node_id] = Node(node_id, _text(record["label"], f"{path}.label"), detail, children)
        order.append(node_id)
    facts = analyze_hierarchy(
        root_id,
        order,
        {key: node.children for key, node in nodes.items()},
        max_depth=MAX_DEPTH,
    )
    return MindMap(root_id, nodes, tuple(order), facts)


def _lines(node: Node) -> tuple[str, ...]:
    heading = f"[{node.node_id}] {node.label}"
    return (heading,) if node.detail is None else (heading, node.detail)


def _sizes(model: MindMap) -> dict[str, RadialSize]:
    return {
        key: RadialSize(
            max(text_width(line, start=phase) for line in _lines(node) for phase in range(4)) + 2,
            len(_lines(node)) + 2,
        )
        for key, node in model.nodes.items()
    }


def _scene(
    model: MindMap,
    sizes: Mapping[str, RadialSize],
    anchor: str,
    summary: Sequence[str] | None = None,
) -> RadialScene:
    try:
        return layout_radial(
            model.facts,
            {key: node.children for key, node in model.nodes.items()},
            sizes,
            anchor_id=anchor,
            summary_children=summary,
        )
    except ValueError as error:
        raise FitError(f"radial layout failed: {error}") from error


def _fits(scene: RadialScene, options: RenderOptions) -> bool:
    return scene.width <= options.max_width and scene.height <= options.max_height


def _breadcrumb(model: MindMap, node_id: str) -> tuple[str, ...]:
    result: list[str] = []
    current: str | None = node_id
    while current is not None:
        result.append(current)
        current = model.facts.parent[current]
    return tuple(reversed(result))


def _paginate(model: MindMap, sizes: Mapping[str, RadialSize], options: RenderOptions) -> list[Plan]:
    plans: list[Plan] = []

    def visit(anchor: str) -> None:
        complete = _scene(model, sizes, anchor)
        if _fits(complete, options):
            plans.append(Plan(anchor, _breadcrumb(model, anchor), "complete" if anchor == model.root_id else "branch-complete", None, complete))
            return
        anchor_only = _scene(model, sizes, anchor, ())
        if not _fits(anchor_only, options):
            raise FitError(f"indivisible node {anchor!r} cannot fit {options.max_width}x{options.max_height}")
        children = model.nodes[anchor].children
        if not children:
            raise FitError(f"leaf node {anchor!r} cannot fit")
        groups: list[tuple[str, ...]] = []
        current: list[str] = []
        unpaired: set[str] = set()
        for child in children:
            candidate = tuple(current + [child])
            if _fits(_scene(model, sizes, anchor, candidate), options):
                current.append(child)
                continue
            if current:
                groups.append(tuple(current))
                current = []
            if _fits(_scene(model, sizes, anchor, (child,)), options):
                current = [child]
            else:
                unpaired.add(child)
        if current:
            groups.append(tuple(current))
        if not groups:
            groups.append(())
        included_leaf_ids: set[str] = set()
        for index, group in enumerate(groups):
            plans.append(
                Plan(
                    anchor,
                    _breadcrumb(model, anchor),
                    "overview",
                    group,
                    _scene(model, sizes, anchor, group),
                    index,
                    len(groups),
                )
            )
            included_leaf_ids.update(child for child in group if not model.nodes[child].children)
        for child in children:
            if model.nodes[child].children or child in unpaired or child not in included_leaf_ids:
                visit(child)

    visit(model.root_id)
    return plans


def _paint(model: MindMap, scene: RadialScene, theme: str) -> str:
    canvas = Canvas(scene.width, scene.height, theme)
    for edge in scene.edges:
        canvas.draw_path(edge.vertices)
    by_id = {item.key: item for item in scene.placements}
    for key in model.facts.preorder:
        if key not in by_id:
            continue
        placed = by_id[key]
        canvas.draw_box(placed.x, placed.y, placed.width, placed.height)
        for row, line in enumerate(_lines(model.nodes[key]), start=placed.y + 1):
            canvas.put_text(placed.x + 1, row, line)
    return canvas.to_text()


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    model = _normalize(data)
    sizes = _sizes(model)
    full = _scene(model, sizes, model.root_id)
    if _fits(full, options):
        plans = [Plan(model.root_id, (model.root_id,), "complete", None, full)]
    elif options.single_card:
        raise FitError(f"mind map requires subtree splitting; natural size is {full.width}x{full.height}")
    else:
        plans = _paginate(model, sizes, options)

    card_ids = tuple(f"mindmap-{index:03d}" for index in range(len(plans)))
    owned_by_plan: list[list[str]] = []
    owner: dict[str, str] = {}
    for index, plan in enumerate(plans):
        if plan.summary_children is None:
            owned = list(model.facts.subtree_ids[plan.anchor_id])
        else:
            owned = ([plan.anchor_id] if plan.fragment_index == 0 else []) + [
                child for child in plan.summary_children if not model.nodes[child].children
            ]
        owned_by_plan.append(owned)
        for node_id in owned:
            if node_id in owner:
                raise AssertionError(f"node {node_id!r} has multiple owning cards")
            owner[node_id] = card_ids[index]
    if set(owner) != set(model.nodes):
        raise AssertionError("mind-map pagination lost node ownership")

    cards: list[CardDraft] = []
    y = 0
    for index, plan in enumerate(plans):
        visible = [item.key for item in plan.scene.placements]
        owned = owned_by_plan[index]
        delegated = (
            [child for child in model.nodes[plan.anchor_id].children if owner[child] != card_ids[index]]
            if plan.summary_children is not None
            else []
        )
        child_cards: list[str] = []
        for child in delegated:
            if owner[child] not in child_cards:
                child_cards.append(owner[child])
        parent_id = model.facts.parent[plan.anchor_id]
        text = _paint(model, plan.scene, options.theme)
        cards.append(
            CardDraft(
                card_ids[index],
                text,
                plan.scene.width,
                plan.scene.height,
                0,
                y,
                {
                    "root_id": model.root_id,
                    "anchor_id": plan.anchor_id,
                    "breadcrumb_ids": list(plan.breadcrumb),
                    "role": plan.role,
                    "fragment_index": plan.fragment_index,
                    "fragment_count": plan.fragment_count,
                    "visible_node_ids": visible,
                    "owned_node_ids": owned,
                    "context_node_ids": [key for key in visible if key not in owned],
                    "source_subtree_node_ids": list(model.facts.subtree_ids[plan.anchor_id]),
                    "delegated_subtree_ids": delegated,
                    "parent_card_id": None if parent_id is None else owner[parent_id],
                    "child_card_ids": child_cards,
                    "counterpart_card_ids": [card_id for card_id in card_ids if card_id != card_ids[index]],
                    "top_level_sides": dict(plan.scene.top_level_sides),
                    "node_rects": {
                        item.key: {"x": item.x, "y": item.y, "width": item.width, "height": item.height, "depth": item.depth, "side": item.side}
                        for item in plan.scene.placements
                    },
                    "edges": [
                        {"from": edge.parent, "to": edge.child, "cells": [list(cell) for cell in edge.cells]}
                        for edge in plan.scene.edges
                    ],
                },
            )
        )
        y += plan.scene.height + CARD_GAP
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


if __name__ == "__main__":
    raise SystemExit(run_renderer(RENDERER, render))
