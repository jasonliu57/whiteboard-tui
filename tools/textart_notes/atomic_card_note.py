#!/usr/bin/env python3
"""Render one immutable text-art card for every atomic concept."""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.boxes import frame_row, frame_rule
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import array_value, check_keys, object_value, slug_value, string_value
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_line
from tools.textart_notes.layouts.grid import ShelfItem, pack_row_major


RENDERER = "atomic-card-note"
PREFERRED_WIDTH = 56
MIN_WIDTH = 20
PACK_COLUMNS = 3
GUTTER_X = 4
GUTTER_Y = 2


@dataclass(frozen=True)
class Reference:
    reference_id: str
    kind: str
    label: str | None


@dataclass(frozen=True)
class Source:
    source_id: str
    citation: str
    locator: str | None


@dataclass(frozen=True)
class Concept:
    concept_id: str
    title: str
    body: str
    tags: tuple[str, ...]
    references: tuple[Reference, ...]
    source: Source | None


@dataclass(frozen=True)
class Collection:
    title: str
    concepts: tuple[Concept, ...]


def _optional_text(record: dict[str, object], key: str, path: str) -> str | None:
    return string_value(record[key], path, single_line=True) if key in record else None


def _normalize(data: dict[str, object]) -> Collection:
    root = object_value(data, "input")
    check_keys(root, "input", required={"collection_title", "concepts"}, allowed={"collection_title", "concepts"})
    values = array_value(root["concepts"], "concepts")
    if not values:
        raise InputError("concepts must not be empty")
    concepts: list[Concept] = []
    concept_ids: set[str] = set()
    for index, value in enumerate(values):
        path = f"concepts[{index}]"
        record = object_value(value, path)
        required = {"id", "title", "body", "tags", "references"}
        check_keys(record, path, required=required, allowed=required | {"source"})
        concept_id = slug_value(record["id"], f"{path}.id", max_length=64)
        if concept_id in concept_ids:
            raise InputError(f"duplicate concept id {concept_id!r}")
        concept_ids.add(concept_id)

        tags: list[str] = []
        for tag_index, tag_value in enumerate(array_value(record["tags"], f"{path}.tags")):
            tag = string_value(tag_value, f"{path}.tags[{tag_index}]", single_line=True)
            if tag in tags:
                raise InputError(f"{path}.tags duplicates {tag!r}")
            tags.append(tag)

        references: list[Reference] = []
        reference_keys: set[tuple[str, str]] = set()
        for reference_index, reference_value in enumerate(array_value(record["references"], f"{path}.references")):
            reference_path = f"{path}.references[{reference_index}]"
            reference = object_value(reference_value, reference_path)
            check_keys(reference, reference_path, required={"id", "kind"}, allowed={"id", "kind", "label"})
            reference_id = slug_value(reference["id"], f"{reference_path}.id", max_length=80)
            kind = reference["kind"]
            if kind not in {"internal", "external"}:
                raise InputError(f"{reference_path}.kind must be internal or external")
            key = (str(kind), reference_id)
            if key in reference_keys:
                raise InputError(f"{path}.references duplicates {kind} {reference_id!r}")
            reference_keys.add(key)
            references.append(Reference(reference_id, str(kind), _optional_text(reference, "label", f"{reference_path}.label")))

        source: Source | None = None
        if "source" in record:
            source_record = object_value(record["source"], f"{path}.source")
            check_keys(
                source_record,
                f"{path}.source",
                required={"id", "citation"},
                allowed={"id", "citation", "locator"},
            )
            source = Source(
                slug_value(source_record["id"], f"{path}.source.id", max_length=80),
                string_value(source_record["citation"], f"{path}.source.citation", single_line=True),
                _optional_text(source_record, "locator", f"{path}.source.locator"),
            )
        concepts.append(
            Concept(
                concept_id,
                string_value(record["title"], f"{path}.title", single_line=True),
                string_value(record["body"], f"{path}.body"),
                tuple(tags),
                tuple(references),
                source,
            )
        )
    return Collection(
        string_value(root["collection_title"], "collection_title", single_line=True),
        tuple(concepts),
    )


def _wrapped(value: str, width: int, start_column: int) -> list[str]:
    lines: list[str] = []
    for logical in value.split("\n"):
        try:
            lines.extend(wrap_line(logical, width, start_column=start_column))
        except ValueError as error:
            raise FitError(str(error)) from error
    return lines or [""]


def _field(label: str, value: str, inner_width: int) -> list[str]:
    prefix = f"{label}: "
    available = inner_width - len(prefix)
    if available < 1:
        raise FitError(f"atomic card is too narrow for {label}")
    rows = _wrapped(value, available, 2 + len(prefix))
    return [prefix + rows[0], *(" " * len(prefix) + row for row in rows[1:])]


