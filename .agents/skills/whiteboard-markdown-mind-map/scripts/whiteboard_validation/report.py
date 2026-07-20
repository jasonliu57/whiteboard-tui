"""Stable machine-readable and human-readable verification evidence."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import atomic_write
from tools.whiteboard_automation.models import (
    CanonicalSnapshot,
    LiveCard,
    LiveEdge,
    LiveStatus,
)
from .models import ExpectedRun, Issue, PreflightRun


REPORT_SCHEMA = 1
TOOL_VERSION = "1.0.0"


@dataclass(frozen=True)
class ReportOutcome:
    result: str
    verification_digest: str
    report_path: Path
    attestation_path: Path


def check_final_attestation(
    path: Path,
    *,
    artifact_digest: str,
    revision: int,
    dirty: bool,
    current_live_snapshot_sha256: str | None = None,
    current_disk_snapshot_sha256: str | None = None,
) -> list[str]:
    """Return stable reasons why an attestation cannot authorize completion."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return [f"ATTESTATION_UNREADABLE: {error}"]
    if not isinstance(value, dict):
        return ["ATTESTATION_INVALID: top level must be an object"]
    reasons: list[str] = []
    stored_digest = value.get("verification_digest")
    unsigned = dict(value)
    unsigned.pop("verification_digest", None)
    computed_digest = hashlib.sha256(_json_bytes(unsigned)).hexdigest()
    if not isinstance(stored_digest, str) or stored_digest != computed_digest:
        reasons.append("ATTESTATION_DIGEST_MISMATCH")
    if value.get("schema") != REPORT_SCHEMA or value.get("tool_version") != TOOL_VERSION:
        reasons.append("ATTESTATION_TOOL_MISMATCH")
    if value.get("command") != "final" or value.get("result") != "PASS":
        reasons.append("ATTESTATION_NOT_A_FINAL_PASS")
    if value.get("artifact_digest") != artifact_digest:
        reasons.append("ATTESTATION_ARTIFACT_STALE")
    if value.get("revision") != revision:
        reasons.append("ATTESTATION_REVISION_STALE")
    if dirty:
        reasons.append("ATTESTATION_BOARD_DIRTY")
    if value.get("baseline_verified") is not True:
        reasons.append("ATTESTATION_BASELINE_UNVERIFIED")
    if not isinstance(value.get("baseline_snapshot_sha256"), str):
        reasons.append("ATTESTATION_BASELINE_UNBOUND")
    live_digest = value.get("live_snapshot_sha256")
    disk_digest = value.get("disk_snapshot_sha256")
    if not isinstance(live_digest, str) or live_digest != disk_digest:
        reasons.append("ATTESTATION_PERSISTENCE_UNVERIFIED")
    if (
        current_live_snapshot_sha256 is not None
        and live_digest != current_live_snapshot_sha256
    ):
        reasons.append("ATTESTATION_LIVE_SNAPSHOT_STALE")
    if (
        current_disk_snapshot_sha256 is not None
        and disk_digest != current_disk_snapshot_sha256
    ):
        reasons.append("ATTESTATION_DISK_SNAPSHOT_STALE")
    if (
        current_live_snapshot_sha256 is not None
        and current_disk_snapshot_sha256 is not None
        and current_live_snapshot_sha256 != current_disk_snapshot_sha256
    ):
        reasons.append("ATTESTATION_CURRENT_PERSISTENCE_MISMATCH")
    return reasons


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    atomic_write(path, _json_bytes(value).decode("utf-8"))


def _result(issues: list[Issue]) -> str:
    if any(issue.severity == "error" for issue in issues):
        return "FAIL"
    if issues:
        return "PASS_WITH_UNVERIFIABLE"
    return "PASS"


