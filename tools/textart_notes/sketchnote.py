#!/usr/bin/env python3
"""Render clustered, icon-assisted visual notes as text-art cards."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.canvas import Canvas
from tools.textart_notes.core.cell_width import expand_tabs, text_width
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import (
    CardDraft,
    FitError,
    InputError,
    RenderOptions,
    RenderResult,
)
from tools.textart_notes.core.router import shortest_grid_route, validate_cell_route
from tools.textart_notes.core.schema import (
    array_value,
    check_keys,
    object_value,
    string_value,
)
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_clusters
from tools.textart_notes.layouts.cluster import ClusterItem, ClusterSize, pack_shelves


RENDERER = "sketchnote"
BLOCK_TEXT_LIMIT = 24
MAX_RELATIONS = 4
MAX_RELATIONS_PER_GROUP = 2
CARD_GAP = 2
MINIMUM_WIDTH = 22
_STYLE_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")

ICON_PATTERNS: dict[str, tuple[str, str, str]] = {
    "idea": (" .-. ", "( * )", " '-' "),
    "person": ("  o  ", " /|\\ ", " / \\ "),
    "action": ("-->  ", " GO! ", "---> "),
    "warning": (" /!\\ ", "/___\\", "  !  "),
    "question": (" ___ ", "  /  ", "  ?  "),
    "note": ("+---+", "|:::|", "+---+"),
}

_SOURCE_MARK = {"ascii": "o", "unicode-light": "○", "unicode-rich": "●"}


@dataclass(frozen=True)
class Block:
    block_id: str
    keyword: str
    body: str
    icon: str
    importance: str
    order: int


@dataclass(frozen=True)
class Group:
    group_id: str
    title: str
    blocks: tuple[Block, ...]
    order: int


@dataclass(frozen=True)
class Relation:
    relation_id: str
    source: str
    target: str
    label: str | None
    order: int


@dataclass(frozen=True)
class SketchDocument:
    document_id: str
    title: str
    groups: tuple[Group, ...]
    relations: tuple[Relation, ...]


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def cells(self) -> frozenset[tuple[int, int]]:
        return frozenset(
            (x, y)
            for y in range(self.y, self.bottom)
            for x in range(self.x, self.right)
        )

    def translated(self, dy: int) -> "Rect":
        return Rect(self.x, self.y + dy, self.width, self.height)


@dataclass(frozen=True)
class BlockMeasure:
    width: int
    height: int
    text_width: int
    keyword_lines: tuple[str, ...]
    body_lines: tuple[str, ...]
    padding_rows: int


@dataclass(frozen=True)
class BlockGeometry:
    block: Block
    rect: Rect
    measure: BlockMeasure

    def translated(self, dy: int) -> "BlockGeometry":
        return BlockGeometry(self.block, self.rect.translated(dy), self.measure)


@dataclass(frozen=True)
class LabelGeometry:
    relation_id: str
    rect: Rect
    text: str

    def translated(self, dy: int) -> "LabelGeometry":
        return LabelGeometry(self.relation_id, self.rect.translated(dy), self.text)


@dataclass(frozen=True)
class RouteGeometry:
    relation: Relation
    path: tuple[tuple[int, int], ...]
    label: LabelGeometry

    def translated(self, dy: int) -> "RouteGeometry":
        return RouteGeometry(
            self.relation,
            tuple((x, y + dy) for x, y in self.path),
            self.label.translated(dy),
        )


@dataclass(frozen=True)
class GroupGeometry:
    group: Group
    blocks: tuple[BlockGeometry, ...]
    rect: Rect
    context_lines: tuple[str, ...]
    part_line: str
    separator_y: int
    routes: tuple[RouteGeometry, ...]
    part_index: int
    part_total: int

    def translated(self, dy: int) -> "GroupGeometry":
        return GroupGeometry(
            self.group,
            tuple(block.translated(dy) for block in self.blocks),
            self.rect.translated(dy),
            self.context_lines,
            self.part_line,
            self.separator_y + dy,
            tuple(route.translated(dy) for route in self.routes),
            self.part_index,
            self.part_total,
        )


@dataclass(frozen=True)
class SegmentPlan:
    group: Group
    blocks: tuple[Block, ...]
    geometry: GroupGeometry


@dataclass(frozen=True)
class CardPlan:
    segments: tuple[SegmentPlan, ...]
    geometries: tuple[GroupGeometry, ...]
    height: int


def _visible(value: object, path: str, *, single_line: bool = False) -> str:
    result = string_value(
        value,
        path,
        single_line=single_line,
        allow_tabs=True,
    )
    if not any(not character.isspace() for character in result):
        raise InputError(f"{path} must contain visible text")
    return result


def _stable_id(value: object, path: str) -> str:
    identifier = string_value(
        value,
        path,
        single_line=True,
        allow_tabs=False,
    )
    if len(identifier) > 48 or not _STYLE_ID.fullmatch(identifier):
        raise InputError(
            f"{path} must be a stable lowercase ASCII slug beginning with a letter "
            "and containing at most 48 characters"
        )
    return identifier


def _normalize(data: dict[str, object]) -> SketchDocument:
    root = object_value(data, "input")
    check_keys(
        root,
        "input",
        required={"id", "title", "groups"},
        allowed={"id", "title", "groups", "relations"},
    )
    document_id = _stable_id(root["id"], "id")
    title = _visible(root["title"], "title")
    raw_groups = array_value(root["groups"], "groups")
    if not raw_groups:
        raise InputError("groups must be a non-empty array")

    seen = {document_id}
    groups: list[Group] = []
    block_to_group: dict[str, str] = {}
    for group_index, value in enumerate(raw_groups):
        path = f"groups[{group_index}]"
        record = object_value(value, path)
        check_keys(
            record,
            path,
            required={"id", "title", "blocks"},
            allowed={"id", "title", "blocks"},
        )
        group_id = _stable_id(record["id"], f"{path}.id")
        if group_id in seen:
            raise InputError(f"duplicate global id {group_id!r}")
        seen.add(group_id)
        raw_blocks = array_value(record["blocks"], f"{path}.blocks")
        if not raw_blocks:
            raise InputError(f"{path}.blocks must be a non-empty array")
        blocks: list[Block] = []
        for block_index, raw_block in enumerate(raw_blocks):
            block_path = f"{path}.blocks[{block_index}]"
            block_record = object_value(raw_block, block_path)
            check_keys(
                block_record,
                block_path,
                required={"id", "keyword", "body", "icon", "importance"},
                allowed={"id", "keyword", "body", "icon", "importance"},
            )
            block_id = _stable_id(block_record["id"], f"{block_path}.id")
            if block_id in seen:
                raise InputError(f"duplicate global id {block_id!r}")
            seen.add(block_id)
            icon = block_record["icon"]
            if not isinstance(icon, str) or icon not in ICON_PATTERNS:
                raise InputError(
                    f"{block_path}.icon must be one of: {', '.join(ICON_PATTERNS)}"
                )
            importance = block_record["importance"]
            if not isinstance(importance, str) or importance not in {
                "normal",
                "high",
                "critical",
            }:
                raise InputError(f"{block_path}.importance is invalid")
            blocks.append(
                Block(
                    block_id,
                    _visible(block_record["keyword"], f"{block_path}.keyword"),
                    _visible(block_record["body"], f"{block_path}.body"),
                    icon,
                    importance,
                    block_index,
                )
            )
            block_to_group[block_id] = group_id
        groups.append(
            Group(
                group_id,
                _visible(record["title"], f"{path}.title"),
                tuple(blocks),
                group_index,
            )
        )

    raw_relations = array_value(root.get("relations", []), "relations")
    if len(raw_relations) > MAX_RELATIONS:
        raise InputError(f"relations may contain at most {MAX_RELATIONS} entries")
    references: set[tuple[str, str]] = set()
    per_group: dict[str, int] = {}
    relations: list[Relation] = []
    for index, value in enumerate(raw_relations):
        path = f"relations[{index}]"
        record = object_value(value, path)
        check_keys(
            record,
            path,
            required={"id", "source", "target"},
            allowed={"id", "source", "target", "label"},
        )
        relation_id = _stable_id(record["id"], f"{path}.id")
        if relation_id in seen:
            raise InputError(f"duplicate global id {relation_id!r}")
        seen.add(relation_id)
        source = _stable_id(record["source"], f"{path}.source")
        target = _stable_id(record["target"], f"{path}.target")
        if source not in block_to_group or target not in block_to_group:
            raise InputError(f"{path} references an unknown block")
        if source == target:
            raise InputError(f"{path} cannot be a self relation")
        reference = (source, target)
        if reference in references:
            raise InputError(f"duplicate directed reference {source!r}->{target!r}")
        references.add(reference)
        label = None
        if record.get("label") is not None:
            label = _visible(record["label"], f"{path}.label", single_line=True)
        source_group = block_to_group[source]
        target_group = block_to_group[target]
        if source_group == target_group:
            per_group[source_group] = per_group.get(source_group, 0) + 1
            if per_group[source_group] > MAX_RELATIONS_PER_GROUP:
                raise InputError(
                    f"group {source_group!r} may contain at most "
                    f"{MAX_RELATIONS_PER_GROUP} relations"
                )
        relations.append(Relation(relation_id, source, target, label, index))
    return SketchDocument(document_id, title, tuple(groups), tuple(relations))


def _wrap_multiline(text: str, width: int, *, start_column: int) -> tuple[str, ...]:
    try:
        return tuple(
            line
            for logical in text.split("\n")
            for line in wrap_clusters(logical, width, start_column=start_column)
        )
    except ValueError as error:
        raise FitError(str(error)) from error


def _measure_block(block: Block, x: int) -> BlockMeasure:
    text_x = x + 8
    keyword = f"[{block.block_id}] {block.keyword}"
    logical = keyword.split("\n") + block.body.split("\n")
    natural = max(text_width(line, start=text_x) for line in logical)
    content_width = min(BLOCK_TEXT_LIMIT, max(8, natural))
    keyword_lines = _wrap_multiline(keyword, content_width, start_column=text_x)
    body_lines = _wrap_multiline(block.body, content_width, start_column=text_x)
    padding = {"normal": 0, "high": 1, "critical": 2}[block.importance]
    text_rows = len(keyword_lines) + 1 + len(body_lines)
    return BlockMeasure(
        content_width + 10,
        2 + max(3, text_rows) + padding,
        content_width,
        keyword_lines,
        body_lines,
        padding,
    )


def _label_token(relation: Relation) -> str:
    suffix = f": {relation.label}" if relation.label is not None else ""
    return "{" + relation.relation_id + suffix + "}"


def _ports(rect: Rect, target: Rect) -> tuple[tuple[int, int], ...]:
    values = {
        "left": (rect.x, rect.y + rect.height // 2),
        "right": (rect.right - 1, rect.y + rect.height // 2),
        "top": (rect.x + rect.width // 2, rect.y),
        "bottom": (rect.x + rect.width // 2, rect.bottom - 1),
    }
    delta_x = (target.x + target.width // 2) - (rect.x + rect.width // 2)
    delta_y = (target.y + target.height // 2) - (rect.y + rect.height // 2)
    horizontal = "right" if delta_x >= 0 else "left"
    vertical = "bottom" if delta_y >= 0 else "top"
    return (
        values[horizontal],
        values[vertical],
        values["top" if vertical == "bottom" else "bottom"],
        values["left" if horizontal == "right" else "right"],
    )


def _bends(path: Sequence[tuple[int, int]]) -> int:
    directions = [
        (second[0] - first[0], second[1] - first[1])
        for first, second in zip(path, path[1:])
    ]
    return sum(first != second for first, second in zip(directions, directions[1:]))


def _route_relation(
    relation: Relation,
    block_by_id: Mapping[str, BlockGeometry],
    *,
    width: int,
    height: int,
    minimum_y: int,
    maximum_y: int,
    label: LabelGeometry,
    reserved: set[tuple[int, int]],
) -> RouteGeometry:
    source = block_by_id[relation.source].rect
    target = block_by_id[relation.target].rect
    block_cells = set().union(*(geometry.rect.cells() for geometry in block_by_id.values()))
    boundary = {
        (x, y)
        for y in range(height)
        for x in range(width)
        if x in {0, width - 1} or y < minimum_y or y > maximum_y
    }
    hard = set(label.rect.cells()) | reserved | boundary
    candidates: list[
        tuple[int, int, int, int, tuple[tuple[int, int], ...]]
    ] = []
    for source_rank, start in enumerate(_ports(source, target)):
        for target_rank, end in enumerate(_ports(target, source)):
            if start in hard or end in hard:
                continue
            blocked = (block_cells - {start, end}) | hard
            try:
                path = shortest_grid_route(
                    start,
                    end,
                    width=width,
                    height=height,
                    blocked=blocked,
                )
            except ValueError:
                continue
            candidates.append(
                (len(path), _bends(path), source_rank, target_rank, path)
            )
    if not candidates:
        raise FitError(f"relation {relation.relation_id!r} has no collision-free route")
    path = min(candidates)[-1]
    validate_cell_route(path, start=path[0], end=path[-1])
    return RouteGeometry(relation, path, label)


def _layout_group(
    group: Group,
    blocks: tuple[Block, ...],
    relations: tuple[Relation, ...],
    *,
    max_width: int,
    part_index: int,
    part_total: int,
    route_edges: bool,
) -> GroupGeometry:
    if max_width < MINIMUM_WIDTH:
        raise FitError(
            f"sketchnote requires at least {MINIMUM_WIDTH} cells of width"
        )
    if part_total > 9999:
        raise FitError("a group requires more than 9999 segments")
    context = f"[{group.group_id}] {group.title}"
    context_lines = _wrap_multiline(context, max_width - 4, start_column=2)
    part_line = f"part {part_index:04d}/{part_total:04d}"
    if text_width(part_line, start=2) > max_width - 4:
        raise FitError("card is too narrow for repeated group context")
    separator_y = 1 + len(context_lines) + 1
    block_origin_y = separator_y + 2

    items = tuple(
        ClusterItem(
            block.block_id,
            tuple(
                ClusterSize(
                    _measure_block(block, phase).width,
                    _measure_block(block, phase).height,
                )
                for phase in range(4)
            ),
        )
        for block in blocks
    )
    packed = pack_shelves(
        items,
        max_width=max_width - 4,
        origin_x=2,
        origin_y=block_origin_y,
        gutter_x=3,
        gutter_y=2,
    )
    block_by_id = {block.block_id: block for block in blocks}
    geometries = tuple(
        BlockGeometry(
            block_by_id[placement.key],
            Rect(
                placement.x,
                placement.y,
                placement.width,
                placement.height,
            ),
            _measure_block(block_by_id[placement.key], placement.x),
        )
        for placement in packed.placements
    )
    content_bottom = max(geometry.rect.bottom for geometry in geometries)
    labels: list[LabelGeometry] = []
    for index, relation in enumerate(relations):
        row = content_bottom + 1 + index * 2
        text = expand_tabs(_label_token(relation), start=2)
        width = text_width(text, start=2)
        if 2 + width > max_width - 2:
            raise FitError(f"relation label {relation.relation_id!r} is too wide")
        labels.append(LabelGeometry(relation.relation_id, Rect(2, row, width, 1), text))
    bottom_y = content_bottom + 1 + 2 * len(relations)
    rect = Rect(0, 0, max_width, bottom_y + 1)

    routes: list[RouteGeometry] = []
    if route_edges:
        geometry_by_id = {geometry.block.block_id: geometry for geometry in geometries}
        all_labels = set().union(*(label.rect.cells() for label in labels)) if labels else set()
        used: set[tuple[int, int]] = set()
        for relation, label in zip(relations, labels):
            other_labels = all_labels - set(label.rect.cells())
            route = _route_relation(
                relation,
                geometry_by_id,
                width=max_width,
                height=rect.height,
                minimum_y=separator_y + 1,
                maximum_y=bottom_y - 1,
                label=label,
                reserved=used | other_labels,
            )
            routes.append(route)
            used.update(route.path)
    return GroupGeometry(
        group,
        geometries,
        rect,
        context_lines,
        part_line,
        separator_y,
        tuple(routes),
        part_index,
        part_total,
    )


def _relations_within(
    blocks: Sequence[Block], relations: Sequence[Relation]
) -> tuple[Relation, ...]:
    identifiers = {block.block_id for block in blocks}
    return tuple(
        relation
        for relation in relations
        if relation.source in identifiers and relation.target in identifiers
    )


def _split_group(
    group: Group,
    relations: tuple[Relation, ...],
    *,
    max_width: int,
    available_height: int,
) -> tuple[SegmentPlan, ...]:
    preview = _layout_group(
        group,
        group.blocks,
        relations,
        max_width=max_width,
        part_index=1,
        part_total=1,
        route_edges=False,
    )
    if preview.rect.height <= available_height:
        geometry = _layout_group(
            group,
            group.blocks,
            relations,
            max_width=max_width,
            part_index=1,
            part_total=1,
            route_edges=True,
        )
        return (SegmentPlan(group, group.blocks, geometry),)

    partitions: list[tuple[Block, ...]] = []
    current: list[Block] = []
    for block in group.blocks:
        candidate = tuple(current + [block])
        geometry = _layout_group(
            group,
            candidate,
            _relations_within(candidate, relations),
            max_width=max_width,
            part_index=1,
            part_total=1,
            route_edges=False,
        )
        if geometry.rect.height <= available_height:
            current.append(block)
            continue
        if not current:
            raise FitError(f"block {block.block_id!r} is taller than an empty card")
        partitions.append(tuple(current))
        current = [block]
        single = _layout_group(
            group,
            tuple(current),
            (),
            max_width=max_width,
            part_index=1,
            part_total=1,
            route_edges=False,
        )
        if single.rect.height > available_height:
            raise FitError(f"block {block.block_id!r} is taller than an empty card")
    partitions.append(tuple(current))
    total = len(partitions)
    return tuple(
        SegmentPlan(
            group,
            partition,
            _layout_group(
                group,
                partition,
                _relations_within(partition, relations),
                max_width=max_width,
                part_index=index,
                part_total=total,
                route_edges=True,
            ),
        )
        for index, partition in enumerate(partitions, 1)
    )


def _plan_cards(
    document: SketchDocument, options: RenderOptions
) -> tuple[tuple[str, ...], tuple[CardPlan, ...]]:
    header = _wrap_multiline(
        f"[{document.document_id}] {document.title}",
        options.max_width,
        start_column=0,
    )
    group_start_y = len(header) + 1
    available_height = options.max_height - group_start_y
    if available_height < 1:
        raise FitError("document header leaves no room for a group")
    block_to_group = {
        block.block_id: group.group_id
        for group in document.groups
        for block in group.blocks
    }
    cross_group = [
        relation.relation_id
        for relation in document.relations
        if block_to_group[relation.source] != block_to_group[relation.target]
    ]
    if cross_group:
        raise FitError("cross-group relations are unsupported: " + ", ".join(cross_group))

    all_segments: list[tuple[SegmentPlan, ...]] = []
    for group in document.groups:
        relations = tuple(
            relation
            for relation in document.relations
            if block_to_group[relation.source] == group.group_id
        )
        all_segments.append(
            _split_group(
                group,
                relations,
                max_width=options.max_width,
                available_height=available_height,
            )
        )

    card_segments: list[list[SegmentPlan]] = []
    current: list[SegmentPlan] = []
    used_height = group_start_y

    def flush() -> None:
        nonlocal current, used_height
        if current:
            card_segments.append(current)
        current = []
        used_height = group_start_y

    for segments in all_segments:
        if len(segments) > 1:
            flush()
            card_segments.extend([segment] for segment in segments)
            continue
        segment = segments[0]
        gutter = 1 if current else 0
        if used_height + gutter + segment.geometry.rect.height > options.max_height:
            flush()
            gutter = 0
        if used_height + segment.geometry.rect.height > options.max_height:
            raise FitError(f"group {segment.group.group_id!r} cannot fit an empty card")
        current.append(segment)
        used_height += gutter + segment.geometry.rect.height
    flush()
    if options.single_card and len(card_segments) != 1:
        raise FitError("--single-card forbids the required semantic split")

    plans: list[CardPlan] = []
    for segments in card_segments:
        y = group_start_y
        geometries: list[GroupGeometry] = []
        for index, segment in enumerate(segments):
            if index:
                y += 1
            geometries.append(segment.geometry.translated(y))
            y += segment.geometry.rect.height
        plans.append(CardPlan(tuple(segments), tuple(geometries), y))
    return header, tuple(plans)


def _route_arrow(path: Sequence[tuple[int, int]]) -> str:
    prior = path[-2]
    current = path[-1]
    return {
        (1, 0): ">",
        (-1, 0): "<",
        (0, 1): "v",
        (0, -1): "^",
    }[(current[0] - prior[0], current[1] - prior[1])]


def _paint_group(canvas: Canvas, geometry: GroupGeometry, theme: str) -> None:
    rect = geometry.rect
    canvas.draw_box(rect.x, rect.y, rect.width, rect.height)
    canvas.draw_path(
        ((rect.x, geometry.separator_y), (rect.right - 1, geometry.separator_y))
    )
    for block in geometry.blocks:
        canvas.draw_box(block.rect.x, block.rect.y, block.rect.width, block.rect.height)
    for route in geometry.routes:
        canvas.draw_path(route.path)

    y = rect.y + 1
    for line in geometry.context_lines:
        canvas.put_text(rect.x + 2, y, line)
        y += 1
    canvas.put_text(rect.x + 2, y, geometry.part_line)
    for geometry_block in geometry.blocks:
        block = geometry_block.block
        marker = {"normal": None, "high": "*", "critical": "!"}[block.importance]
        if marker is not None:
            canvas.put_text(geometry_block.rect.x + 1, geometry_block.rect.y + 1, marker)
        for row, icon_line in enumerate(ICON_PATTERNS[block.icon]):
            canvas.put_text(
                geometry_block.rect.x + 2,
                geometry_block.rect.y + 1 + row,
                icon_line,
            )
        text_x = geometry_block.rect.x + 8
        text_y = geometry_block.rect.y + 1
        for line in geometry_block.measure.keyword_lines:
            canvas.put_text(text_x, text_y, line)
            text_y += 1
        text_y += 1
        for line in geometry_block.measure.body_lines:
            canvas.put_text(text_x, text_y, line)
            text_y += 1
    for route in geometry.routes:
        canvas.put_text(route.label.rect.x, route.label.rect.y, route.label.text)
    for route in geometry.routes:
        canvas.put_text(
            route.path[0][0],
            route.path[0][1],
            _SOURCE_MARK[theme],
            overwrite=True,
        )
        canvas.put_text(
            route.path[-1][0],
            route.path[-1][1],
            _route_arrow(route.path),
            overwrite=True,
        )


def _rect_data(rect: Rect) -> dict[str, int]:
    return {"x": rect.x, "y": rect.y, "width": rect.width, "height": rect.height}


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    document = _normalize(data)
    header, plans = _plan_cards(document, options)
    card_ids = tuple(
        f"{document.document_id}-sketch-{index:03d}" for index in range(len(plans))
    )
    block_card: dict[str, str] = {}
    for card_id, plan in zip(card_ids, plans):
        for segment in plan.segments:
            for block in segment.blocks:
                block_card[block.block_id] = card_id

    cards: list[CardDraft] = []
    card_y = 0
    for card_index, (card_id, plan) in enumerate(zip(card_ids, plans)):
        canvas = Canvas(options.max_width, plan.height, options.theme)
        for row, line in enumerate(header):
            canvas.put_text(0, row, line)
        for geometry in plan.geometries:
            _paint_group(canvas, geometry, options.theme)

        groups_metadata = [
            {
                "id": geometry.group.group_id,
                "part": geometry.part_index,
                "parts": geometry.part_total,
                "rect": _rect_data(geometry.rect),
                "blocks": [
                    {
                        "id": block.block.block_id,
                        "order": block.block.order,
                        "icon": block.block.icon,
                        "importance": block.block.importance,
                        "rect": _rect_data(block.rect),
                    }
                    for block in geometry.blocks
                ],
            }
            for geometry in plan.geometries
        ]
        card_routes = sorted(
            (
                route
                for geometry in plan.geometries
                for route in geometry.routes
            ),
            key=lambda route: route.relation.order,
        )
        routes_metadata = [
            {
                "id": route.relation.relation_id,
                "order": route.relation.order,
                "source": route.relation.source,
                "target": route.relation.target,
                "label": route.relation.label,
                "path": [list(point) for point in route.path],
                "label_rect": _rect_data(route.label.rect),
                "label_text": route.label.text,
            }
            for route in card_routes
        ]
        continuations: list[dict[str, object]] = []
        for relation in document.relations:
            source_card = block_card[relation.source]
            target_card = block_card[relation.target]
            if source_card == target_card:
                continue
            if card_id == source_card:
                role = "source"
            elif card_id == target_card:
                role = "target"
            else:
                continue
            continuations.append(
                {
                    "id": relation.relation_id,
                    "order": relation.order,
                    "source": relation.source,
                    "target": relation.target,
                    "label": relation.label,
                    "source_card": source_card,
                    "target_card": target_card,
                    "role": role,
                }
            )
        cards.append(
            CardDraft(
                card_id,
                canvas.to_text(),
                options.max_width,
                plan.height,
                0,
                card_y,
                {
                    "document_id": document.document_id,
                    "card_index": card_index,
                    "groups": groups_metadata,
                    "routes": routes_metadata,
                    "continuations": continuations,
                },
            )
        )
        card_y += plan.height + CARD_GAP
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


if __name__ == "__main__":
    raise SystemExit(run_renderer(RENDERER, render))