def _reference_text(reference: Reference, known_ids: set[str]) -> tuple[str, bool]:
    if reference.kind == "external":
        marker, resolved = "[E]", False
    else:
        resolved = reference.reference_id in known_ids
        marker = "[I:ok]" if resolved else "[I:?]"
    suffix = f" - {reference.label}" if reference.label is not None else ""
    return f"{marker} {reference.reference_id}{suffix}", resolved


def _source_text(source: Source | None) -> str:
    if source is None:
        return "(none)"
    suffix = f" @ {source.locator}" if source.locator is not None else ""
    return f"{source.source_id} | {source.citation}{suffix}"


def _paint(collection: Collection, concept: Concept, known_ids: set[str], width: int, theme: str) -> str:
    if width < MIN_WIDTH:
        raise FitError(f"atomic cards require at least {MIN_WIDTH} cells")
    inner = width - 4
    elements: list[str | None] = []
    elements.extend(_field("COLLECTION", collection.title, inner))
    elements.extend(_field("ID", concept.concept_id, inner))
    elements.append(None)
    elements.extend(_field("TITLE", concept.title, inner))
    elements.append(None)
    elements.append("BODY")
    elements.extend(_wrapped(concept.body, inner, 2))
    elements.append(None)
    elements.extend(_field("TAGS", ", ".join(concept.tags) if concept.tags else "(none)", inner))
    if concept.references:
        for reference in concept.references:
            visible, _ = _reference_text(reference, known_ids)
            elements.extend(_field("REF", visible, inner))
    else:
        elements.extend(_field("REFS", "(none)", inner))
    elements.extend(_field("SOURCE", _source_text(concept.source), inner))
    lines = [frame_rule(width, theme, position="top")]
    for element in elements:
        lines.append(
            frame_rule(width, theme, position="middle")
            if element is None
            else frame_row(width, theme, element)
        )
    lines.append(frame_rule(width, theme, position="bottom"))
    return "\n".join(lines)


def _reference_metadata(references: tuple[Reference, ...], known_ids: set[str]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for reference in references:
        _, resolved = _reference_text(reference, known_ids)
        output.append(
            {
                "id": reference.reference_id,
                "kind": reference.kind,
                "label": reference.label,
                "resolved": resolved,
            }
        )
    return output


def _source_metadata(source: Source | None) -> dict[str, object] | None:
    if source is None:
        return None
    return {"id": source.source_id, "citation": source.citation, "locator": source.locator}


def _draft(
    collection: Collection,
    concept: Concept,
    index: int,
    known_ids: set[str],
    options: RenderOptions,
) -> CardDraft:
    if options.max_width < MIN_WIDTH:
        raise FitError(f"atomic cards require max_width >= {MIN_WIDTH}")
    preferred = min(PREFERRED_WIDTH, options.max_width)
    attempts = (preferred,) if preferred == options.max_width else (preferred, options.max_width)
    last_height = 0
    for width in attempts:
        text = _paint(collection, concept, known_ids, width, options.theme)
        height = len(text.split("\n"))
        last_height = height
        if height <= options.max_height:
            return CardDraft(
                concept.concept_id,
                text,
                width,
                height,
                metadata={
                    "atomic": True,
                    "concept_id": concept.concept_id,
                    "collection_title": collection.title,
                    "concept_order": index,
                    "tags": list(concept.tags),
                    "references": _reference_metadata(concept.references, known_ids),
                    "source": _source_metadata(concept.source),
                    "creates_board_edges": False,
                },
            )
    raise FitError(
        f"concept {concept.concept_id!r} is indivisible and needs {last_height} rows at maximum width"
    )


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    collection = _normalize(data)
    if options.single_card and len(collection.concepts) != 1:
        raise FitError("--single-card requires exactly one atomic concept")
    known_ids = {concept.concept_id for concept in collection.concepts}
    drafts = tuple(
        _draft(collection, concept, index, known_ids, options)
        for index, concept in enumerate(collection.concepts)
    )
    placements = pack_row_major(
        tuple(ShelfItem(card.logical_id, card.width, card.height) for card in drafts),
        columns=PACK_COLUMNS,
        gutter_x=GUTTER_X,
        gutter_y=GUTTER_Y,
    )
    cards: list[CardDraft] = []
    for draft, placement in zip(drafts, placements):
        metadata = dict(draft.metadata)
        metadata["packing"] = {
            "engine": "grid",
            "columns": PACK_COLUMNS,
            "row": placement.row,
            "column": placement.column,
        }
        cards.append(replace(draft, x=placement.x, y=placement.y, metadata=metadata))
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
