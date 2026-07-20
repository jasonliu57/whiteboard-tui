#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parents[4]
sys.path.insert(0, str(SCRIPTS))

from whiteboard_validation.artifacts import (  # noqa: E402
    MindMapInputError,
    load_expected_run,
    load_preflight_run,
    resolve_folder_payload,
)
from whiteboard_validation.cli import (  # noqa: E402
    EXIT_MISMATCH,
    EXIT_PERSISTENCE,
    _read_live_scope,
    build_parser,
    main,
)
from whiteboard_validation.compare import (  # noqa: E402
    compare_baseline,
    compare_cards,
    compare_edges,
    compare_live_and_disk,
)
from tools.whiteboard_automation.errors import CtlError  # noqa: E402
from whiteboard_validation.materialize import run_materialization  # noqa: E402
from tools.whiteboard_automation.models import (  # noqa: E402
    CreateCardsResponse,
    LiveCard,
    LiveEdge,
    LiveStatus,
    MutationResponse,
)
from whiteboard_validation.models import (  # noqa: E402
    ExpectedCard,
    ExpectedEdge,
    ExpectedRun,
    RevisionChangedError,
)
from tools.whiteboard_automation.snapshot import (  # noqa: E402
    SNAPSHOT_MAGIC,
    parse_canonical_snapshot,
)
from whiteboard_validation.persistence import (  # noqa: E402
    load_baseline_evidence,
    resolve_board_path,
)
from whiteboard_validation.report import (  # noqa: E402
    check_final_attestation,
    write_final_report,
)


def live_card(
    payload: bytes,
    *,
    revision: int = 7,
    card_id: int = 0,
    card_format: str = "note",
    x: int = 1,
    y: int = 2,
    width: int = 12,
    height: int = 5,
) -> LiveCard:
    return LiveCard(
        revision,
        card_id,
        card_format,
        x,
        y,
        width,
        height,
        payload,
    )


def snapshot_bytes(
    cards: list[tuple[int, str, int, int, int, int, bytes]],
    *,
    card_slots: int | None = None,
    edges: list[tuple[int, int, int]] | None = None,
    edge_slots: int | None = None,
    glyphs: list[tuple[int, int, int]] | None = None,
) -> bytes:
    edges = edges or []
    glyphs = glyphs or []
    if card_slots is None:
        card_slots = max((card[0] for card in cards), default=-1) + 1
    if edge_slots is None:
        edge_slots = max((edge[0] for edge in edges), default=-1) + 1
    body = bytearray(SNAPSHOT_MAGIC)
    body.extend(
        f"META {card_slots} {len(cards)} {edge_slots} {len(edges)} {len(glyphs)}\n".encode(
            "ascii"
        )
    )
    for card_id, fmt, x, y, width, height, payload in cards:
        body.extend(
            f"CARD {card_id} {fmt} {x} {y} {width} {height} "
            f"{len(payload)}\n".encode("ascii")
        )
        body.extend(payload)
        body.extend(b"\n")
    for edge_id, source, target in edges:
        body.extend(
            f"EDGE {edge_id} {source} 1 {target} 3 0 0 0 0 1 1 0\n".encode("ascii")
        )
    for x, y, codepoint in sorted(glyphs, key=lambda value: (value[1], value[0])):
        body.extend(f"GLYPH {x} {y} {codepoint}\n".encode("ascii"))
    body.extend(b"END\n")
    return bytes(body)


