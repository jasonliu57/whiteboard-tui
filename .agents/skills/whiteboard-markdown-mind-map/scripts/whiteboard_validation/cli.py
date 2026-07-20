"""Command-line orchestration for deterministic whiteboard verification."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .artifacts import (
    MindMapInputError,
    atomic_write,
    atomic_write_bytes,
    load_expected_run,
    load_preflight_run,
    load_state,
    resolve_run_path,
)
from .compare import (
    compare_baseline,
    compare_cards,
    compare_edges,
    compare_live_and_disk,
    compare_owned_snapshot,
    compare_status,
)
from tools.whiteboard_automation.errors import CtlError, ProtocolError
from tools.whiteboard_automation.client import (
    WhiteboardCtlClient,
    WhiteboardInspectClient,
    resolve_executable,
)
from tools.whiteboard_automation.models import (
    CanonicalSnapshot,
    LiveCard,
    LiveEdge,
)
from .models import Issue, RevisionChangedError
from .materialize import run_materialization
from .persistence import (
    load_baseline_evidence,
    require_snapshot_output_distinct,
    resolve_board_path,
    update_state,
    validate_png,
)
from tools.whiteboard_automation.snapshot import parse_canonical_snapshot
from .report import check_final_attestation, write_final_report, write_preflight_report
from tools.whiteboard_automation.batch import decode_create_cards


EXIT_MISMATCH = 1
EXIT_INPUT = 2
EXIT_ENVIRONMENT = 3
EXIT_REVISION = 4
EXIT_PERSISTENCE = 5


def repository_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "CMakeLists.txt").is_file() and (parent / "src").is_dir():
            return parent
    raise MindMapInputError("cannot locate whiteboard-tui repository root")


def _socket(state: dict[str, str]) -> str:
    value = state.get("socket") or os.environ.get("WHITEBOARD_TUI_SOCKET")
    if not value:
        raise MindMapInputError("state.tsv: missing socket")
    return value


def _geometry_preflight(run_dir: Path) -> tuple[int, str]:
    tool = Path(__file__).resolve().parents[1] / "mindmap_tools.py"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(tool),
                "validate-layout",
                "--run-dir",
                str(run_dir),
                "--layout",
                "layout.tsv",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CtlError(f"layout validator could not run: {error}") from error
    return completed.returncode, completed.stdout.decode("utf-8", errors="replace")


def command_preflight(arguments: argparse.Namespace) -> int:
    preflight = load_preflight_run(Path(arguments.run_dir))
    code, output = _geometry_preflight(preflight.run_dir)
    if code == 2:
        raise MindMapInputError(output.strip() or "layout validator rejected its input")
    issues: list[Issue] = []
    if code != 0:
        issues.append(
            Issue(
                "LAYOUT_VALIDATION_FAILED",
                "Static layout validation failed",
                {"output": output.strip()},
            )
        )
    outcome = write_preflight_report(preflight, issues, output)
    print(
        f"PREFLIGHT result={outcome.result} cards={len(preflight.cards)} "
        f"edges={len(preflight.edges)} digest={preflight.artifact_digest}"
    )
    return 0 if outcome.result != "FAIL" else EXIT_MISMATCH


def _clients(arguments: argparse.Namespace, state: dict[str, str]):
    root = repository_root()
    ctl = resolve_executable(arguments.whiteboardctl)
    inspect = resolve_executable(arguments.whiteboard_inspect)
    return (
        root,
        WhiteboardCtlClient(ctl, _socket(state), arguments.timeout),
        WhiteboardInspectClient(inspect, arguments.timeout),
    )


def _baseline_json(
    snapshot: CanonicalSnapshot,
    revision: int,
    artifact_digest: str,
) -> dict[str, object]:
    return {
        "schema": 1,
        "revision": revision,
        "artifact_digest": artifact_digest,
        "sha256": snapshot.digest,
        "card_slots": snapshot.card_slots,
        "cards": snapshot.live_cards,
        "edge_slots": snapshot.edge_slots,
        "edges": snapshot.live_edges,
        "glyphs": snapshot.glyph_count,
    }


def command_preview(arguments: argparse.Namespace) -> int:
    run_dir = Path(arguments.run_dir).resolve()
    state = load_state(resolve_run_path(run_dir, "state.tsv", context="state.tsv"))
    batch_path = resolve_run_path(run_dir, arguments.batch, context="preview batch")
    try:
        batch = batch_path.read_bytes()
        cards = decode_create_cards(batch)
    except (OSError, ValueError) as error:
        raise MindMapInputError(f"invalid preview batch: {error}") from error

    left = min(card.x for card in cards)
    top = min(card.y for card in cards)
    right = max(card.x + card.width for card in cards)
    bottom = max(card.y + card.height for card in cards)
    ctl_path = resolve_executable(arguments.whiteboardctl)
    client = WhiteboardCtlClient(ctl_path, _socket(state), arguments.timeout)
    before = client.status()
    view = client.view()
    occupied = client.query(left, top, right, bottom, 256)
    if view.revision != before.revision or occupied.revision != before.revision:
        raise RevisionChangedError("live revision changed while the preview area was checked")
    if occupied.cards:
        identifiers = ", ".join(str(card.card_id) for card in occupied.cards)
        raise MindMapInputError(f"preview area contains existing cards: {identifiers}")

    created = client.create_cards(batch, before.revision)
    card_ids = tuple(created.first_card_id + index for index in range(created.count))
    work = run_dir / "work"
    png_path = work / "preview.raw.png"
    try:
        atomic_write(work / "preview.ids", "".join(f"{card_id}\n" for card_id in card_ids))
        if created.count != len(cards):
            raise ProtocolError(
                f"CREATE_CARDS returned {created.count} cards, expected {len(cards)}"
            )
        png_data = client.board_png(png_path, arguments.max_side)
        png_issues, png_metadata = validate_png(png_data)
        if png_issues:
            raise CtlError("board-png returned an invalid PNG")
        current = client.status()
        if current.revision != created.revision:
            raise RevisionChangedError("live revision changed before preview cleanup")
        deleted = client.delete_cards(card_ids, current.revision)
    except BaseException:
        try:
            current = client.status()
            if current.revision == created.revision:
                client.delete_cards(card_ids, current.revision)
        finally:
            raise

    if deleted.count != len(card_ids):
        raise ProtocolError(
            f"DELETE_CARDS removed {deleted.count} cards, expected {len(card_ids)}"
        )
    after = client.status()
    if after.revision != deleted.revision:
        raise RevisionChangedError("live revision changed after preview cleanup")
    if after.cards != before.cards or after.edges != before.edges:
        raise ProtocolError("preview cleanup did not restore the original Board counts")

    result = {
        "schema": 1,
        "bounds": {"left": left, "top": top, "right": right, "bottom": bottom},
        "cards": len(cards),
        "card_ids": list(card_ids),
        "initial_revision": before.revision,
        "created_revision": created.revision,
        "deleted_revision": deleted.revision,
        "png": png_metadata,
        "viewport": {
            "x": view.viewport_x,
            "y": view.viewport_y,
            "width": view.viewport_width,
            "height": view.viewport_height,
        },
    }
    atomic_write(
        work / "preview-result.json",
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        f"PREVIEW cards={len(cards)} bounds={left},{top},{right},{bottom} "
        f"png={png_path} cleanup_revision={deleted.revision}"
    )
    return 0


def command_capture_baseline(arguments: argparse.Namespace) -> int:
    preflight = load_preflight_run(Path(arguments.run_dir))
    root = repository_root()
    ctl_path = resolve_executable(arguments.whiteboardctl)
    client = WhiteboardCtlClient(ctl_path, _socket(preflight.state), arguments.timeout)
    directory = preflight.run_dir / "work" / "verification"
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "baseline.snapshot"
    board_path = resolve_board_path(
        preflight.state,
        root,
        require_regular=False,
    )
    require_snapshot_output_distinct(board_path, output)
    if output.exists() and not arguments.replace_baseline:
        raise MindMapInputError(
            f"baseline already exists at {output}; use --replace-baseline explicitly"
        )
    before = client.status()
    raw = client.snapshot(output)
    after = client.status()
    if before.revision != after.revision:
        raise RevisionChangedError(
            f"baseline revision changed {before.revision}->{after.revision}"
        )
    snapshot = parse_canonical_snapshot(raw)
    metadata = _baseline_json(snapshot, after.revision, preflight.artifact_digest)
    atomic_write(
        directory / "baseline.json",
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )
    print(
        f"BASELINE revision={after.revision} cards={snapshot.live_cards} "
        f"edges={snapshot.live_edges} glyphs={snapshot.glyph_count} sha256={snapshot.digest}"
    )
    return 0


def _read_live_scope(expected, client: WhiteboardCtlClient):
    last_change: RevisionChangedError | None = None
    for _attempt in range(2):
        start = client.status()
        cards: dict[int, LiveCard] = {}
        edges: dict[int, LiveEdge] = {}
        revisions = {start.revision}
        for expected_card in expected.cards:
            try:
                card = client.get_card(expected_card.card_id)
            except CtlError as error:
                if b"ERR missing_card" in error.stderr:
                    continue
                raise
            cards[card.card_id] = card
            revisions.add(card.revision)
        for card_id in sorted(expected.card_ids):
            try:
                response = client.edges(card_id)
            except CtlError as error:
                if b"ERR missing_card" in error.stderr:
                    continue
                raise
            revisions.add(response.revision)
            for edge in response.edges:
                previous = edges.get(edge.edge_id)
                if previous is not None and previous != edge:
                    raise ProtocolError(
                        f"EDGES: edge {edge.edge_id} differs between endpoint responses"
                    )
                edges[edge.edge_id] = edge
        end = client.status()
        revisions.add(end.revision)
        if len(revisions) == 1:
            return end, cards, edges
        last_change = RevisionChangedError(
            f"live revisions changed during verification: {sorted(revisions)}"
        )
    assert last_change is not None
    raise last_change


def _load_baseline(run_dir: Path) -> CanonicalSnapshot | None:
    evidence = load_baseline_evidence(run_dir)
    return evidence[0] if evidence is not None else None


def command_final(arguments: argparse.Namespace) -> int:
    expected = load_expected_run(Path(arguments.run_dir))
    root, client, inspect = _clients(arguments, expected.state)
    status, cards, edges = _read_live_scope(expected, client)
    directory = expected.run_dir / "work" / "verification"
    directory.mkdir(parents=True, exist_ok=True)

    board_path = resolve_board_path(expected.state, root)
    live_path = directory / "live.snapshot"
    require_snapshot_output_distinct(board_path, live_path)
    snapshot_before = client.status()
    live_raw = client.snapshot(live_path)
    snapshot_after = client.status()
    if (
        snapshot_before.revision != snapshot_after.revision
        or snapshot_after.revision != status.revision
    ):
        raise RevisionChangedError(
            "live revision changed while canonical snapshot was captured"
        )
    live_snapshot = parse_canonical_snapshot(live_raw)

    disk_path = directory / "disk.snapshot"
    require_snapshot_output_distinct(board_path, disk_path)
    disk_raw = inspect.snapshot(board_path, disk_path)
    disk_snapshot = parse_canonical_snapshot(disk_raw)

    png_path = directory / "final.raw.png"
    png_data = client.board_png(png_path)
    png_issues, png_metadata = validate_png(png_data)
    final_status = client.status()
    if final_status.revision != status.revision:
        raise RevisionChangedError(
            f"live revision changed {status.revision}->{final_status.revision}"
        )

    baseline = _load_baseline(expected.run_dir)
    issues: list[Issue] = []
    issues.extend(compare_cards(expected, cards))
    issues.extend(compare_edges(expected, edges))
    issues.extend(compare_status(expected, final_status, baseline))
    issues.extend(compare_owned_snapshot(expected, live_snapshot))
    issues.extend(compare_live_and_disk(live_snapshot, disk_snapshot))
    issues.extend(png_issues)
    if baseline is None:
        issues.append(
            Issue(
                "UNRELATED_CONTENT_UNVERIFIABLE",
                "No pre-materialization baseline exists; unrelated content preservation cannot be proven",
                severity="unverifiable",
            )
        )
    else:
        issues.extend(compare_baseline(baseline, live_snapshot, expected))
    if final_status.dirty:
        issues.append(
            Issue(
                "PERSISTENCE_DIRTY",
                "The live board has unsaved changes",
                {"revision": final_status.revision},
            )
        )

    outcome = write_final_report(
        expected,
        final_status,
        cards,
        edges,
        issues,
        live_snapshot=live_snapshot,
        disk_snapshot=disk_snapshot,
        baseline_snapshot=baseline,
        png=png_metadata,
    )
    if outcome.result != "FAIL" and not png_issues:
        atomic_write_bytes(expected.run_dir / "final.png", png_data)
    updates = {
        "verified_revision": str(final_status.revision),
        "verification": outcome.result.lower(),
        "verification_digest": outcome.verification_digest,
        "dirty": "1" if final_status.dirty else "0",
    }
    if outcome.result != "FAIL" and not final_status.dirty:
        updates.update({"phase": "saved", "saved": "1", "dirty": "0"})
    else:
        updates.update({"phase": "materialized", "saved": "0"})
    update_state(expected.run_dir / "state.tsv", updates)
    print(
        f"FINAL result={outcome.result} revision={final_status.revision} "
        f"cards={len(cards)}/{len(expected.cards)} edges={len(edges)} "
        f"artifact={expected.artifact_digest} live={live_snapshot.digest} disk={disk_snapshot.digest}"
    )
    if final_status.dirty:
        return EXIT_PERSISTENCE
    return 0 if outcome.result != "FAIL" else EXIT_MISMATCH


def command_check_attestation(arguments: argparse.Namespace) -> int:
    expected = load_expected_run(Path(arguments.run_dir))
    root, client, inspect = _clients(arguments, expected.state)
    directory = expected.run_dir / "work" / "verification"
    directory.mkdir(parents=True, exist_ok=True)
    board_path = resolve_board_path(expected.state, root)
    live_path = directory / "attestation-live.snapshot"
    disk_path = directory / "attestation-disk.snapshot"
    require_snapshot_output_distinct(board_path, live_path)
    require_snapshot_output_distinct(board_path, disk_path)
    before = client.status()
    live_snapshot = parse_canonical_snapshot(client.snapshot(live_path))
    after_live = client.status()
    disk_snapshot = parse_canonical_snapshot(inspect.snapshot(board_path, disk_path))
    status = client.status()
    if not (before.revision == after_live.revision == status.revision):
        raise RevisionChangedError(
            "live revision changed while current attestation evidence was captured"
        )
    attestation = expected.run_dir / "work" / "verification" / "attestation.json"
    reasons = check_final_attestation(
        attestation,
        artifact_digest=expected.artifact_digest,
        revision=status.revision,
        dirty=status.dirty,
        current_live_snapshot_sha256=live_snapshot.digest,
        current_disk_snapshot_sha256=disk_snapshot.digest,
    )
    if reasons:
        print("ATTESTATION result=STALE reasons=" + ",".join(reasons))
        return EXIT_MISMATCH
    print(
        f"ATTESTATION result=CURRENT revision={status.revision} "
        f"artifact={expected.artifact_digest}"
    )
    return 0


def command_materialize(arguments: argparse.Namespace) -> int:
    preflight = load_preflight_run(Path(arguments.run_dir))
    phase = preflight.state.get("phase", "")
    if phase not in {"positioned", "materializing"}:
        raise MindMapInputError(
            f"materialize requires state positioned or materializing, got {phase!r}"
        )
    baseline = preflight.run_dir / "work" / "verification" / "baseline.snapshot"
    if phase == "positioned":
        result = command_preflight(arguments)
        if result != 0:
            return result
        if not baseline.exists():
            capture_arguments = argparse.Namespace(**vars(arguments))
            capture_arguments.replace_baseline = False
            command_capture_baseline(capture_arguments)
        else:
            load_baseline_evidence(preflight.run_dir, required=True)
    elif not baseline.is_file():
        raise MindMapInputError(
            "materializing state has no pre-mutation baseline; refusing a late baseline"
        )
    else:
        load_baseline_evidence(preflight.run_dir, required=True)
    ctl_path = resolve_executable(arguments.whiteboardctl)
    client = WhiteboardCtlClient(ctl_path, _socket(preflight.state), arguments.timeout)
    outcome = run_materialization(preflight, client)
    print(
        f"MATERIALIZED revision={outcome.revision} cards={outcome.cards} "
        f"edges_ok={outcome.successful_edges} edges_error={outcome.failed_edges}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify format-first whiteboard artifacts without inline agent code.",
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(
        command: argparse.ArgumentParser, *, live: bool = True, inspect: bool = False
    ) -> None:
        command.add_argument("--run-dir", required=True)
        if live:
            command.add_argument(
                "--whiteboardctl", type=Path, required=True, help="executable path"
            )
            command.add_argument("--timeout", type=float, default=10.0)
        if inspect:
            command.add_argument(
                "--whiteboard-inspect", type=Path, required=True, help="executable path"
            )

    preflight = subparsers.add_parser(
        "preflight",
        help="explain final artifact and geometry problems without Board mutation",
        allow_abbrev=False,
    )
    common(preflight, live=False)
    preflight.set_defaults(handler=command_preflight)

    preview = subparsers.add_parser(
        "preview",
        help="capture provisional cards as PNG and remove them",
        allow_abbrev=False,
    )
    common(preview)
    preview.add_argument("--batch", default="work/preview.cards")
    preview.add_argument("--max-side", type=int, default=1600)
    preview.set_defaults(handler=command_preview)

    final = subparsers.add_parser(
        "final",
        help="compare artifacts, live Board, saved Board, edges, and PNG",
        allow_abbrev=False,
    )
    common(final, inspect=True)
    final.set_defaults(handler=command_final)

    attestation = subparsers.add_parser(
        "check-attestation",
        help="confirm that final verification still matches the saved Board",
        allow_abbrev=False,
    )
    common(attestation, inspect=True)
    attestation.set_defaults(handler=command_check_attestation)

    materialize = subparsers.add_parser(
        "materialize",
        help="preflight, capture a baseline, and write cards, payloads, and edges",
        allow_abbrev=False,
    )
    common(materialize)
    materialize.set_defaults(handler=command_materialize)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if hasattr(arguments, "timeout") and arguments.timeout <= 0:
        parser.error("--timeout must be positive")
    if hasattr(arguments, "max_side") and not 256 <= arguments.max_side <= 2048:
        parser.error("--max-side must be between 256 and 2048")
    try:
        return int(arguments.handler(arguments))
    except MindMapInputError as error:
        print(f"INPUT ERROR: {error}", file=sys.stderr)
        return EXIT_INPUT
    except RevisionChangedError as error:
        print(f"REVISION ERROR: {error}", file=sys.stderr)
        return EXIT_REVISION
    except (CtlError, ProtocolError, OSError) as error:
        print(f"ENVIRONMENT ERROR: {error}", file=sys.stderr)
        return EXIT_ENVIRONMENT
