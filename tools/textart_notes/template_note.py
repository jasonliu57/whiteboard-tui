#!/usr/bin/env python3
"""Render reusable fill-in templates as text-art Schema Blocks."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.boxes import frame_row, frame_rule
from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.core.cli import run_renderer
from tools.textart_notes.core.models import CardDraft, FitError, InputError, RenderOptions, RenderResult
from tools.textart_notes.core.schema import (
    array_value,
    bool_value,
    check_keys,
    int_value,
    object_value,
    slug_value,
    string_value,
)
from tools.textart_notes.core.validate import validate_options, validate_result
from tools.textart_notes.core.wrap import wrap_line


RENDERER = "template-note"
MIN_WIDTH = 16
GUTTER = 2
_MISSING = object()


@dataclass(frozen=True)
class Blank:
    style: str
    text: str = ""


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    kind: str
    required: bool
    blank: Blank | None = None


@dataclass(frozen=True)
class Section:
    id: str
    label: str
    min_items: int
    max_items: int
    max_height: int
    empty_placeholder: str
    fields: tuple[Field, ...]


@dataclass(frozen=True)
class Template:
    template_id: str
    title: str
    fields: tuple[Field, ...]
    sections: tuple[Section, ...]
    field_values: Mapping[str, object]
    section_values: Mapping[str, tuple[Mapping[str, object], ...]]


@dataclass(frozen=True)
class Unit:
    key: str
    rows: tuple[str, ...]
    incomplete: int


def _parse_blank(value: object, path: str) -> Blank:
    raw = object_value(value, path)
    check_keys(raw, path, required={"style"}, allowed={"style", "text"})
    style = raw["style"]
    if style not in {"placeholder", "line"}:
        raise InputError(f"{path}.style must be placeholder or line")
    if style == "placeholder":
        if "text" not in raw:
            raise InputError(f"{path}.text is required for placeholder style")
        return Blank(
            style,
            string_value(raw["text"], f"{path}.text", single_line=True, allow_tabs=False),
        )
    if "text" in raw:
        raise InputError(f"{path}.text is not allowed for line style")
    return Blank(style)


def _parse_field(value: object, path: str) -> Field:
    raw = object_value(value, path)
    check_keys(
        raw,
        path,
        required={"id", "label", "type", "required"},
        allowed={"id", "label", "type", "required", "blank"},
    )
    kind = raw["type"]
    if kind not in {"text", "checkbox"}:
        raise InputError(f"{path}.type must be text or checkbox")
    blank: Blank | None = None
    if kind == "text":
        if "blank" not in raw:
            raise InputError(f"{path}.blank is required for text fields")
        blank = _parse_blank(raw["blank"], f"{path}.blank")
    elif "blank" in raw:
        raise InputError(f"{path}.blank is not allowed for checkbox fields")
    return Field(
        slug_value(raw["id"], f"{path}.id", max_length=40),
        string_value(raw["label"], f"{path}.label", single_line=True),
        str(kind),
        bool_value(raw["required"], f"{path}.required"),
        blank,
    )


def _unique(items: Sequence[Field | Section], path: str) -> None:
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            raise InputError(f"{path} contains duplicate id: {item.id}")
        seen.add(item.id)


def _parse_section(value: object, path: str) -> Section:
    raw = object_value(value, path)
    required = {
        "id", "label", "min_items", "max_items", "max_height",
        "empty_placeholder", "item_fields",
    }
    check_keys(raw, path, required=required, allowed=required)
    field_values = array_value(raw["item_fields"], f"{path}.item_fields")
    if not field_values:
        raise InputError(f"{path}.item_fields must not be empty")
    fields = tuple(
        _parse_field(item, f"{path}.item_fields[{index}]")
        for index, item in enumerate(field_values)
    )
    _unique(fields, f"{path}.item_fields")
    minimum = int_value(raw["min_items"], f"{path}.min_items", minimum=0, maximum=1000)
    maximum = int_value(raw["max_items"], f"{path}.max_items", minimum=1, maximum=1000)
    if minimum > maximum:
        raise InputError(f"{path}.min_items must not exceed max_items")
    return Section(
        slug_value(raw["id"], f"{path}.id", max_length=40),
        string_value(raw["label"], f"{path}.label", single_line=True),
        minimum,
        maximum,
        int_value(raw["max_height"], f"{path}.max_height", minimum=3, maximum=100),
        string_value(
            raw["empty_placeholder"],
            f"{path}.empty_placeholder",
            single_line=True,
        ),
        fields,
    )


def _validate_value(field: Field, value: object, path: str) -> None:
    if value is None:
        return
    if field.kind == "checkbox":
        bool_value(value, path)
    else:
        string_value(value, path, allow_empty=True)


def _normalize(data: dict[str, object]) -> Template:
    root = object_value(data, "input")
    check_keys(root, "input", required={"schema", "values"}, allowed={"schema", "values"})
    schema = object_value(root["schema"], "schema")
    schema_keys = {"version", "template_id", "title", "fields", "repeatable_sections"}
    check_keys(schema, "schema", required=schema_keys, allowed=schema_keys)
    if type(schema["version"]) is not int or schema["version"] != 1:
        raise InputError("schema.version must equal 1")
    fields = tuple(
        _parse_field(value, f"schema.fields[{index}]")
        for index, value in enumerate(array_value(schema["fields"], "schema.fields"))
    )
    sections = tuple(
        _parse_section(value, f"schema.repeatable_sections[{index}]")
        for index, value in enumerate(
            array_value(schema["repeatable_sections"], "schema.repeatable_sections")
        )
    )
    if not fields and not sections:
        raise InputError("template must declare at least one field or repeatable section")
    _unique(fields, "schema.fields")
    _unique(sections, "schema.repeatable_sections")
    if set(field.id for field in fields) & set(section.id for section in sections):
        raise InputError("field and section ids must be globally distinct")

    values = object_value(root["values"], "values")
    check_keys(
        values,
        "values",
        required={"fields", "repeatable_sections"},
        allowed={"fields", "repeatable_sections"},
    )
    raw_fields = object_value(values["fields"], "values.fields")
    field_by_id = {field.id: field for field in fields}
    unknown_fields = sorted(set(raw_fields) - set(field_by_id))
    if unknown_fields:
        raise InputError(f"values.fields has unknown ids: {', '.join(unknown_fields)}")
    for field_id, value in raw_fields.items():
        _validate_value(field_by_id[field_id], value, f"values.fields.{field_id}")

    raw_sections = object_value(values["repeatable_sections"], "values.repeatable_sections")
    section_by_id = {section.id: section for section in sections}
    unknown_sections = sorted(set(raw_sections) - set(section_by_id))
    if unknown_sections:
        raise InputError(
            f"values.repeatable_sections has unknown ids: {', '.join(unknown_sections)}"
        )
    section_values: dict[str, tuple[Mapping[str, object], ...]] = {}
    for section in sections:
        items = array_value(raw_sections.get(section.id, []), f"values.repeatable_sections.{section.id}")
        if len(items) > section.max_items:
            raise InputError(
                f"values.repeatable_sections.{section.id} exceeds max_items={section.max_items}"
            )
        child_by_id = {field.id: field for field in section.fields}
        normalized_items: list[Mapping[str, object]] = []
        for index, value in enumerate(items):
            path = f"values.repeatable_sections.{section.id}[{index}]"
            item = object_value(value, path)
            unknown = sorted(set(item) - set(child_by_id))
            if unknown:
                raise InputError(f"{path} has unknown ids: {', '.join(unknown)}")
            for field_id, field_value in item.items():
                _validate_value(child_by_id[field_id], field_value, f"{path}.{field_id}")
            normalized_items.append(item)
        section_values[section.id] = tuple(normalized_items)

    return Template(
        slug_value(schema["template_id"], "schema.template_id", max_length=60),
        string_value(schema["title"], "schema.title", single_line=True),
        fields,
        sections,
        raw_fields,
        section_values,
    )


def _wrapped(value: str, width: int, *, prefix: str = "", start_column: int = 2) -> list[str]:
    prefix_width = text_width(prefix)
    available = width - prefix_width
    if available < 1:
        raise FitError(f"prefix {prefix!r} leaves no content width")
    rows: list[str] = []
    first = True
    for hard_line in value.split("\n"):
        for row in wrap_line(hard_line, available, start_column=start_column + prefix_width):
            rows.append((prefix if first else " " * prefix_width) + row)
            first = False
    return rows or [prefix]


def _blank_rows(field: Field, width: int, prefix: str) -> list[str]:
    assert field.blank is not None
    marker = "! " if field.required else "  "
    full_prefix = prefix + marker
    if field.blank.style == "placeholder":
        return _wrapped(f"<{field.blank.text}>", width, prefix=full_prefix)
    count = width - text_width(full_prefix)
    if count < 1:
        raise FitError("blank line has no horizontal room")
    return [full_prefix + "_" * count]


def _field_rows(field: Field, value: object, width: int, *, nested: bool = False) -> tuple[list[str], int]:
    indent = "  " if nested else ""
    required_marker = "* " if field.required else "- "
    blank = value is _MISSING or value is None or (
        field.kind == "text" and isinstance(value, str) and not value.strip()
    )
    if field.kind == "checkbox":
        token = "[x]" if value is True else "[ ]"
        suffix = " <blank>" if blank else ""
        return _wrapped(field.label + suffix, width, prefix=indent + required_marker + token + " "), int(field.required and blank)
    rows = _wrapped(field.label, width, prefix=indent + required_marker)
    if blank:
        rows.extend(_blank_rows(field, width, indent + "  "))
    else:
        assert isinstance(value, str)
        rows.extend(_wrapped(value, width, prefix=indent + "  "))
    return rows, int(field.required and blank)


def _units(note: Template, width: int) -> list[Unit]:
    units: list[Unit] = []
    for field in note.fields:
        rows, incomplete = _field_rows(field, note.field_values.get(field.id, _MISSING), width)
        units.append(Unit(f"field:{field.id}", tuple(rows), incomplete))
    for section in note.sections:
        actual = list(note.section_values[section.id])
        required_slots = max(section.min_items, len(actual))
        records: list[Mapping[str, object]] = actual + [dict() for _ in range(required_slots - len(actual))]
        if not records:
            rows = _wrapped(section.label, width, prefix="# ")
            rows.extend(_wrapped(f"<{section.empty_placeholder}>", width, prefix="  "))
            units.append(Unit(f"section:{section.id}:empty", tuple(rows), 0))
            continue
        for index, record in enumerate(records, start=1):
            rows = _wrapped(section.label, width, prefix="# ")
            rows.extend(_wrapped(f"Record {index}", width, prefix="  "))
            incomplete = 0
            for field in section.fields:
                field_rows, missing = _field_rows(
                    field, record.get(field.id, _MISSING), width, nested=True
                )
                rows.extend(field_rows)
                incomplete += missing
            if len(rows) > section.max_height:
                raise FitError(
                    f"repeatable record {section.id}[{index - 1}] exceeds section max_height"
                )
            units.append(Unit(f"section:{section.id}:{index}", tuple(rows), incomplete))
    return units


def _header_rows(note: Template, width: int, page: int, total: int) -> list[str]:
    rows = _wrapped(note.title, width)
    rows.extend(_wrapped(note.template_id, width, prefix="Template: "))
    rows.extend(_wrapped("* required; - optional; ! missing; [x]/[ ] checkbox", width, prefix="Legend: "))
    rows.extend(_wrapped(f"{page}/{total}", width, prefix="Part: "))
    return rows


def _paginate(note: Template, units: list[Unit], options: RenderOptions) -> list[list[Unit]]:
    guess = 1
    for _ in range(32):
        header_height = len(_header_rows(note, options.max_width - 4, guess, guess))
        capacity = options.max_height - header_height - 3
        if capacity < 1:
            raise FitError("template header leaves no room for fields")
        pages: list[list[Unit]] = []
        current: list[Unit] = []
        used = 0
        for unit in units:
            if len(unit.rows) > capacity:
                raise FitError(f"indivisible {unit.key} cannot fit one card")
            if current and used + len(unit.rows) > capacity:
                pages.append(current)
                current = []
                used = 0
            current.append(unit)
            used += len(unit.rows)
        if current:
            pages.append(current)
        if len(pages) == guess:
            return pages
        guess = len(pages)
    raise FitError("template pagination did not converge")


def render(data: dict[str, object], options: RenderOptions) -> RenderResult:
    validate_options(options)
    if options.max_width < MIN_WIDTH:
        raise FitError(f"template cards require at least {MIN_WIDTH} cells of width")
    note = _normalize(data)
    inner_width = options.max_width - 4
    units = _units(note, inner_width)
    pages = _paginate(note, units, options)
    if options.single_card and len(pages) != 1:
        raise FitError(f"template requires {len(pages)} complete cards")
    cards: list[CardDraft] = []
    next_y = 0
    total_incomplete = sum(unit.incomplete for unit in units)
    for page_number, page_units in enumerate(pages, start=1):
        lines = [frame_rule(options.max_width, options.theme, position="top")]
        lines.extend(
            frame_row(options.max_width, options.theme, row)
            for row in _header_rows(note, inner_width, page_number, len(pages))
        )
        lines.append(frame_rule(options.max_width, options.theme, position="middle"))
        for unit in page_units:
            lines.extend(frame_row(options.max_width, options.theme, row) for row in unit.rows)
        lines.append(frame_rule(options.max_width, options.theme, position="bottom"))
        logical_id = f"template-{note.template_id}-{page_number:03d}"
        card = CardDraft(
            logical_id,
            "\n".join(lines),
            options.max_width,
            len(lines),
            0,
            next_y,
            {
                "template_id": note.template_id,
                "part": page_number,
                "parts": len(pages),
                "incomplete_required": total_incomplete,
                "unit_keys": [unit.key for unit in page_units],
            },
        )
        cards.append(card)
        next_y += card.height + GUTTER
    result = RenderResult(RENDERER, options.theme, tuple(cards))
    validate_result(result, options)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    return run_renderer(RENDERER, render, argv)


if __name__ == "__main__":
    raise SystemExit(main())
