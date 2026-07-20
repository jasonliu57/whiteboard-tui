#!/usr/bin/env python3
"""Compile and validate deterministic format-first whiteboard artifacts.

Exit codes:
  0: success
  1: valid input with one or more geometry errors
  2: invalid input, schema, or file data
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from whiteboard_validation.artifacts import (
    FORMATS,
    LOGICAL_ID_PATTERN,
    UNIT_ID_PATTERN,
    CardRow,
    MemberRow,
    MindMapInputError,
    UnitRow,
    atomic_write,
    load_cards,
    load_edges,
    load_layout,
    load_members,
    load_units,
    parse_integer,
    resolve_folder_payload,
    resolve_path,
)
from tools.textart_notes.core.cell_width import text_width
from tools.textart_notes.frozen_generation import ManifestError, load_plan
from tools.textart_notes.render_note import load_renderer
from tools.whiteboard_automation.batch import CreateCardSpec, encode_create_cards


RENDERER_DISPATCHER = REPO_ROOT / "tools" / "textart_notes" / "render_note.py"


@dataclass(frozen=True)
class PlannedUnit:
    logical_id: str
    kind: str
    native_format: str | None
    renderer: str | None
    group: str
    title: str
    why: str
    content: str
    theme: str = "unicode-light"
    max_width: int = 120
    max_height: int = 70
    single_card: bool = False

    @property
    def card_format(self) -> str:
        if self.kind != "native" or self.native_format is None:
            raise MindMapInputError(f"{self.logical_id}: unit is not a native card")
        return self.native_format

    @property
    def payload(self) -> str:
        return self.content


@dataclass(frozen=True)
class PreparedCard:
    logical_id: str
    width: int
    height: int
    title: str
    payload_path: str
    payload_text: str
    dx: int
    dy: int


@dataclass(frozen=True)
class PreparedUnit:
    source: PlannedUnit
    width: int
    height: int
    anchor: str
    cards: tuple[PreparedCard, ...]
    renderer_manifest: str | None = None
    renderer_payloads: Mapping[str, str] | None = None


@dataclass(frozen=True)
class Rect:
    logical_id: str
    title: str
    x: int
    y: int
    width: int
    height: int
    group: str

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)


def parse_plan(path: Path) -> tuple[str, list[PlannedUnit], list[tuple[str, str]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise MindMapInputError(f"{path}: {error}") from error

    if not text.startswith("# Design\n"):
        raise MindMapInputError(f"{path}: response must begin with # Design")
    units_marker = "\n# Units\n"
    try:
        design, remainder = text.split(units_marker, 1)
        units_text, remainder = remainder.split("\n# Groups\n", 1)
        _, connections_text = remainder.split("\n# Connections\n", 1)
    except ValueError as error:
        raise MindMapInputError(
            f"{path}: missing or duplicate required top-level section"
        ) from error

    matches = list(
        re.finditer(
            r"(?ms)^## ([a-z0-9][a-z0-9-]*)\n\n(.*?)(?=^## |\Z)",
            units_text.strip() + "\n",
        )
    )
    if not matches:
        raise MindMapInputError(f"{path}: no presentation units found")
    if "".join(match.group(0) for match in matches).strip() != units_text.strip():
        raise MindMapInputError(f"{path}: unparsed content exists in {units_marker.strip()}")

    units: list[PlannedUnit] = []
    for match in matches:
        logical_id = match.group(1)
        if not UNIT_ID_PATTERN.fullmatch(logical_id):
            raise MindMapInputError(f"{path}: invalid unit ID {logical_id!r}")
        body = match.group(2).rstrip()
        fence = "payload" if "~~~payload\n" in body else "input"
        marker = f"~~~{fence}\n"
        if marker not in body:
            raise MindMapInputError(f"{logical_id}: missing payload or input fence")
        metadata_text, content_part = body.split(marker, 1)
        if "\n~~~" not in content_part:
            raise MindMapInputError(f"{logical_id}: unterminated {fence} fence")
        content, suffix = content_part.rsplit("\n~~~", 1)
        if suffix.strip():
            raise MindMapInputError(f"{logical_id}: text follows {fence} fence")
        if not content:
            raise MindMapInputError(f"{logical_id}: empty {fence}")

        metadata: dict[str, str] = {}
        for line in metadata_text.splitlines():
            if not line.strip():
                continue
            metadata_match = re.fullmatch(r"([a-z][a-z-]*):\s*(.+)", line)
            if not metadata_match:
                raise MindMapInputError(
                    f"{logical_id}: invalid metadata line {line!r}"
                )
            key, value = metadata_match.groups()
            if key in metadata:
                raise MindMapInputError(
                    f"{logical_id}: duplicate metadata key {key}"
                )
            metadata[key] = value

        common = {"kind", "group", "title", "why"}
        if not common <= set(metadata):
            missing = sorted(common - set(metadata))
            raise MindMapInputError(f"{logical_id}: missing metadata {missing}")
        kind = metadata["kind"]
        if kind == "native":
            allowed = common | {"format"}
            if set(metadata) != allowed or fence != "payload":
                raise MindMapInputError(
                    f"{logical_id}: native unit requires kind/format/group/title/why and payload"
                )
            native_format = metadata["format"]
            if native_format not in FORMATS:
                raise MindMapInputError(
                    f"{logical_id}: unsupported format {native_format!r}"
                )
            units.append(
                PlannedUnit(
                    logical_id=logical_id,
                    kind=kind,
                    native_format=native_format,
                    renderer=None,
                    group=metadata["group"],
                    title=metadata["title"],
                    why=metadata["why"],
                    content=content,
                )
            )
            continue

        if kind != "renderer":
            raise MindMapInputError(f"{logical_id}: kind must be native or renderer")
        allowed = common | {
            "renderer",
            "theme",
            "max-width",
            "max-height",
            "single-card",
        }
        unknown = sorted(set(metadata) - allowed)
        if unknown or "renderer" not in metadata or fence != "input":
            raise MindMapInputError(
                f"{logical_id}: invalid renderer metadata or missing input fence"
            )
        renderer = metadata["renderer"]
        if not UNIT_ID_PATTERN.fullmatch(renderer):
            raise MindMapInputError(f"{logical_id}: invalid renderer key {renderer!r}")
        theme = metadata.get("theme", "unicode-light")
        if theme not in {"ascii", "unicode-light", "unicode-rich"}:
            raise MindMapInputError(f"{logical_id}: unsupported theme {theme!r}")
        max_width = parse_integer(metadata.get("max-width", "120"), f"{logical_id}.max-width")
        max_height = parse_integer(metadata.get("max-height", "70"), f"{logical_id}.max-height")
        if not 1 <= max_width <= 160 or not 1 <= max_height <= 100:
            raise MindMapInputError(
                f"{logical_id}: renderer bounds must be within 1..160 x 1..100"
            )
        single_text = metadata.get("single-card", "false")
        if single_text not in {"true", "false"}:
            raise MindMapInputError(f"{logical_id}: single-card must be true or false")
        units.append(
            PlannedUnit(
                logical_id=logical_id,
                kind=kind,
                native_format=None,
                renderer=renderer,
                group=metadata["group"],
                title=metadata["title"],
                why=metadata["why"],
                content=content,
                theme=theme,
                max_width=max_width,
                max_height=max_height,
                single_card=single_text == "true",
            )
        )

    ids = [unit.logical_id for unit in units]
    if len(ids) != len(set(ids)):
        raise MindMapInputError(f"{path}: duplicate logical unit ID")
    id_set = set(ids)

    for unit in units:
        if unit.kind != "native" or unit.native_format != "folder":
            continue
        # Validate the exchange contract before producing artifacts. Actual
        # CardIds are assigned only during materialization.
        resolve_folder_payload(
            unit.content.encode("utf-8"),
            logical_id=unit.logical_id,
            unit_anchors={unit_id: unit_id for unit_id in ids},
            card_map={unit_id: index for index, unit_id in enumerate(ids)},
        )

    connection_match = re.fullmatch(
        r"\s*```tsv\n(.*?)\n```\s*",
        connections_text,
        flags=re.DOTALL,
    )
    if not connection_match:
        raise MindMapInputError(f"{path}: connections must be one TSV fence")
    reader = csv.DictReader(
        io.StringIO(connection_match.group(1)),
        delimiter="\t",
    )
    if reader.fieldnames != ["from", "to"]:
        raise MindMapInputError(
            f"{path}: connection header must be from<TAB>to"
        )

    edges: list[tuple[str, str]] = []
    edge_set: set[tuple[str, str]] = set()
    for row in reader:
        source = row.get("from")
        target = row.get("to")
        if source is None or target is None:
            raise MindMapInputError(f"{path}: malformed connection row")
        if source not in id_set or target not in id_set:
            raise MindMapInputError(
                f"{path}: unknown connection endpoint {source}->{target}"
            )
        if source == target:
            raise MindMapInputError(f"{path}: self connection {source}->{target}")
        pair = (source, target)
        if pair in edge_set:
            raise MindMapInputError(
                f"{path}: duplicate connection {source}->{target}"
            )
        edge_set.add(pair)
        edges.append(pair)

    without_payloads = re.sub(
        r"(?ms)^~~~(?:payload|input)\n.*?^~~~\s*$",
        "",
        text,
    )
    geometry = re.search(
        r"(?im)^\s*(x|y|width|height)\s*[:\t]",
        without_payloads,
    )
    if geometry:
        raise MindMapInputError(
            f"{path}: premature final geometry field {geometry.group(1)}"
        )

    return design + "\n", units, edges


def cell_width(text: str) -> int:
    return text_width(text)


def wrapped_lines(text: str, available: int) -> int:
    total = 0
    for line in text.splitlines() or [""]:
        total += max(1, math.ceil(cell_width(line) / max(1, available)))
    return total


def choose_prose_size(
    text: str,
    candidates: Sequence[int],
    spec: FormatSpec,
    padding: tuple[int, int] = (4, 4),
) -> tuple[int, int]:
    viable: list[tuple[float, int, int]] = []
    for candidate in candidates:
        width = min(max(candidate, spec.minimum[0]), spec.maximum[0])
        estimated_height = wrapped_lines(text, width - padding[0]) + padding[1]
        height = min(max(estimated_height, spec.minimum[1]), spec.maximum[1])
        ratio = width / max(1, height)
        score = width * height + abs(ratio - 2.4) * 18
        viable.append((score, width, height))
    _, width, height = min(viable)
    return width, height


def measure_card(card: PlannedUnit) -> tuple[int, int]:
    spec = FORMATS[card.card_format]
    if card.card_format == "text-art":
        lines = card.payload.splitlines()
        width = max((cell_width(line) for line in lines), default=1)
        height = max(1, len(lines))
        if width > spec.maximum[0] or height > spec.maximum[1]:
            raise MindMapInputError(
                f"{card.logical_id}: text-art payload is {width}x{height}, "
                f"maximum is {spec.maximum[0]}x{spec.maximum[1]}"
            )
    elif card.card_format == "code":
        lines = card.payload.splitlines()
        width = max((cell_width(line) for line in lines), default=1) + 4
        height = len(lines) + 4
    elif card.card_format == "csv":
        try:
            rows = list(csv.reader(io.StringIO(card.payload, newline=""), strict=True))
        except csv.Error as error:
            raise MindMapInputError(f"{card.logical_id}: invalid CSV: {error}") from error
        if not rows:
            raise MindMapInputError(f"{card.logical_id}: empty CSV")
        column_count = max(len(row) for row in rows)
        column_widths = [
            max(
                (
                    max((cell_width(line) for line in row[column].splitlines()), default=0)
                    if column < len(row) else 0
                    for row in rows
                ),
                default=0,
            )
            for column in range(column_count)
        ]
        width = sum(column_widths) + 3 * column_count + 1
        height = len(rows) + 4
    elif card.card_format == "folder":
        lines = card.payload.splitlines()
        width = max((cell_width(line) for line in lines), default=1) + 6
        height = len(lines) + 4
    elif card.card_format == "todo":
        width, height = choose_prose_size(
            card.payload,
            [20, 24, 30, 36, 42, 48],
            spec,
        )
    elif card.card_format == "note":
        width, height = choose_prose_size(
            card.payload,
            [20, 24, 30, 36, 42, 48, 56],
            spec,
        )
    else:
        width, height = choose_prose_size(
            card.payload,
            [32, 40, 48, 56, 64],
            spec,
        )

    width = min(max(width, spec.minimum[0]), spec.maximum[0])
    height = min(max(height, spec.minimum[1]), spec.maximum[1])
    return int(width), int(height)


def prepare_unit(unit: PlannedUnit, temporary_root: Path) -> PreparedUnit:
    if unit.kind == "native":
        width, height = measure_card(unit)
        payload = unit.content
        if unit.card_format == "csv":
            try:
                rows = list(csv.reader(io.StringIO(payload, newline=""), strict=True))
            except csv.Error as error:
                raise MindMapInputError(f"{unit.logical_id}: invalid CSV: {error}") from error

            columns = max(1, max(len(row) for row in rows))
            rows = [row + [""] * (columns - len(row)) for row in rows]

            def quote_cell(cell: str) -> str:
                if any(character in cell for character in ',"\r\n'):
                    return '"' + cell.replace('"', '""') + '"'
                return cell

            payload = "\n".join(
                ('""' if not row or row == [""] else ",".join(quote_cell(cell) for cell in row))
                for row in rows
            )
        elif unit.card_format == "todo":
            if any(not line.startswith(("- [ ] ", "- [x] ")) for line in payload.split("\n")):
                raise MindMapInputError(
                    f"{unit.logical_id}: todo lines must begin with '- [ ] ' or '- [x] '"
                )
        else:
            payload += "\n"
        extension = FORMATS[unit.card_format].extension
        payload_path = (Path("payloads") / f"{unit.logical_id}{extension}").as_posix()
        card = PreparedCard(
            logical_id=unit.logical_id,
            width=width,
            height=height,
            title=unit.title,
            payload_path=payload_path,
            # Payload artifacts must match the Board's canonical content
            # export, including CSV quoting and Todo/CSV terminal newlines.
            payload_text=payload,
            dx=0,
            dy=0,
        )
        return PreparedUnit(unit, width, height, unit.logical_id, (card,))

    if unit.renderer is None:
        raise MindMapInputError(f"{unit.logical_id}: missing renderer key")
    if not RENDERER_DISPATCHER.is_file():
        raise MindMapInputError(f"renderer dispatcher is missing: {RENDERER_DISPATCHER}")

    input_path = temporary_root / f"{unit.logical_id}.json"
    input_path.write_text(unit.content + "\n", encoding="utf-8", newline="\n")
    output_dir = temporary_root / unit.logical_id
    command = [
        sys.executable,
        "-B",
        str(RENDERER_DISPATCHER),
        "--style",
        unit.renderer,
        "--input",
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--theme",
        unit.theme,
        "--max-width",
        str(unit.max_width),
        "--max-height",
        str(unit.max_height),
    ]
    if unit.single_card:
        command.append("--single-card")
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MindMapInputError(
            f"{unit.logical_id}: could not execute renderer: {error}"
        ) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown renderer error"
        raise MindMapInputError(
            f"{unit.logical_id}: renderer {unit.renderer!r} failed "
            f"with exit {result.returncode}: {detail}"
        )

    manifest_path = output_dir / "manifest.json"
    try:
        manifest_text = manifest_path.read_text(encoding="utf-8")
        rendered = load_plan(manifest_path, origin_x=0, origin_y=0)
    except (OSError, UnicodeError, ManifestError) as error:
        raise MindMapInputError(
            f"{unit.logical_id}: invalid renderer manifest: {error}"
        ) from error
    renderer_spec, _ = load_renderer(unit.renderer)
    if rendered.renderer != renderer_spec.manifest_renderer or rendered.theme != unit.theme:
        raise MindMapInputError(f"{unit.logical_id}: renderer manifest identity mismatch")

    prepared: list[PreparedCard] = []
    renderer_payloads: dict[str, str] = {}
    for index, card in enumerate(rendered.cards):
        payload_text = card.payload.decode("utf-8")
        combined_id = f"{unit.logical_id}--{card.logical_id}"
        card_title = (
            unit.title
            if len(rendered.cards) == 1
            else f"{unit.title} [{index + 1}/{len(rendered.cards)}]"
        )
        payload_path = (Path("payloads") / f"{combined_id}.txt").as_posix()
        prepared.append(
            PreparedCard(
                logical_id=combined_id,
                width=card.width,
                height=card.height,
                title=card_title,
                payload_path=payload_path,
                payload_text=payload_text,
                dx=card.relative_x,
                dy=card.relative_y,
            )
        )
        renderer_payloads[card.payload_name] = payload_text

    unit_width = max(card.dx + card.width for card in prepared)
    unit_height = max(card.dy + card.height for card in prepared)
    return PreparedUnit(
        source=unit,
        width=unit_width,
        height=unit_height,
        anchor=prepared[0].logical_id,
        cards=tuple(prepared),
        renderer_manifest=manifest_text,
        renderer_payloads=renderer_payloads,
    )


def command_prepare(arguments: argparse.Namespace) -> int:
    run_dir = Path(arguments.run_dir).resolve()
    plan_path = resolve_path(run_dir, arguments.plan, "plan.md")
    _, units, unit_edges = parse_plan(plan_path)
    with tempfile.TemporaryDirectory(prefix="wb-presentation-render-") as name:
        temporary_root = Path(name)
        prepared_units = [prepare_unit(unit, temporary_root) for unit in units]

    all_prepared_cards = [
        card for prepared_unit in prepared_units for card in prepared_unit.cards
    ]
    card_ids = [card.logical_id for card in all_prepared_cards]
    if len(card_ids) != len(set(card_ids)):
        raise MindMapInputError(
            "renderer expansion produced duplicate logical card IDs; rename a unit"
        )
    print(
        f"VALID plan={plan_path} units={len(units)} "
        f"cards={len(all_prepared_cards)} edges={len(unit_edges)}"
    )
    if arguments.check_only:
        return 0

    payload_dir = run_dir / "payloads"
    payload_dir.mkdir(parents=True, exist_ok=True)
    card_rows: list[list[str]] = []
    unit_rows: list[list[str]] = []
    member_rows: list[list[str]] = []
    anchor_by_unit: dict[str, str] = {}
    card_index = 0
    for unit_index, prepared_unit in enumerate(prepared_units):
        unit = prepared_unit.source
        anchor_by_unit[unit.logical_id] = prepared_unit.anchor
        unit_rows.append(
            [
                unit.logical_id,
                str(unit_index),
                unit.kind,
                unit.renderer or "-",
                str(prepared_unit.width),
                str(prepared_unit.height),
                unit.group,
                unit.title,
                prepared_unit.anchor,
            ]
        )
        for card in prepared_unit.cards:
            atomic_write(run_dir / card.payload_path, card.payload_text)
            card_rows.append(
                [
                    card.logical_id,
                    str(card_index),
                    unit.card_format if unit.kind == "native" else "text-art",
                    str(card.width),
                    str(card.height),
                    unit.group,
                    card.title,
                    card.payload_path,
                ]
            )
            member_rows.append(
                [unit.logical_id, card.logical_id, str(card.dx), str(card.dy)]
            )
            card_index += 1

        if unit.kind == "renderer":
            atomic_write(
                run_dir / "renderer-inputs" / f"{unit.logical_id}.json",
                unit.content + "\n",
            )
            if prepared_unit.renderer_manifest is None or prepared_unit.renderer_payloads is None:
                raise MindMapInputError(
                    f"{unit.logical_id}: missing compiled renderer artifacts"
                )
            rendered_root = run_dir / "work" / "rendered" / unit.logical_id
            atomic_write(
                rendered_root / "manifest.json",
                prepared_unit.renderer_manifest,
            )
            for relative, payload_text in prepared_unit.renderer_payloads.items():
                atomic_write(rendered_root / relative, payload_text)

    cards_output = io.StringIO()
    cards_writer = csv.writer(
        cards_output,
        delimiter="\t",
        lineterminator="\n",
    )
    cards_writer.writerow(
        ["id", "index", "format", "width", "height", "group", "title", "payload"]
    )
    cards_writer.writerows(card_rows)
    atomic_write(run_dir / "cards.tsv", cards_output.getvalue())

    units_output = io.StringIO()
    units_writer = csv.writer(units_output, delimiter="\t", lineterminator="\n")
    units_writer.writerow(
        ["id", "index", "kind", "renderer", "width", "height", "group", "title", "anchor"]
    )
    units_writer.writerows(unit_rows)
    atomic_write(run_dir / "units.tsv", units_output.getvalue())

    members_output = io.StringIO()
    members_writer = csv.writer(
        members_output,
        delimiter="\t",
        lineterminator="\n",
    )
    members_writer.writerow(["unit", "card", "dx", "dy"])
    members_writer.writerows(member_rows)
    atomic_write(run_dir / "unit-members.tsv", members_output.getvalue())

    unit_edges_output = io.StringIO()
    unit_edges_writer = csv.writer(
        unit_edges_output,
        delimiter="\t",
        lineterminator="\n",
    )
    unit_edges_writer.writerow(["from", "to"])
    unit_edges_writer.writerows(unit_edges)
    atomic_write(run_dir / "unit-edges.tsv", unit_edges_output.getvalue())

    edges = [
        (anchor_by_unit[source], anchor_by_unit[target])
        for source, target in unit_edges
    ]
    edges_output = io.StringIO()
    edges_writer = csv.writer(
        edges_output,
        delimiter="\t",
        lineterminator="\n",
    )
    edges_writer.writerow(["from", "to"])
    edges_writer.writerows(edges)
    atomic_write(run_dir / "edges.tsv", edges_output.getvalue())

    loaded_cards = load_cards(run_dir / "cards.tsv")
    loaded_units = load_units(
        run_dir / "units.tsv", {card.logical_id for card in loaded_cards}
    )
    load_members(run_dir / "unit-members.tsv", loaded_units, loaded_cards)
    load_edges(run_dir / "unit-edges.tsv", {unit.logical_id for unit in loaded_units})
    load_edges(run_dir / "edges.tsv", {card.logical_id for card in loaded_cards})
    print(
        f"PREPARED run_dir={run_dir} units={len(loaded_units)} "
        f"cards={len(loaded_cards)} edges={len(edges)}"
    )
    return 0


def interval_overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return min(a1, b1) - max(a0, b0)


def segment_intersects_rect(
    start: tuple[float, float],
    end: tuple[float, float],
    rect: Rect,
    margin: int,
) -> bool:
    left = rect.x - margin
    right = rect.right + margin
    top = rect.y - margin
    bottom = rect.bottom + margin
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    lower = 0.0
    upper = 1.0
    for origin, delta, minimum, maximum in (
        (start[0], dx, left, right),
        (start[1], dy, top, bottom),
    ):
        if delta == 0:
            if origin < minimum or origin > maximum:
                return False
            continue
        first = (minimum - origin) / delta
        second = (maximum - origin) / delta
        lower = max(lower, min(first, second))
        upper = min(upper, max(first, second))
        if lower > upper:
            return False
    return upper >= 0 and lower <= 1


def validate_geometry(
    cards: Sequence[CardRow | UnitRow],
    positions: dict[str, tuple[int, int]],
    edges: list[tuple[str, str]],
    arguments: argparse.Namespace,
    cohesive_by_id: Mapping[str, str] | None = None,
) -> tuple[list[str], list[str], tuple[int, int, int, int]]:
    rects = [
        Rect(
            logical_id=card.logical_id,
            title=card.title,
            x=positions[card.logical_id][0],
            y=positions[card.logical_id][1],
            width=card.width,
            height=card.height,
            group=card.group,
        )
        for card in cards
    ]
    errors: list[str] = []
    warnings: list[str] = []
    relations = {frozenset(edge) for edge in edges}

    for index, first in enumerate(rects):
        for second in rects[index + 1 :]:
            horizontal_overlap = interval_overlap(
                first.x, first.right, second.x, second.right
            )
            vertical_overlap = interval_overlap(
                first.y, first.bottom, second.y, second.bottom
            )
            if horizontal_overlap > 0 and vertical_overlap > 0:
                errors.append(
                    f"{format_rect(first)} and {format_rect(second)} overlap by "
                    f"{horizontal_overlap}×{vertical_overlap} cells. Both items "
                    "occupy the same board area."
                )
                continue

            if (
                cohesive_by_id is not None
                and first.logical_id in cohesive_by_id
                and second.logical_id in cohesive_by_id
                and cohesive_by_id.get(first.logical_id)
                == cohesive_by_id.get(second.logical_id)
            ):
                continue
            if frozenset((first.logical_id, second.logical_id)) in relations:
                continue
            if vertical_overlap > 0:
                horizontal_gap = max(
                    second.x - first.right,
                    first.x - second.right,
                )
                if 0 <= horizontal_gap < arguments.horizontal_gap:
                    errors.append(
                        f"{format_rect(first)} and {format_rect(second)} have a "
                        f"horizontal gap of {horizontal_gap} cells; the minimum is "
                        f"{arguments.horizontal_gap}. Their spacing does not meet "
                        "the horizontal clearance rule."
                    )
            if horizontal_overlap > 0:
                vertical_gap = max(
                    second.y - first.bottom,
                    first.y - second.bottom,
                )
                if 0 <= vertical_gap < arguments.vertical_gap:
                    errors.append(
                        f"{format_rect(first)} and {format_rect(second)} have a "
                        f"vertical gap of {vertical_gap} cells; the minimum is "
                        f"{arguments.vertical_gap}. Their spacing does not meet "
                        "the vertical clearance rule."
                    )

    groups: dict[str, list[Rect]] = {}
    for rect in rects:
        if rect.group != "-":
            groups.setdefault(rect.group, []).append(rect)
    for group, members in groups.items():
        if len(members) < 2:
            continue
        left = min(member.x for member in members)
        top = min(member.y for member in members)
        right = max(member.right for member in members)
        bottom = max(member.bottom for member in members)
        member_area = sum(member.width * member.height for member in members)
        bound_area = (right - left) * (bottom - top)
        ratio = bound_area / member_area
        if ratio > arguments.group_area_ratio:
            warnings.append(
                f'Group "{group}" spans {right-left}×{bottom-top} cells and has '
                f"an area ratio of {ratio:.1f}; the reference ratio is "
                f"{arguments.group_area_ratio:g}. Its members may be harder to "
                "recognize as one visual group."
            )

    left = min(rect.x for rect in rects)
    top = min(rect.y for rect in rects)
    right = max(rect.right for rect in rects)
    bottom = max(rect.bottom for rect in rects)
    width = right - left
    height = bottom - top
    too_wide = arguments.max_board_width > 0 and width > arguments.max_board_width
    too_tall = arguments.max_board_height > 0 and height > arguments.max_board_height
    if too_wide or too_tall:
        width_limit = (
            f"{arguments.max_board_width} cells"
            if arguments.max_board_width > 0
            else "no width limit"
        )
        height_limit = (
            f"{arguments.max_board_height} cells"
            if arguments.max_board_height > 0
            else "no height limit"
        )
        warnings.append(
            f"The layout spans {width}×{height} cells; the reference limits are "
            f"{width_limit} by {height_limit}. A larger board may be harder to "
            "view in one preview."
        )

    by_id = {rect.logical_id: rect for rect in rects}
    for source_id, target_id in edges:
        source = by_id[source_id]
        target = by_id[target_id]
        endpoint_units = (
            {
                cohesive_by_id.get(source_id),
                cohesive_by_id.get(target_id),
            }
            if cohesive_by_id is not None
            else set()
        )
        blockers = [
            rect.logical_id
            for rect in rects
            if rect.logical_id not in {source_id, target_id}
            and (
                cohesive_by_id is None
                or cohesive_by_id.get(rect.logical_id) not in endpoint_units
            )
            and segment_intersects_rect(
                source.center,
                target.center,
                rect,
                arguments.corridor_margin,
            )
        ]
        if blockers:
            warnings.append(
                f"The straight connection from {format_rect(source)} to "
                f"{format_rect(target)} passes through "
                f"{format_rect_list([by_id[blocker] for blocker in blockers])}. "
                "The connection may be harder to follow visually."
            )

    return errors, warnings, (left, top, right, bottom)


def format_rect(rect: Rect) -> str:
    return f"{json.dumps(rect.title, ensure_ascii=False)} ({rect.logical_id})"


def format_rect_list(rects: Sequence[Rect]) -> str:
    return ", ".join(format_rect(rect) for rect in rects)


def count_text(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


def print_validation_report(
    *,
    subject: str,
    source_path: Path,
    item_name: str,
    item_count: int,
    bounds: tuple[int, int, int, int],
    errors: Sequence[str],
    warnings: Sequence[str],
) -> None:
    if errors:
        print(f"The {subject} cannot be used.")
    elif warnings:
        print(
            f"The {subject} is valid with "
            f"{count_text(len(warnings), 'warning')}."
        )
    else:
        print(f"The {subject} is valid.")

    left, top, right, bottom = bounds
    print(
        f"Checked {count_text(item_count, item_name)} from {source_path}. "
        f"The layout covers {right-left}×{bottom-top} cells, from "
        f"({left},{top}) to ({right},{bottom})."
    )
    if errors:
        print("\nErrors:")
        for message in errors:
            print(f"- {message}")
    if warnings:
        print("\nWarnings:")
        for message in warnings:
            print(f"- {message}")
    print(
        f"\nResult: {count_text(len(errors), 'error')} and "
        f"{count_text(len(warnings), 'warning')}."
    )


def command_validate_layout(arguments: argparse.Namespace) -> int:
    run_dir = Path(arguments.run_dir).resolve()
    cards_path = resolve_path(run_dir, arguments.cards, "cards.tsv")
    edges_path = resolve_path(run_dir, arguments.edges, "edges.tsv")
    layout_path = resolve_path(run_dir, arguments.layout, "layout.tsv")
    cards = load_cards(cards_path)
    ids = {card.logical_id for card in cards}
    edges = load_edges(edges_path, ids)
    positions = load_layout(layout_path, ids)
    cohesive_by_id: dict[str, str] | None = None
    members_path = resolve_path(run_dir, arguments.members, "unit-members.tsv")
    units_path = resolve_path(run_dir, arguments.units, "units.tsv")
    if members_path.is_file() and units_path.is_file():
        units = load_units(units_path, ids)
        members = load_members(members_path, units, cards)
        cohesive_by_id = {member.card_id: member.unit_id for member in members}
    errors, warnings, bounds = validate_geometry(
        cards,
        positions,
        edges,
        arguments,
        cohesive_by_id,
    )
    print_validation_report(
        subject="card layout",
        source_path=layout_path,
        item_name="card",
        item_count=len(cards),
        bounds=bounds,
        errors=errors,
        warnings=warnings,
    )
    return 1 if errors else 0


def command_validate_units(arguments: argparse.Namespace) -> int:
    run_dir = Path(arguments.run_dir).resolve()
    cards = load_cards(resolve_path(run_dir, arguments.cards, "cards.tsv"))
    units_path = resolve_path(run_dir, arguments.units, "units.tsv")
    units = load_units(units_path, {card.logical_id for card in cards})
    unit_ids = {unit.logical_id for unit in units}
    edges = load_edges(
        resolve_path(run_dir, arguments.edges, "unit-edges.tsv"), unit_ids
    )
    layout_path = resolve_path(run_dir, arguments.layout, "unit-layout.tsv")
    positions = load_layout(layout_path, unit_ids)
    errors, warnings, bounds = validate_geometry(
        units,
        positions,
        edges,
        arguments,
    )
    print_validation_report(
        subject="unit layout",
        source_path=layout_path,
        item_name="unit",
        item_count=len(units),
        bounds=bounds,
        errors=errors,
        warnings=warnings,
    )
    return 1 if errors else 0


def command_expand_layout(arguments: argparse.Namespace) -> int:
    run_dir = Path(arguments.run_dir).resolve()
    cards = load_cards(resolve_path(run_dir, arguments.cards, "cards.tsv"))
    card_ids = {card.logical_id for card in cards}
    units = load_units(
        resolve_path(run_dir, arguments.units, "units.tsv"), card_ids
    )
    members = load_members(
        resolve_path(run_dir, arguments.members, "unit-members.tsv"),
        units,
        cards,
    )
    layout_path = resolve_path(run_dir, arguments.layout, "unit-layout.tsv")
    unit_positions = load_layout(
        layout_path,
        {unit.logical_id for unit in units},
    )
    positions = {
        member.card_id: (
            unit_positions[member.unit_id][0] + member.dx,
            unit_positions[member.unit_id][1] + member.dy,
        )
        for member in members
    }
    edges = load_edges(
        resolve_path(run_dir, arguments.edges, "edges.tsv"), card_ids
    )
    cohesive_by_id = {member.card_id: member.unit_id for member in members}
    errors, warnings, bounds = validate_geometry(
        cards,
        positions,
        edges,
        arguments,
        cohesive_by_id,
    )
    print_validation_report(
        subject="expanded card layout",
        source_path=layout_path,
        item_name="card",
        item_count=len(cards),
        bounds=bounds,
        errors=errors,
        warnings=warnings,
    )
    if errors:
        print("No layout was written; any existing output was left unchanged.")
        return 1

    output_path = resolve_path(run_dir, arguments.output, "layout.tsv")
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(["id", "x", "y"])
    for card in cards:
        x, y = positions[card.logical_id]
        writer.writerow([card.logical_id, x, y])
    atomic_write(output_path, output.getvalue())
    print(f"Wrote the expanded card layout to {output_path}.")
    return 0


def command_build_batch(arguments: argparse.Namespace) -> int:
    run_dir = Path(arguments.run_dir).resolve()
    cards_path = resolve_path(run_dir, arguments.cards, "cards.tsv")
    layout_path = resolve_path(run_dir, arguments.layout, "layout.tsv")
    cards = load_cards(cards_path)
    positions = load_layout(
        layout_path,
        {card.logical_id for card in cards},
    )
    batch = encode_create_cards(
        CreateCardSpec(
            card.card_format,
            positions[card.logical_id][0],
            positions[card.logical_id][1],
            card.width,
            card.height,
        )
        for card in cards
    ).decode("ascii")
    outputs = arguments.output or ["work/create.cards"]
    resolved_outputs: list[Path] = []
    for output in outputs:
        path = resolve_path(run_dir, output, "work/create.cards")
        if path in resolved_outputs:
            raise MindMapInputError(f"duplicate output path {path}")
        atomic_write(path, batch)
        resolved_outputs.append(path)
        print(f"BUILT output={path} cards={len(cards)}")
    return 0


def add_geometry_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--horizontal-gap", type=int, default=6)
    command.add_argument("--vertical-gap", type=int, default=4)
    command.add_argument("--group-area-ratio", type=float, default=7.0)
    command.add_argument("--max-board-width", type=int, default=650)
    command.add_argument("--max-board-height", type=int, default=450)
    command.add_argument("--corridor-margin", type=int, default=1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile and validate format-first whiteboard artifacts.",
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare",
        help="compile native and renderer units into deterministic artifacts",
        allow_abbrev=False,
    )
    prepare.add_argument("--run-dir", required=True)
    prepare.add_argument(
        "--plan",
        help="plan path, relative to --run-dir unless absolute",
    )
    prepare.add_argument(
        "--check-only",
        action="store_true",
        help="validate and size without writing artifacts",
    )
    prepare.set_defaults(handler=command_prepare)

    validate = subparsers.add_parser(
        "validate-layout",
        help="validate layout.tsv schema and geometry",
        allow_abbrev=False,
    )
    validate.add_argument("--run-dir", required=True)
    validate.add_argument("--cards", help="cards TSV relative to --run-dir")
    validate.add_argument("--edges", help="edges TSV relative to --run-dir")
    validate.add_argument("--layout", help="layout TSV relative to --run-dir")
    validate.add_argument("--units", help="units TSV relative to --run-dir")
    validate.add_argument("--members", help="unit-members TSV relative to --run-dir")
    add_geometry_arguments(validate)
    validate.set_defaults(handler=command_validate_layout)

    validate_units = subparsers.add_parser(
        "validate-units",
        help="validate outer unit-layout.tsv geometry",
        allow_abbrev=False,
    )
    validate_units.add_argument("--run-dir", required=True)
    validate_units.add_argument("--cards", help="cards TSV relative to --run-dir")
    validate_units.add_argument("--units", help="units TSV relative to --run-dir")
    validate_units.add_argument("--edges", help="unit edges TSV relative to --run-dir")
    validate_units.add_argument("--layout", help="unit layout TSV relative to --run-dir")
    add_geometry_arguments(validate_units)
    validate_units.set_defaults(handler=command_validate_units)

    expand = subparsers.add_parser(
        "expand-layout",
        help="expand unit origins plus locked member offsets into layout.tsv",
        allow_abbrev=False,
    )
    expand.add_argument("--run-dir", required=True)
    expand.add_argument("--cards", help="cards TSV relative to --run-dir")
    expand.add_argument("--units", help="units TSV relative to --run-dir")
    expand.add_argument("--members", help="unit-members TSV relative to --run-dir")
    expand.add_argument("--edges", help="card edges TSV relative to --run-dir")
    expand.add_argument("--layout", help="unit layout TSV relative to --run-dir")
    expand.add_argument("--output", help="output card layout relative to --run-dir")
    add_geometry_arguments(expand)
    expand.set_defaults(handler=command_expand_layout)

    build = subparsers.add_parser(
        "build-batch",
        help="join cards.tsv and layout.tsv into create-cards input",
        allow_abbrev=False,
    )
    build.add_argument("--run-dir", required=True)
    build.add_argument("--cards", help="cards TSV relative to --run-dir")
    build.add_argument("--layout", help="layout TSV relative to --run-dir")
    build.add_argument(
        "--output",
        action="append",
        help=(
            "output path relative to --run-dir; repeat for multiple identical "
            "batches; defaults to work/create.cards"
        ),
    )
    build.set_defaults(handler=command_build_batch)
    return parser


def validate_cli_values(arguments: argparse.Namespace) -> None:
    if arguments.command not in {"validate-layout", "validate-units", "expand-layout"}:
        return
    if arguments.horizontal_gap < 0 or arguments.vertical_gap < 0:
        raise MindMapInputError("clearance thresholds must be non-negative")
    if arguments.group_area_ratio <= 0:
        raise MindMapInputError("--group-area-ratio must be positive")
    if arguments.max_board_width < 0 or arguments.max_board_height < 0:
        raise MindMapInputError("board extent limits must be non-negative")
    if arguments.corridor_margin < 0:
        raise MindMapInputError("--corridor-margin must be non-negative")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        validate_cli_values(arguments)
        return int(arguments.handler(arguments))
    except MindMapInputError as error:
        print("The command could not be completed.", file=sys.stderr)
        print(f"Reason: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