def write_run(
    root: Path,
    *,
    two_cards: bool = False,
    phase: str = "positioned",
    with_results: bool = True,
) -> Path:
    run = root / "run.mindmap"
    (run / "payloads").mkdir(parents=True)
    cards = [
        ("u-one", 0, "note", 12, 5, "payloads/u-one.txt", b"\xe4\xb8\xad\nEND\n")
    ]
    if two_cards:
        cards.append(("u-two", 1, "markdown", 16, 6, "payloads/u-two.md", b"# Two\n"))
    lines = ["id\tindex\tformat\twidth\theight\tgroup\ttitle\tpayload"]
    layout = ["id\tx\ty"]
    for logical_id, index, fmt, width, height, payload_path, payload in cards:
        lines.append(
            f"{logical_id}\t{index}\t{fmt}\t{width}\t{height}\t-\t{logical_id}\t{payload_path}"
        )
        layout.append(f"{logical_id}\t{index * 30 + 1}\t2")
        (run / payload_path).write_bytes(payload)
    (run / "cards.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (run / "layout.tsv").write_text("\n".join(layout) + "\n", encoding="utf-8")
    edge_lines = ["from\tto"]
    if two_cards:
        edge_lines.extend(["u-one\tu-two", "u-two\tu-one"])
    (run / "edges.tsv").write_text("\n".join(edge_lines) + "\n", encoding="utf-8")
    board = root / "board.tiwb"
    board.write_bytes(b"board")
    state = textwrap.dedent(
        f"""\
        key\tvalue
        source\tnote.md
        board_file\t{board}
        socket\t{root / 'agent.sock'}
        phase\t{phase}
        state\t{phase}
        revision\t1
        dirty\t0
        saved\t0
        """
    )
    (run / "state.tsv").write_text(state, encoding="utf-8")
    if with_results:
        map_lines = ["id\tcard_id"] + [
            f"{logical_id}\t{index}" for logical_id, index, *_ in cards
        ]
        (run / "card-map.tsv").write_text("\n".join(map_lines) + "\n", encoding="utf-8")
        result_lines = ["from\tto\tstatus\tedge_id\terror"]
        if two_cards:
            result_lines.extend([
                "u-one\tu-two\tOK\t0\t",
                "u-two\tu-one\tERROR\t\tERR no_route_in_view",
            ])
        (run / "edge-results.tsv").write_text(
            "\n".join(result_lines) + "\n", encoding="utf-8"
        )
    return run


def expected_run(payload: bytes = b"abc") -> ExpectedRun:
    card = ExpectedCard(
        logical_id="u-one",
        card_id=1,
        card_format="note",
        x=1,
        y=2,
        width=12,
        height=5,
        payload_path=Path("payload"),
        payload=payload,
    )
    return ExpectedRun(Path("."), (card,), (), {}, "digest")


def write_baseline(directory: Path, raw: bytes, revision: int = 1) -> None:
    snapshot = parse_canonical_snapshot(raw)
    (directory / "baseline.snapshot").write_bytes(raw)
    (directory / "baseline.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "revision": revision,
                "artifact_digest": "fixture",
                "sha256": snapshot.digest,
                "card_slots": snapshot.card_slots,
                "cards": snapshot.live_cards,
                "edge_slots": snapshot.edge_slots,
                "edges": snapshot.live_edges,
                "glyphs": snapshot.glyph_count,
            }
        )
        + "\n",
        encoding="utf-8",
    )


class ComparisonTests(unittest.TestCase):
    def test_card_metadata_and_payload_mismatches(self) -> None:
        expected = expected_run(b"abc")
        live = live_card(b"abd", card_id=1, width=13)
        codes = [issue.code for issue in compare_cards(expected, {1: live})]
        self.assertIn("CARD_METADATA_MISMATCH", codes)
        self.assertIn("CARD_PAYLOAD_MISMATCH", codes)
        self.assertEqual(compare_cards(expected, {})[0].code, "CARD_MISSING")

    def test_missing_extra_and_reversed_edges(self) -> None:
        run = expected_run()
        declared = ExpectedEdge("u-one", "u-two", 1, 2, True, 8, None)
        run = replace(run, edges=(declared,))
        reverse = LiveEdge(7, 9, 2, 1, 1, 3, 0, 0, (0, 0, 1, 1), ())
        codes = [issue.code for issue in compare_edges(run, {9: reverse})]
        self.assertIn("EDGE_MISSING", codes)
        self.assertIn("EXTRA_OWNED_EDGE", codes)
        failed = replace(declared, expected_present=False, expected_edge_id=None, recorded_error="x")
        codes = [issue.code for issue in compare_edges(replace(run, edges=(failed,)), {9: reverse})]
        self.assertIn("REVERSED_EDGE_PRESENT", codes)

    def test_baseline_detects_unrelated_change_and_slot_history(self) -> None:
        baseline = parse_canonical_snapshot(
            snapshot_bytes([(0, "note", 0, 0, 12, 5, b"old")])
        )
        final = parse_canonical_snapshot(
            snapshot_bytes(
                [
                    (0, "note", 0, 0, 12, 5, b"changed"),
                    (1, "note", 1, 2, 12, 5, b"abc"),
                    (2, "note", 50, 2, 12, 5, b"extra"),
                ],
                card_slots=3,
            )
        )
        codes = [issue.code for issue in compare_baseline(baseline, final, expected_run())]
        self.assertIn("UNRELATED_CARD_CHANGED", codes)
        self.assertIn("EXTRA_UNOWNED_CARD", codes)
        self.assertIn("CARD_SLOT_COUNT_MISMATCH", codes)

    def test_live_disk_mismatch(self) -> None:
        live = parse_canonical_snapshot(snapshot_bytes([]))
        disk = parse_canonical_snapshot(snapshot_bytes([], card_slots=1))
        self.assertEqual(compare_live_and_disk(live, disk)[0].code, "LIVE_DISK_MISMATCH")