def write_preflight_report(
    preflight: PreflightRun,
    issues: list[Issue],
    geometry_output: str,
) -> ReportOutcome:
    directory = preflight.run_dir / "work" / "verification"
    directory.mkdir(parents=True, exist_ok=True)
    result = _result(issues)
    expected = {
        "schema": REPORT_SCHEMA,
        "artifact_digest": preflight.artifact_digest,
        "cards": [
            {
                "logical_id": logical_id,
                "format": card_format,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "payload": str(payload_path.relative_to(preflight.run_dir)),
                "payload_bytes": len(payload),
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
            }
            for logical_id, card_format, x, y, width, height, payload_path, payload
            in preflight.cards
        ],
        "edges": [{"from": source, "to": target} for source, target in preflight.edges],
    }
    _write_json(directory / "expected.json", expected)
    report = {
        "schema": REPORT_SCHEMA,
        "tool_version": TOOL_VERSION,
        "command": "preflight",
        "result": result,
        "artifact_digest": preflight.artifact_digest,
        "issues": [issue.as_dict() for issue in issues],
        "geometry_output": geometry_output,
    }
    report_path = directory / "report.json"
    _write_json(report_path, report)
    markdown = [
        "# Whiteboard preflight verification",
        "",
        f"- Result: `{result}`",
        f"- Artifact digest: `{preflight.artifact_digest}`",
        f"- Cards: {len(preflight.cards)}",
        f"- Declared edges: {len(preflight.edges)}",
        "",
        "## Issues",
        "",
    ]
    markdown.extend(
        [f"- `{issue.code}` ({issue.severity}): {issue.message}" for issue in issues]
        or ["- None"]
    )
    markdown.extend(
        [
            "",
            "## Geometry",
            "",
            "```text",
            geometry_output.rstrip(),
            "```",
        ]
    )
    atomic_write(directory / "report.md", "\n".join(markdown) + "\n")
    attestation = {
        "schema": REPORT_SCHEMA,
        "tool_version": TOOL_VERSION,
        "command": "preflight",
        "result": result,
        "artifact_digest": preflight.artifact_digest,
    }
    verification_digest = hashlib.sha256(_json_bytes(attestation)).hexdigest()
    attestation["verification_digest"] = verification_digest
    attestation_path = directory / "attestation.json"
    _write_json(attestation_path, attestation)
    return ReportOutcome(result, verification_digest, report_path, attestation_path)


def _card_rows(
    expected: ExpectedRun,
    live_cards: dict[int, LiveCard],
) -> str:
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(
        [
            "id",
            "card_id",
            "metadata",
            "payload",
            "expected_bytes",
            "actual_bytes",
            "detail",
        ]
    )
    for card in expected.cards:
        live = live_cards.get(card.card_id)
        if live is None:
            writer.writerow([card.logical_id, card.card_id, "MISSING", "MISSING", len(card.payload), 0, "missing card"])
            continue
        metadata_ok = (
            card.card_format,
            card.x,
            card.y,
            card.width,
            card.height,
        ) == (
            live.card_format,
            live.x,
            live.y,
            live.width,
            live.height,
        )
        payload_ok = card.payload == live.payload
        writer.writerow(
            [
                card.logical_id,
                card.card_id,
                "OK" if metadata_ok else "FAIL",
                "OK" if payload_ok else "FAIL",
                len(card.payload),
                len(live.payload),
                "" if metadata_ok and payload_ok else "see report.json",
            ]
        )
    return output.getvalue()


