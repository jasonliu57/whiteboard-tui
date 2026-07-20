"""Persistence paths, PNG checks, and atomic state checkpoints."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from .artifacts import MindMapInputError, atomic_write, load_state
from .models import Issue
from tools.whiteboard_automation.errors import ProtocolError
from tools.whiteboard_automation.models import CanonicalSnapshot
from tools.whiteboard_automation.snapshot import parse_canonical_snapshot


def resolve_board_path(
    state: dict[str, str],
    repository_root: Path,
    *,
    require_regular: bool = True,
) -> Path:
    raw = state.get("board_file")
    if not raw:
        raise MindMapInputError("state.tsv: missing board_file")
    path = Path(raw)
    if not path.is_absolute():
        path = repository_root / path
    resolved = path.resolve(strict=False)
    if require_regular and not resolved.is_file():
        raise MindMapInputError(f"board file is not a regular file: {resolved}")
    return resolved


def paths_are_same(first: Path, second: Path) -> bool:
    """Compare existing identities when possible, then normalized paths."""

    try:
        if first.exists() and second.exists() and first.samefile(second):
            return True
    except OSError:
        pass
    return first.resolve(strict=False) == second.resolve(strict=False)


def require_snapshot_output_distinct(board_path: Path, output_path: Path) -> None:
    if paths_are_same(board_path, output_path):
        raise MindMapInputError(
            f"snapshot output must differ from board file: {board_path}"
        )


def load_baseline_evidence(
    run_dir: Path,
    *,
    required: bool = False,
) -> tuple[CanonicalSnapshot, int, str] | None:
    """Load and cross-check the snapshot, digest, counts, and metadata."""

    directory = run_dir / "work" / "verification"
    snapshot_path = directory / "baseline.snapshot"
    metadata_path = directory / "baseline.json"
    snapshot_exists = snapshot_path.is_file()
    metadata_exists = metadata_path.is_file()
    if not snapshot_exists and not metadata_exists:
        if required:
            raise MindMapInputError("pre-mutation baseline evidence is missing")
        return None
    if not snapshot_exists or not metadata_exists:
        raise MindMapInputError(
            "baseline evidence is incomplete; baseline.snapshot and baseline.json "
            "must both exist"
        )
    try:
        snapshot = parse_canonical_snapshot(snapshot_path.read_bytes())
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ProtocolError) as error:
        raise MindMapInputError(f"invalid baseline evidence: {error}") from error
    expected = {
        "schema": 1,
        "sha256": snapshot.digest,
        "card_slots": snapshot.card_slots,
        "cards": snapshot.live_cards,
        "edge_slots": snapshot.edge_slots,
        "edges": snapshot.live_edges,
        "glyphs": snapshot.glyph_count,
    }
    if not isinstance(metadata, dict) or any(
        metadata.get(key) != value for key, value in expected.items()
    ):
        raise MindMapInputError("baseline.json does not match baseline.snapshot")
    revision = metadata.get("revision")
    artifact_digest = metadata.get("artifact_digest")
    if type(revision) is not int or revision < 0 or not isinstance(artifact_digest, str):
        raise MindMapInputError(
            "baseline.json is missing a non-negative revision or artifact digest"
        )
    return snapshot, revision, artifact_digest


def validate_png(data: bytes) -> tuple[list[Issue], dict[str, int | str]]:
    metadata: dict[str, int | str] = {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return [Issue("FINAL_PNG_INVALID", "Final board image is not a valid PNG")], metadata
    width, height = struct.unpack(">II", data[16:24])
    metadata.update({"width": width, "height": height})
    if width == 0 or height == 0:
        return [Issue("FINAL_PNG_EMPTY", "Final board image has zero dimensions")], metadata
    return [], metadata


def update_state(path: Path, updates: dict[str, str]) -> None:
    state = load_state(path)
    order = list(state)
    for key, value in updates.items():
        if key not in state:
            order.append(key)
        state[key] = value
    lines = ["key\tvalue"]
    for key in order:
        value = state[key]
        if "\t" in value or "\n" in value or "\r" in value:
            raise MindMapInputError(f"state value for {key!r} is not TSV-safe")
        lines.append(f"{key}\t{value}")
    atomic_write(path, "\n".join(lines) + "\n")