class ArtifactAndAttestationTests(unittest.TestCase):
    def test_artifact_headers_paths_and_folder_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            run = write_run(Path(name))
            loaded = load_expected_run(run)
            self.assertEqual(loaded.cards[0].payload, "中\nEND\n".encode())
            (run / "cards.tsv").write_text("bad\theader\n", encoding="utf-8")
            with self.assertRaises(MindMapInputError):
                load_preflight_run(run)
        folder = b"ROOT\tRoot\n0\tCARD\t@u-target\t0\tTarget\n"
        self.assertEqual(
            resolve_folder_payload(
                folder,
                logical_id="u-folder",
                unit_anchors={"u-target": "u-one"},
                card_map={"u-one": 42},
            ),
            b"ROOT\tRoot\n0\tCARD\t42\t0\tTarget\n",
        )

    def test_artifact_change_invalidates_old_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            run = write_run(Path(name))
            expected = load_expected_run(run)
            payload = expected.cards[0].payload
            live = live_card(payload)
            snap = parse_canonical_snapshot(
                snapshot_bytes([(0, "note", 1, 2, 12, 5, payload)])
            )
            outcome = write_final_report(
                expected,
                LiveStatus(7, 1, 0, False),
                {0: live},
                {},
                [],
                live_snapshot=snap,
                disk_snapshot=snap,
                baseline_snapshot=snap,
                png=None,
            )
            self.assertEqual(
                check_final_attestation(
                    outcome.attestation_path,
                    artifact_digest=expected.artifact_digest,
                    revision=7,
                    dirty=False,
                ),
                [],
            )
            (run / "payloads" / "u-one.txt").write_bytes(payload + b"changed")
            changed = load_expected_run(run)
            self.assertIn(
                "ATTESTATION_ARTIFACT_STALE",
                check_final_attestation(
                    outcome.attestation_path,
                    artifact_digest=changed.artifact_digest,
                    revision=7,
                    dirty=False,
                ),
            )
            other = parse_canonical_snapshot(snapshot_bytes([], card_slots=1))
            reasons = check_final_attestation(
                outcome.attestation_path,
                artifact_digest=expected.artifact_digest,
                revision=7,
                dirty=False,
                current_live_snapshot_sha256=snap.digest,
                current_disk_snapshot_sha256=other.digest,
            )
            self.assertIn("ATTESTATION_DISK_SNAPSHOT_STALE", reasons)
            self.assertIn("ATTESTATION_CURRENT_PERSISTENCE_MISMATCH", reasons)

    def test_folder_unit_metadata_is_bound_to_artifact_digest(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            run = write_run(Path(name))
            (run / "cards.tsv").write_text(
                "id\tindex\tformat\twidth\theight\tgroup\ttitle\tpayload\n"
                "u-one\t0\tfolder\t16\t5\t-\tu-one\tpayloads/u-one.folder.md\n",
                encoding="utf-8",
            )
            (run / "payloads" / "u-one.folder.md").write_bytes(
                b"ROOT\tRoot\n0\tCARD\t@u-unit\t0\tSelf\n"
            )
            units = (
                "id\tindex\tkind\trenderer\twidth\theight\tgroup\ttitle\tanchor\n"
                "u-unit\t0\tnative\t-\t16\t5\t-\tUnit\tu-one\n"
            )
            (run / "units.tsv").write_text(units, encoding="utf-8")
            (run / "unit-members.tsv").write_text(
                "unit\tcard\tdx\tdy\nu-unit\tu-one\t0\t0\n",
                encoding="utf-8",
            )
            before = load_expected_run(run)
            (run / "units.tsv").write_text(
                units.replace("\tUnit\t", "\tRenamed\t"),
                encoding="utf-8",
            )
            after = load_expected_run(run)
            self.assertNotEqual(before.artifact_digest, after.artifact_digest)

    def test_baseline_snapshot_and_metadata_are_cross_checked(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            run = Path(name) / "run.mindmap"
            directory = run / "work" / "verification"
            directory.mkdir(parents=True)
            write_baseline(directory, snapshot_bytes([]))
            self.assertIsNotNone(load_baseline_evidence(run, required=True))
            (directory / "baseline.snapshot").write_bytes(
                snapshot_bytes([], card_slots=1)
            )
            with self.assertRaises(MindMapInputError):
                load_baseline_evidence(run, required=True)


class RevisionTests(unittest.TestCase):
    def test_revision_change_retries_once_then_stops(self) -> None:
        expected = expected_run(b"")

        class FlappingClient:
            revision = 0

            def status(self) -> LiveStatus:
                self.revision += 1
                return LiveStatus(self.revision, 1, 0, False)

            def get_card(self, card_id: int) -> LiveCard:
                return live_card(b"", revision=self.revision, card_id=card_id)

            def edges(self, card_id: int):
                from tools.whiteboard_automation.protocol import parse_edges_response

                return parse_edges_response(
                    f"OK {self.revision} EDGES {card_id} 0\nEND\n".encode()
                )

        with self.assertRaises(RevisionChangedError):
            _read_live_scope(expected, FlappingClient())


class MaterializationTests(unittest.TestCase):
    def test_preflight_records_layout_warning_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            run = write_run(Path(name), two_cards=True, with_results=False)
            (run / "layout.tsv").write_text(
                "id\tx\ty\nu-one\t1\t2\nu-two\t800\t2\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with mock.patch("sys.stdout", output):
                result = main(["preflight", "--run-dir", str(run)])
            self.assertEqual(result, 0, output.getvalue())
            report = json.loads(
                (run / "work" / "verification" / "report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(report["result"], "PASS")
            self.assertIn("Warnings:", report["geometry_output"])
            self.assertIn(
                "A larger board may be harder to view in one preview.",
                report["geometry_output"],
            )
            markdown = (
                run / "work" / "verification" / "report.md"
            ).read_text(encoding="utf-8")
            self.assertIn("## Geometry", markdown)
            self.assertIn(
                "A larger board may be harder to view in one preview.",
                markdown,
            )

    def test_preflight_stops_on_layout_error(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            run = write_run(Path(name), two_cards=True, with_results=False)
            (run / "layout.tsv").write_text(
                "id\tx\ty\nu-one\t1\t2\nu-two\t1\t2\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with mock.patch("sys.stdout", output):
                result = main(["preflight", "--run-dir", str(run)])
            self.assertEqual(result, EXIT_MISMATCH, output.getvalue())
            report = json.loads(
                (run / "work" / "verification" / "report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(report["result"], "FAIL")
            self.assertIn(
                "Both items occupy the same board area.",
                report["geometry_output"],
            )

    def test_preview_checks_space_captures_png_and_removes_cards(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            run = Path(name)
            (run / "work").mkdir()
            (run / "state.tsv").write_text(
                "key\tvalue\nsocket\t/tmp/preview.sock\nphase\tprepared\n",
                encoding="utf-8",
            )
            (run / "work" / "preview.cards").write_text(
                "note 10 20 12 5\nmarkdown 30 20 16 6\n",
                encoding="ascii",
            )

            class PreviewClient:
                def __init__(self, *_args) -> None:
                    self.statuses = iter(
                        [
                            LiveStatus(7, 1, 0, False),
                            LiveStatus(8, 3, 0, True),
                            LiveStatus(9, 1, 0, True),
                        ]
                    )

                def status(self):
                    return next(self.statuses)

                def view(self):
                    return SimpleNamespace(
                        revision=7,
                        viewport_x=0,
                        viewport_y=0,
                        viewport_width=100,
                        viewport_height=60,
                    )

                def query(self, *values):
                    self.query_values = values
                    return SimpleNamespace(revision=7, cards=())

                def create_cards(self, batch, revision):
                    self.created = (batch, revision)
                    return CreateCardsResponse(8, 2, 40)

                def board_png(self, path, max_side):
                    data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                    path.write_bytes(data)
                    self.max_side = max_side
                    return data

                def delete_cards(self, card_ids, revision):
                    self.deleted = (card_ids, revision)
                    return SimpleNamespace(revision=9, count=2)

            client = PreviewClient()
            with (
                mock.patch("whiteboard_validation.cli.resolve_executable", return_value=Path("/ctl")),
                mock.patch("whiteboard_validation.cli.WhiteboardCtlClient", return_value=client),
            ):
                self.assertEqual(
                    main(["preview", "--run-dir", str(run), "--whiteboardctl", "/ctl"]),
                    0,
                )
            self.assertEqual(client.deleted, ((40, 41), 8))
            self.assertEqual((run / "work" / "preview.ids").read_text(), "40\n41\n")
            result = json.loads((run / "work" / "preview-result.json").read_text())
            self.assertEqual(result["bounds"], {"left": 10, "top": 20, "right": 46, "bottom": 26})
            self.assertEqual(result["deleted_revision"], 9)

    def test_runner_rechecks_artifact_digest_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            run = write_run(Path(name), with_results=False)
            preflight = load_preflight_run(run)
            (run / "payloads" / "u-one.txt").write_bytes(b"changed\n")

            class NeverCalled:
                def status(self) -> LiveStatus:
                    raise AssertionError("Board must not be contacted")

            with self.assertRaisesRegex(MindMapInputError, "inputs changed"):
                run_materialization(preflight, NeverCalled())  # type: ignore[arg-type]

    def test_runner_journals_before_each_mutation_and_writes_exact_results(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            run = write_run(Path(name), two_cards=True, with_results=False)
            preflight = load_preflight_run(run)
            baseline_directory = run / "work" / "verification"
            baseline_directory.mkdir(parents=True)
            write_baseline(baseline_directory, snapshot_bytes([]), revision=1)

            class FakeClient:
                def __init__(self) -> None:
                    self.revision = 1
                    self.payloads = {0: b"", 1: b""}
                    self.calls: list[tuple[object, ...]] = []

                def _last_event(self) -> str:
                    lines = (run / "work" / "materialization.jsonl").read_text().splitlines()
                    return json.loads(lines[-1])["event"]

                def status(self) -> LiveStatus:
                    return LiveStatus(self.revision, len(self.payloads), 0, self.revision > 1)

                def create_cards(self, batch: bytes, revision: int) -> CreateCardsResponse:
                    self.assert_event("CREATE_BEGIN")
                    self.calls.append(("create", revision, batch))
                    self.revision = 2
                    return CreateCardsResponse(2, 2, 0)

                def assert_event(self, wanted: str) -> None:
                    if self._last_event() != wanted:
                        raise AssertionError((wanted, self._last_event()))

                def get_card(self, card_id: int) -> LiveCard:
                    fmt = "note" if card_id == 0 else "markdown"
                    width, height, x = (12, 5, 1) if card_id == 0 else (16, 6, 31)
                    return live_card(
                        self.payloads[card_id],
                        revision=self.revision,
                        card_id=card_id,
                        card_format=fmt,
                        x=x,
                        width=width,
                        height=height,
                    )

                def replace_card(
                    self, card_id: int, revision: int, width: int, height: int, payload: bytes
                ) -> MutationResponse:
                    self.assert_event("REPLACE_BEGIN")
                    self.calls.append(("replace", card_id, revision, width, height))
                    self.payloads[card_id] = payload
                    self.revision += 1
                    return MutationResponse(self.revision, card_id)

                def connect(self, source: int, target: int, revision: int) -> MutationResponse:
                    self.assert_event("EDGE_BEGIN")
                    self.calls.append(("connect", source, target, revision))
                    if source == 1:
                        raise CtlError(
                            "connect failed",
                            returncode=1,
                            stderr=b"ERR no_route_in_view\n",
                        )
                    self.revision += 1
                    return MutationResponse(self.revision, 0)

            client = FakeClient()
            outcome = run_materialization(preflight, client)  # type: ignore[arg-type]
            self.assertEqual((outcome.cards, outcome.successful_edges, outcome.failed_edges), (2, 1, 1))
            self.assertEqual(
                (run / "card-map.tsv").read_text(),
                "id\tcard_id\nu-one\t0\nu-two\t1\n",
            )
            self.assertEqual(
                (run / "edge-results.tsv").read_text(),
                "from\tto\tstatus\tedge_id\terror\n"
                "u-one\tu-two\tOK\t0\t\n"
                "u-two\tu-one\tERROR\t\tERR no_route_in_view\n",
            )
            state = dict(
                line.split("\t", 1)
                for line in (run / "state.tsv").read_text().splitlines()[1:]
            )
            self.assertEqual((state["phase"], state["saved"]), ("materialized", "0"))
            self.assertEqual(client.calls[0][0:2], ("create", 1))
            self.assertEqual([call[0] for call in client.calls], ["create", "replace", "replace", "connect", "connect"])


class FinalCommandTests(unittest.TestCase):
    def test_live_commands_require_explicit_executables(self) -> None:
        parser = build_parser()
        for command in ("preview", "materialize", "final", "check-attestation"):
            arguments = [command, "--run-dir", "run"]
            with (
                self.subTest(command=command),
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                with self.assertRaises(SystemExit) as caught:
                    parser.parse_args(arguments)
                self.assertEqual(caught.exception.code, 2)
                self.assertIn("--whiteboardctl", stderr.getvalue())
                if command in {"final", "check-attestation"}:
                    with self.assertRaises(SystemExit):
                        parser.parse_args([*arguments, "--whiteboardctl", "/ctl"])
                    self.assertIn("--whiteboard-inspect", stderr.getvalue())

    def test_board_file_is_required(self) -> None:
        with self.assertRaisesRegex(MindMapInputError, "missing board_file"):
            resolve_board_path({}, ROOT)

    def _fake_executables(self, root: Path, snapshot: Path, payload: Path, log: Path) -> tuple[Path, Path]:
        ctl = root / "fake-ctl"
        ctl.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import os, pathlib, shutil, sys
                command = sys.argv[1]
                with open(os.environ['FAKE_CTL_LOG'], 'a', encoding='utf-8') as stream:
                    stream.write(command + '\\n')
                dirty = os.environ.get('FAKE_DIRTY', '0')
                if command == 'status':
                    sys.stdout.write(f'OK 7 STATUS 1 0 {{dirty}}\\n')
                elif command == 'get':
                    payload = pathlib.Path({str(payload)!r}).read_bytes()
                    header = f'OK 7 CARD 0 note 1 2 12 5 {{len(payload)}}\\n'.encode()
                    sys.stdout.buffer.write(header + payload + b'\\nEND\\n')
                elif command == 'edges':
                    sys.stdout.write('OK 7 EDGES 0 0\\nEND\\n')
                elif command == 'snapshot':
                    shutil.copyfile({str(snapshot)!r}, sys.argv[3])
                elif command == 'board-png':
                    sys.stdout.buffer.write(b'\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01')
                else:
                    raise SystemExit('mutation forbidden: ' + command)
                """
            ),
            encoding="utf-8",
        )
        inspect = root / "fake-inspect"
        inspect.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                import shutil, sys
                shutil.copyfile({str(snapshot)!r}, sys.argv[4])
                """
            ),
            encoding="utf-8",
        )
        ctl.chmod(ctl.stat().st_mode | stat.S_IXUSR)
        inspect.chmod(inspect.stat().st_mode | stat.S_IXUSR)
        return ctl, inspect

    def test_final_uses_only_read_commands_and_dirty_revokes_saved(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            run = write_run(root)
            payload = run / "payloads" / "u-one.txt"
            snapshot = root / "live.snapshot"
            snapshot.write_bytes(
                snapshot_bytes([(0, "note", 1, 2, 12, 5, payload.read_bytes())])
            )
            verification = run / "work" / "verification"
            verification.mkdir(parents=True)
            write_baseline(verification, snapshot_bytes([]))
            log = root / "ctl.log"
            ctl, inspect = self._fake_executables(root, snapshot, payload, log)
            arguments = [
                "final",
                "--run-dir",
                str(run),
                "--whiteboardctl",
                str(ctl),
                "--whiteboard-inspect",
                str(inspect),
            ]
            with mock.patch.dict(os.environ, {"FAKE_CTL_LOG": str(log)}, clear=False):
                self.assertEqual(main(arguments), 0)
            commands = log.read_text().splitlines()
            self.assertEqual(
                commands,
                ["status", "get", "edges", "status", "status", "snapshot", "status", "board-png", "status"],
            )
            self.assertFalse({"connect", "replace-card", "delete-card", "delete-cards"} & set(commands))
            with mock.patch.dict(
                os.environ,
                {"FAKE_CTL_LOG": str(log), "FAKE_DIRTY": "1"},
                clear=False,
            ):
                self.assertEqual(main(arguments), EXIT_PERSISTENCE)
            report = json.loads((verification / "report.json").read_text())
            self.assertIn("PERSISTENCE_DIRTY", [issue["code"] for issue in report["issues"]])
            state = dict(
                line.split("\t", 1)
                for line in (run / "state.tsv").read_text().splitlines()[1:]
            )
            self.assertEqual((state["saved"], state["phase"]), ("0", "materialized"))


if __name__ == "__main__":
    unittest.main()