def _edge_rows(expected: ExpectedRun, live_edges: dict[int, LiveEdge]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(["from", "to", "expected", "edge_id", "actual", "verification"])
    for edge in expected.edges:
        matching = [
            item.edge_id
            for item in live_edges.values()
            if item.source_card_id == edge.source_card_id
            and item.target_card_id == edge.target_card_id
        ]
        actual = "YES" if matching else "NO"
        wanted = "YES" if edge.expected_present else "NO"
        exact = (
            edge.expected_present
            and edge.expected_edge_id in matching
            and len(matching) == 1
        ) or (not edge.expected_present and not matching)
        writer.writerow(
            [
                edge.source_logical_id,
                edge.target_logical_id,
                wanted,
                "" if edge.expected_edge_id is None else edge.expected_edge_id,
                actual,
                "OK" if exact else "FAIL",
            ]
        )
    return output.getvalue()


def write_final_report(
    expected: ExpectedRun,
    status: LiveStatus,
    live_cards: dict[int, LiveCard],
    live_edges: dict[int, LiveEdge],
    issues: list[Issue],
    *,
    live_snapshot: CanonicalSnapshot | None,
    disk_snapshot: CanonicalSnapshot | None,
    baseline_snapshot: CanonicalSnapshot | None,
    png: dict[str, int | str] | None,
) -> ReportOutcome:
    directory = expected.run_dir / "work" / "verification"
    directory.mkdir(parents=True, exist_ok=True)
    result = _result(issues)
    expected_json = {
        "schema": REPORT_SCHEMA,
        "artifact_digest": expected.artifact_digest,
        "cards": [
            {
                "logical_id": card.logical_id,
                "card_id": card.card_id,
                "format": card.card_format,
                "x": card.x,
                "y": card.y,
                "width": card.width,
                "height": card.height,
                "payload_bytes": len(card.payload),
                "payload_sha256": hashlib.sha256(card.payload).hexdigest(),
            }
            for card in expected.cards
        ],
        "edges": [
            {
                "from": edge.source_logical_id,
                "to": edge.target_logical_id,
                "source_card_id": edge.source_card_id,
                "target_card_id": edge.target_card_id,
                "expected_present": edge.expected_present,
                "expected_edge_id": edge.expected_edge_id,
                "recorded_error": edge.recorded_error,
            }
            for edge in expected.edges
        ],
    }
    live_json = {
        "schema": REPORT_SCHEMA,
        "revision": status.revision,
        "cards": [
            {
                "card_id": card.card_id,
                "format": card.card_format,
                "x": card.x,
                "y": card.y,
                "width": card.width,
                "height": card.height,
                "payload_bytes": len(card.payload),
                "payload_sha256": hashlib.sha256(card.payload).hexdigest(),
            }
            for card in sorted(live_cards.values(), key=lambda item: item.card_id)
        ],
        "edges": [
            {
                "edge_id": edge.edge_id,
                "source_card_id": edge.source_card_id,
                "target_card_id": edge.target_card_id,
                "source_side": edge.source_side,
                "target_side": edge.target_side,
                "mode": edge.mode,
                "state": edge.state,
            }
            for edge in sorted(live_edges.values(), key=lambda item: item.edge_id)
        ],
        "snapshot_sha256": live_snapshot.digest if live_snapshot else None,
    }
    _write_json(directory / "expected.json", expected_json)
    _write_json(directory / "live.json", live_json)
    atomic_write(directory / "cards.tsv", _card_rows(expected, live_cards))
    atomic_write(directory / "edges.tsv", _edge_rows(expected, live_edges))
    report = {
        "schema": REPORT_SCHEMA,
        "tool_version": TOOL_VERSION,
        "command": "final",
        "result": result,
        "artifact_digest": expected.artifact_digest,
        "revision": status.revision,
        "status": {
            "cards": status.live_cards,
            "edges": status.live_edges,
            "dirty": status.dirty,
        },
        "baseline_present": baseline_snapshot is not None,
        "baseline_snapshot_sha256": baseline_snapshot.digest if baseline_snapshot else None,
        "live_snapshot_sha256": live_snapshot.digest if live_snapshot else None,
        "disk_snapshot_sha256": disk_snapshot.digest if disk_snapshot else None,
        "png": png,
        "issues": [issue.as_dict() for issue in issues],
    }
    report_path = directory / "report.json"
    _write_json(report_path, report)
    markdown = [
        "# Whiteboard final verification",
        "",
        f"- Result: `{result}`",
        f"- Revision: {status.revision}",
        f"- Artifact digest: `{expected.artifact_digest}`",
        f"- Live cards/edges: {status.live_cards}/{status.live_edges}",
        f"- Dirty: {int(status.dirty)}",
        f"- Baseline: {'present' if baseline_snapshot is not None else 'missing'}",
        "",
        "## Issues",
        "",
    ]
    markdown.extend(
        [f"- `{issue.code}` ({issue.severity}): {issue.message}" for issue in issues]
        or ["- None"]
    )
    atomic_write(directory / "report.md", "\n".join(markdown) + "\n")
    attestation = {
        "schema": REPORT_SCHEMA,
        "tool_version": TOOL_VERSION,
        "command": "final",
        "result": result,
        "artifact_digest": expected.artifact_digest,
        "revision": status.revision,
        "baseline_verified": baseline_snapshot is not None and not any(
            issue.code.startswith("UNRELATED_") or issue.code.startswith("BASELINE_")
            for issue in issues
        ),
        "baseline_snapshot_sha256": baseline_snapshot.digest if baseline_snapshot else None,
        "live_snapshot_sha256": live_snapshot.digest if live_snapshot else None,
        "disk_snapshot_sha256": disk_snapshot.digest if disk_snapshot else None,
    }
    verification_digest = hashlib.sha256(_json_bytes(attestation)).hexdigest()
    attestation["verification_digest"] = verification_digest
    attestation_path = directory / "attestation.json"
    _write_json(attestation_path, attestation)
    return ReportOutcome(result, verification_digest, report_path, attestation_path)
