"""Shared artifact contracts used by the compiler and final verifier."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from tools.whiteboard_automation.generated_card_formats import CARD_FORMATS
from tools.whiteboard_automation.files import atomic_write, atomic_write_bytes

from .models import ExpectedCard, ExpectedEdge, ExpectedRun, PreflightRun


LOGICAL_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")
UNIT_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True)
class FormatSpec:
    minimum: tuple[int, int]
    maximum: tuple[int, int]
    extension: str


FORMAT_EXTENSIONS = {
    "note": ".txt",
    "markdown": ".md",
    "code": ".txt",
    "todo": ".todo",
    "csv": ".csv",
    "folder": ".folder.md",
    "text-art": ".txt",
}

FORMATS = {
    name: FormatSpec(tuple(contract["minimum"]), tuple(contract["maximum"]), FORMAT_EXTENSIONS[name])
    for name, contract in CARD_FORMATS.items()
}



@dataclass(frozen=True)
class CardRow:
    logical_id: str
    index: int
    card_format: str
    width: int
    height: int
    group: str
    title: str
    payload: str


@dataclass(frozen=True)
class UnitRow:
    logical_id: str
    index: int
    kind: str
    renderer: str
    width: int
    height: int
    group: str
    title: str
    anchor: str


@dataclass(frozen=True)
class MemberRow:
    unit_id: str
    card_id: str
    dx: int
    dy: int


class MindMapInputError(Exception):
    """Raised when a run artifact violates the mind-map contract."""


def resolve_path(run_dir: Path, value: str | None, default: str) -> Path:
    path = Path(value) if value is not None else Path(default)
    if not path.is_absolute():
        path = run_dir / path
    return path.resolve()


def resolve_run_path(
    run_dir: Path,
    value: str | Path,
    *,
    context: str,
    require_regular: bool = True,
) -> Path:
    """Resolve a verifier-owned path and reject traversal or symlink escape."""

    root = run_dir.resolve()
    candidate = Path(value)
    if candidate.is_absolute():
        raise MindMapInputError(f"{context}: absolute paths are not allowed")
    resolved = (root / candidate).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise MindMapInputError(f"{context}: path escapes run directory") from error
    if require_regular and not resolved.is_file():
        raise MindMapInputError(f"{context}: expected a regular file at {resolved}")
    return resolved


def read_tsv(path: Path, header: list[str]) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            if reader.fieldnames != header:
                raise MindMapInputError(
                    f"{path}: expected TSV header {header}, got {reader.fieldnames}"
                )
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as error:
        raise MindMapInputError(f"{path}: {error}") from error

    for number, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            raise MindMapInputError(f"{path}:{number}: malformed TSV row")
    return rows


def parse_integer(value: str, context: str) -> int:
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value) is None or value == "-0":
        raise MindMapInputError(f"{context}: expected canonical integer, got {value!r}")
    return int(value)


def load_cards(path: Path) -> list[CardRow]:
    rows = read_tsv(
        path,
        ["id", "index", "format", "width", "height", "group", "title", "payload"],
    )
    cards: list[CardRow] = []
    ids: set[str] = set()
    for expected_index, row in enumerate(rows):
        logical_id = row["id"]
        if not LOGICAL_ID_PATTERN.fullmatch(logical_id):
            raise MindMapInputError(f"{path}: invalid logical ID {logical_id!r}")
        if logical_id in ids:
            raise MindMapInputError(f"{path}: duplicate logical ID {logical_id}")
        ids.add(logical_id)
        index = parse_integer(row["index"], f"{logical_id}.index")
        if index != expected_index:
            raise MindMapInputError(f"{path}: expected index {expected_index}, got {index}")
        card_format = row["format"]
        if card_format not in FORMATS:
            raise MindMapInputError(f"{path}: unsupported format {card_format!r}")
        width = parse_integer(row["width"], f"{logical_id}.width")
        height = parse_integer(row["height"], f"{logical_id}.height")
        spec = FORMATS[card_format]
        if not (spec.minimum[0] <= width <= spec.maximum[0]):
            raise MindMapInputError(
                f"{logical_id}: width {width} outside {spec.minimum[0]}..{spec.maximum[0]}"
            )
        if not (spec.minimum[1] <= height <= spec.maximum[1]):
            raise MindMapInputError(
                f"{logical_id}: height {height} outside {spec.minimum[1]}..{spec.maximum[1]}"
            )
        cards.append(CardRow(logical_id, index, card_format, width, height, row["group"], row["title"], row["payload"]))
    if not cards:
        raise MindMapInputError(f"{path}: no cards")
    return cards


def load_units(path: Path, card_ids: set[str]) -> list[UnitRow]:
    rows = read_tsv(
        path,
        ["id", "index", "kind", "renderer", "width", "height", "group", "title", "anchor"],
    )
    units: list[UnitRow] = []
    ids: set[str] = set()
    for expected_index, row in enumerate(rows):
        logical_id = row["id"]
        if not UNIT_ID_PATTERN.fullmatch(logical_id) or logical_id in ids:
            raise MindMapInputError(f"{path}: invalid or duplicate unit ID {logical_id!r}")
        ids.add(logical_id)
        index = parse_integer(row["index"], f"{logical_id}.index")
        if index != expected_index:
            raise MindMapInputError(f"{path}: expected unit index {expected_index}, got {index}")
        kind = row["kind"]
        renderer = row["renderer"]
        if kind not in {"native", "renderer"}:
            raise MindMapInputError(f"{logical_id}: invalid unit kind {kind!r}")
        if (kind == "native" and renderer != "-") or (kind == "renderer" and not UNIT_ID_PATTERN.fullmatch(renderer)):
            raise MindMapInputError(f"{logical_id}: invalid renderer identity {renderer!r}")
        width = parse_integer(row["width"], f"{logical_id}.width")
        height = parse_integer(row["height"], f"{logical_id}.height")
        if not 1 <= width <= 1_000_000 or not 1 <= height <= 1_000_000:
            raise MindMapInputError(f"{logical_id}: invalid unit bounds {width}x{height}")
        anchor = row["anchor"]
        if anchor not in card_ids:
            raise MindMapInputError(f"{logical_id}: unknown anchor card {anchor!r}")
        units.append(UnitRow(logical_id, index, kind, renderer, width, height, row["group"], row["title"], anchor))
    if not units:
        raise MindMapInputError(f"{path}: no units")
    return units


def load_members(path: Path, units: list[UnitRow], cards: list[CardRow]) -> list[MemberRow]:
    rows = read_tsv(path, ["unit", "card", "dx", "dy"])
    units_by_id = {unit.logical_id: unit for unit in units}
    cards_by_id = {card.logical_id: card for card in cards}
    members: list[MemberRow] = []
    seen_cards: set[str] = set()
    for row in rows:
        unit_id = row["unit"]
        card_id = row["card"]
        if unit_id not in units_by_id or card_id not in cards_by_id:
            raise MindMapInputError(f"{path}: unknown membership {unit_id!r}->{card_id!r}")
        if card_id in seen_cards:
            raise MindMapInputError(f"{path}: duplicate member card {card_id!r}")
        seen_cards.add(card_id)
        dx = parse_integer(row["dx"], f"{card_id}.dx")
        dy = parse_integer(row["dy"], f"{card_id}.dy")
        card = cards_by_id[card_id]
        unit = units_by_id[unit_id]
        if dx < 0 or dy < 0 or dx + card.width > unit.width or dy + card.height > unit.height:
            raise MindMapInputError(f"{path}: member {card_id!r} lies outside unit {unit_id!r}")
        members.append(MemberRow(unit_id, card_id, dx, dy))
    missing = sorted(set(cards_by_id) - seen_cards)
    if missing:
        raise MindMapInputError(f"{path}: cards without a unit: {missing}")
    member_unit = {member.card_id: member.unit_id for member in members}
    for unit in units:
        if member_unit.get(unit.anchor) != unit.logical_id:
            raise MindMapInputError(f"{path}: anchor {unit.anchor!r} is not a member of {unit.logical_id!r}")
    return members


def load_edges(path: Path, ids: set[str]) -> list[tuple[str, str]]:
    rows = read_tsv(path, ["from", "to"])
    edges: list[tuple[str, str]] = []
    edge_set: set[tuple[str, str]] = set()
    for row in rows:
        source = row["from"]
        target = row["to"]
        if source not in ids or target not in ids:
            raise MindMapInputError(f"{path}: unknown connection endpoint {source}->{target}")
        if source == target:
            raise MindMapInputError(f"{path}: self connection {source}->{target}")
        pair = (source, target)
        if pair in edge_set:
            raise MindMapInputError(f"{path}: duplicate connection {source}->{target}")
        edge_set.add(pair)
        edges.append(pair)
    return edges


def load_layout(path: Path, ids: set[str]) -> dict[str, tuple[int, int]]:
    rows = read_tsv(path, ["id", "x", "y"])
    positions: dict[str, tuple[int, int]] = {}
    for row in rows:
        logical_id = row["id"]
        if logical_id in positions:
            raise MindMapInputError(f"{path}: duplicate layout ID {logical_id}")
        positions[logical_id] = (
            parse_integer(row["x"], f"{logical_id}.x"),
            parse_integer(row["y"], f"{logical_id}.y"),
        )
    missing = sorted(ids - set(positions))
    unknown = sorted(set(positions) - ids)
    if missing or unknown:
        raise MindMapInputError(f"{path}: layout ID mismatch: missing={missing}, unknown={unknown}")
    return positions


def load_state(path: Path) -> dict[str, str]:
    rows = read_tsv(path, ["key", "value"])
    state: dict[str, str] = {}
    for row in rows:
        key = row["key"]
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise MindMapInputError(f"{path}: invalid state key {key!r}")
        if key in state:
            raise MindMapInputError(f"{path}: duplicate state key {key!r}")
        state[key] = row["value"]
    return state


def load_card_map(path: Path, logical_ids: set[str]) -> dict[str, int]:
    rows = read_tsv(path, ["id", "card_id"])
    result: dict[str, int] = {}
    used: set[int] = set()
    for row in rows:
        logical_id = row["id"]
        if logical_id not in logical_ids:
            raise MindMapInputError(f"{path}: unknown logical ID {logical_id!r}")
        if logical_id in result:
            raise MindMapInputError(f"{path}: duplicate logical ID {logical_id!r}")
        card_id = parse_integer(row["card_id"], f"{logical_id}.card_id")
        if card_id < 0:
            raise MindMapInputError(f"{path}: negative CardId {card_id}")
        if card_id in used:
            raise MindMapInputError(f"{path}: duplicate CardId {card_id}")
        result[logical_id] = card_id
        used.add(card_id)
    missing = sorted(logical_ids - set(result))
    if missing:
        raise MindMapInputError(f"{path}: missing mappings for {missing}")
    return result


@dataclass(frozen=True)
class EdgeResultRow:
    source: str
    target: str
    status: str
    edge_id: int | None
    error: str | None


def load_edge_results(
    path: Path,
    declared: list[tuple[str, str]],
) -> list[EdgeResultRow]:
    rows = read_tsv(path, ["from", "to", "status", "edge_id", "error"])
    declared_set = set(declared)
    result: list[EdgeResultRow] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        pair = (row["from"], row["to"])
        if pair not in declared_set:
            raise MindMapInputError(f"{path}: undeclared edge {pair[0]}->{pair[1]}")
        if pair in seen:
            raise MindMapInputError(f"{path}: duplicate result {pair[0]}->{pair[1]}")
        seen.add(pair)
        status = row["status"]
        if status == "OK":
            edge_id = parse_integer(row["edge_id"], f"{pair[0]}->{pair[1]}.edge_id")
            if edge_id < 0 or row["error"]:
                raise MindMapInputError(f"{path}: malformed OK result {pair[0]}->{pair[1]}")
            result.append(EdgeResultRow(*pair, status, edge_id, None))
        elif status == "ERROR":
            if row["edge_id"] or not row["error"]:
                raise MindMapInputError(f"{path}: malformed ERROR result {pair[0]}->{pair[1]}")
            result.append(EdgeResultRow(*pair, status, None, row["error"]))
        else:
            raise MindMapInputError(f"{path}: invalid edge status {status!r}")
    missing = [pair for pair in declared if pair not in seen]
    if missing:
        raise MindMapInputError(f"{path}: missing edge results {missing}")
    return result


def resolve_folder_payload(
    payload: bytes,
    *,
    logical_id: str,
    unit_anchors: dict[str, str],
    card_map: dict[str, int],
) -> bytes:
    """Resolve a canonical Folder exchange payload without text re-encoding drift."""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MindMapInputError(f"{logical_id}: folder payload is not UTF-8") from error
    lines = text.splitlines()
    if not lines or not lines[0].startswith("ROOT\t"):
        raise MindMapInputError(
            f"{logical_id}: folder payload must begin with ROOT<TAB>name"
        )
    output = [lines[0]]
    for number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t", 4)
        if len(fields) != 5:
            raise MindMapInputError(
                f"{logical_id}: folder line {number} must have five tab-separated fields"
            )
        depth, kind, target, collapsed, name = fields
        if not depth.isascii() or not depth.isdecimal():
            raise MindMapInputError(f"{logical_id}: folder line {number} has invalid depth")
        if collapsed not in {"0", "1"}:
            raise MindMapInputError(
                f"{logical_id}: folder line {number} has invalid collapsed flag"
            )
        if kind == "DIR":
            if target != "-":
                raise MindMapInputError(
                    f"{logical_id}: folder DIR line {number} must use target '-'"
                )
        elif kind == "CARD":
            if collapsed != "0" or not target.startswith("@"):
                raise MindMapInputError(
                    f"{logical_id}: folder CARD line {number} must use @UNIT-ID and collapsed=0"
                )
            unit_id = target[1:]
            anchor = unit_anchors.get(unit_id)
            if anchor is None or anchor not in card_map:
                raise MindMapInputError(
                    f"{logical_id}: folder line {number} has unresolved target {target!r}"
                )
            fields[2] = str(card_map[anchor])
        else:
            raise MindMapInputError(
                f"{logical_id}: folder line {number} has invalid kind {kind!r}"
            )
        output.append("\t".join((fields[0], fields[1], fields[2], fields[3], name)))
    return ("\n".join(output) + "\n").encode("utf-8")


def resolve_materialized_payloads(
    run_dir: Path,
    cards: list[CardRow],
    card_map: dict[str, int],
) -> dict[str, bytes]:
    raw_payloads = {
        card.logical_id: _payload_bytes(run_dir, card)[1]
        for card in cards
    }
    if not any(card.card_format == "folder" for card in cards):
        return raw_payloads
    card_ids = {card.logical_id for card in cards}
    units = load_units(
        resolve_run_path(run_dir, "units.tsv", context="units.tsv"),
        card_ids,
    )
    load_members(
        resolve_run_path(run_dir, "unit-members.tsv", context="unit-members.tsv"),
        units,
        cards,
    )
    anchors = {unit.logical_id: unit.anchor for unit in units}
    return {
        card.logical_id: (
            resolve_folder_payload(
                raw_payloads[card.logical_id],
                logical_id=card.logical_id,
                unit_anchors=anchors,
                card_map=card_map,
            )
            if card.card_format == "folder"
            else raw_payloads[card.logical_id]
        )
        for card in cards
    }


def _payload_bytes(run_dir: Path, card: CardRow) -> tuple[Path, bytes]:
    path = resolve_run_path(run_dir, card.payload, context=f"{card.logical_id}.payload")
    try:
        data = path.read_bytes()
        data.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise MindMapInputError(f"{path}: invalid UTF-8 payload: {error}") from error
    return path, data


def _artifact_digest(
    run_dir: Path,
    names: list[str],
    payloads: list[tuple[str, bytes]],
    state: dict[str, str],
) -> str:
    digest = hashlib.sha256()
    digest.update(b"WHITEBOARD-ARTIFACTS 1\0")
    for name in names:
        path = resolve_run_path(run_dir, name, context=name)
        data = path.read_bytes()
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    for logical_id, data in payloads:
        encoded = logical_id.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    stable_state = {
        key: state[key]
        for key in ("source", "board_file", "socket")
        if key in state
    }
    encoded_state = json.dumps(
        stable_state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest.update(len(encoded_state).to_bytes(8, "big"))
    digest.update(encoded_state)
    return digest.hexdigest()


def load_preflight_run(run_dir: Path) -> PreflightRun:
    root = run_dir.resolve()
    cards = load_cards(resolve_run_path(root, "cards.tsv", context="cards.tsv"))
    ids = {card.logical_id for card in cards}
    layout = load_layout(resolve_run_path(root, "layout.tsv", context="layout.tsv"), ids)
    edges = load_edges(resolve_run_path(root, "edges.tsv", context="edges.tsv"), ids)
    state_path = resolve_run_path(root, "state.tsv", context="state.tsv")
    state = load_state(state_path)
    compiled: list[tuple[str, str, int, int, int, int, Path, bytes]] = []
    payloads: list[tuple[str, bytes]] = []
    for card in cards:
        path, data = _payload_bytes(root, card)
        x, y = layout[card.logical_id]
        compiled.append(
            (card.logical_id, card.card_format, x, y, card.width, card.height, path, data)
        )
        payloads.append((card.logical_id, data))
    artifact_names = ["cards.tsv", "layout.tsv", "edges.tsv"]
    if any(card.card_format == "folder" for card in cards):
        units = load_units(
            resolve_run_path(root, "units.tsv", context="units.tsv"),
            ids,
        )
        load_members(
            resolve_run_path(root, "unit-members.tsv", context="unit-members.tsv"),
            units,
            cards,
        )
        anchors = {unit.logical_id: unit.anchor for unit in units}
        placeholder_map = {card.logical_id: card.index for card in cards}
        raw_by_id = dict(payloads)
        for card in cards:
            if card.card_format == "folder":
                resolve_folder_payload(
                    raw_by_id[card.logical_id],
                    logical_id=card.logical_id,
                    unit_anchors=anchors,
                    card_map=placeholder_map,
                )
        artifact_names.extend(["units.tsv", "unit-members.tsv"])
    return PreflightRun(
        run_dir=root,
        cards=tuple(compiled),
        edges=tuple(edges),
        state=state,
        artifact_digest=_artifact_digest(
            root,
            artifact_names,
            payloads,
            state,
        ),
    )


def load_expected_run(run_dir: Path) -> ExpectedRun:
    preflight = load_preflight_run(run_dir)
    root = preflight.run_dir
    logical_ids = {card[0] for card in preflight.cards}
    card_map = load_card_map(
        resolve_run_path(root, "card-map.tsv", context="card-map.tsv"),
        logical_ids,
    )
    declared = list(preflight.edges)
    results = load_edge_results(
        resolve_run_path(root, "edge-results.tsv", context="edge-results.tsv"),
        declared,
    )
    source_cards = load_cards(resolve_run_path(root, "cards.tsv", context="cards.tsv"))
    materialized_payloads = resolve_materialized_payloads(root, source_cards, card_map)
    expected_cards = tuple(
        ExpectedCard(
            logical_id=logical_id,
            card_id=card_map[logical_id],
            card_format=card_format,
            x=x,
            y=y,
            width=width,
            height=height,
            payload_path=payload_path,
            payload=materialized_payloads[logical_id],
        )
        for logical_id, card_format, x, y, width, height, payload_path, payload
        in preflight.cards
    )
    expected_edges = tuple(
        ExpectedEdge(
            source_logical_id=row.source,
            target_logical_id=row.target,
            source_card_id=card_map[row.source],
            target_card_id=card_map[row.target],
            expected_present=row.status == "OK",
            expected_edge_id=row.edge_id,
            recorded_error=row.error,
        )
        for row in results
    )
    payloads = [(card[0], card[7]) for card in preflight.cards]
    artifact_names = [
        "cards.tsv",
        "layout.tsv",
        "card-map.tsv",
        "edges.tsv",
        "edge-results.tsv",
    ]
    if any(card.card_format == "folder" for card in source_cards):
        artifact_names.extend(["units.tsv", "unit-members.tsv"])
    return ExpectedRun(
        run_dir=root,
        cards=expected_cards,
        edges=expected_edges,
        state=preflight.state,
        artifact_digest=_artifact_digest(
            root,
            artifact_names,
            payloads,
            preflight.state,
        ),
    )
