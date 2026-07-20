"""Opt-in, isolated Board integration for the text-art materializer.

Run explicitly with::

    WHITEBOARD_TEXTART_INTEGRATION=1 \
      WHITEBOARD_TUI_BINARY=/path/to/whiteboard_tui \
      WHITEBOARDCTL_BINARY=/path/to/whiteboardctl \
      WHITEBOARD_INSPECT_BINARY=/path/to/whiteboard-inspect \
      PYTHONDONTWRITEBYTECODE=1 \
      python3 -B -m unittest -v \
      tools.textart_notes.integration_tests.test_materializer_board

The test owns its PTY, socket names, temporary Board, manifests, and result
state.  It never discovers or connects to a user's existing Board.
"""

from __future__ import annotations

import csv
import fcntl
import json
import os
import pty
import shutil
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
import unittest
from pathlib import Path

from tests.short_socket_workspace import ShortSocketWorkspace

from tools.textart_notes.core.manifest import write_result
from tools.textart_notes.core.models import CardDraft, RenderOptions, RenderResult
from tools.whiteboard_automation.client import WhiteboardCtlClient, WhiteboardInspectClient
from tools.whiteboard_automation.errors import CtlError, ProtocolError
from tools.whiteboard_automation.snapshot import parse_canonical_snapshot


ROOT = Path(__file__).resolve().parents[3]
CTL = Path(
    os.environ.get(
        "WHITEBOARDCTL_BINARY",
        ROOT / "build" / "vcpkg-release" / "whiteboardctl",
    )
)
TUI = Path(
    os.environ.get(
        "WHITEBOARD_TUI_BINARY",
        ROOT / "build" / "vcpkg-release" / "whiteboard_tui",
    )
)
INSPECT = Path(
    os.environ.get(
        "WHITEBOARD_INSPECT_BINARY",
        ROOT / "build" / "vcpkg-release" / "whiteboard-inspect",
    )
)
MATERIALIZER = ROOT / "tools" / "textart_notes" / "materialize_textart.py"
VERIFY_TOOL = (
    ROOT
    / ".agents"
    / "skills"
    / "whiteboard-markdown-mind-map"
    / "scripts"
    / "verify_whiteboard.py"
)
MINDMAP_TOOL = VERIFY_TOOL.with_name("mindmap_tools.py")
RUN_INTEGRATION = os.environ.get("WHITEBOARD_TEXTART_INTEGRATION") == "1"

class OwnedTui:
    """One whiteboard_tui process whose terminal and files belong to the test."""

    def __init__(self, board: Path, socket_path: Path) -> None:
        self.board = board
        self.socket_path = socket_path
        self.master = -1
        self.process: subprocess.Popen[bytes] | None = None
        self.output = bytearray()
        self._reader: threading.Thread | None = None

    def start(self) -> WhiteboardCtlClient:
        if self.process is not None:
            raise AssertionError("owned TUI already started")
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        environment = os.environ.copy()
        environment["WHITEBOARD_TUI_SOCKET"] = str(self.socket_path)
        environment.setdefault("TERM", "xterm-256color")
        environment.setdefault(
            "LANG",
            "en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8",
        )
        try:
            self.process = subprocess.Popen(
                [str(TUI), str(self.board)],
                cwd=ROOT,
                env=environment,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            os.close(slave)
        self.master = master
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()

        deadline = time.monotonic() + 8.0
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            try:
                client = WhiteboardCtlClient(CTL, self.socket_path, 1.0)
                client.status()
                return client
            except (CtlError, ProtocolError, OSError, ValueError) as error:
                last_error = error
                time.sleep(0.05)
        rendered = bytes(self.output).decode("utf-8", errors="replace")[-4000:]
        self.stop()
        raise AssertionError(f"isolated TUI did not become ready: {last_error}\n{rendered}")

    def _drain(self) -> None:
        while self.master >= 0:
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                return
            if not chunk:
                return
            self.output.extend(chunk)
            if len(self.output) > 65536:
                del self.output[:-65536]

    def send(self, content: bytes) -> None:
        if self.master < 0:
            raise AssertionError("owned TUI is not running")
        os.write(self.master, content)

    def stop(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            try:
                self.send(b"\x11")  # Ctrl-Q, on a PTY owned by this test only.
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
        if self.master >= 0:
            os.close(self.master)
            self.master = -1
        if self._reader is not None:
            self._reader.join(timeout=1)
        self.process = None

    def __enter__(self) -> "OwnedTui":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()


def _wait_for_clean(client: WhiteboardCtlClient, deadline_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if client.status().dirty == 0:
            return
        time.sleep(0.05)
    raise AssertionError("isolated Board did not report clean after Ctrl-S")


def _delete_one(client: WhiteboardCtlClient, card_id: int, revision: int) -> int:
    response = client.delete_cards((card_id,), revision)
    if response.count != 1:
        raise AssertionError(f"unexpected isolated delete count: {response.count}")
    return response.revision


@unittest.skipUnless(
    RUN_INTEGRATION,
    "set WHITEBOARD_TEXTART_INTEGRATION=1 to run the isolated PTY/Board test",
)
class MaterializerBoardIntegrationTests(unittest.TestCase):
    def test_failed_open_preserves_source(self) -> None:
        for content, diagnostic in (
            (struct.pack("<III", 0x42574954, 0xFFFFFFFF, 3), b"whiteboard_tui:"),
            (b"invalid project", b"whiteboard_tui:"),
        ):
            with self.subTest(content=content), ShortSocketWorkspace("wbopen-") as root:
                board = root / "board.tiwb"
                board.write_bytes(content)
                socket_path = root / "board.sock"
                with OwnedTui(board, socket_path) as owner:
                    with self.assertRaisesRegex(AssertionError, "did not become ready"):
                        owner.start()
                self.assertIn(diagnostic, bytes(owner.output))
                self.assertEqual(board.read_bytes(), content)
                self.assertFalse(socket_path.exists())

    def test_mindmap_preview_captures_png_and_restores_board(self) -> None:
        self.assertTrue(CTL.is_file() and os.access(CTL, os.X_OK), CTL)
        self.assertTrue(TUI.is_file() and os.access(TUI, os.X_OK), TUI)
        self.assertTrue(VERIFY_TOOL.is_file(), VERIFY_TOOL)
        with ShortSocketWorkspace("wbpreview-") as root:
            board = root / "board.tiwb"
            socket_path = root / "board.sock"
            run = root / "source.mindmap"
            (run / "work").mkdir(parents=True)
            (run / "state.tsv").write_text(
                "key\tvalue\n"
                f"board_file\t{board}\n"
                f"socket\t{socket_path}\n"
                "phase\tplanned\n"
                "revision\t0\n"
                "dirty\t0\n"
                "saved\t0\n",
                encoding="utf-8",
            )
            (run / "work" / "preview.cards").write_text(
                "note 0 0 12 5\nmarkdown 24 0 16 6\n",
                encoding="ascii",
            )
            with OwnedTui(board, socket_path) as owner:
                client = owner.start()
                before = client.status()
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(VERIFY_TOOL),
                        "preview",
                        "--run-dir",
                        str(run),
                        "--whiteboardctl",
                        str(CTL),
                        "--timeout",
                        "3",
                    ],
                    cwd=ROOT,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
                self.assertIn(b"PREVIEW cards=2", completed.stdout)
                after = client.status()
                self.assertEqual((after.cards, after.edges), (before.cards, before.edges))
                self.assertEqual(after.revision, before.revision + 2)
                self.assertTrue((run / "work" / "preview.raw.png").is_file())
                self.assertEqual((run / "work" / "preview.ids").read_text(), "0\n1\n")
                result = json.loads((run / "work" / "preview-result.json").read_text())
                self.assertEqual(result["deleted_revision"], after.revision)

    def test_mindmap_runner_verifies_live_disk_and_attestation(self) -> None:
        self.assertTrue(CTL.is_file() and os.access(CTL, os.X_OK), CTL)
        self.assertTrue(TUI.is_file() and os.access(TUI, os.X_OK), TUI)
        self.assertTrue(INSPECT.is_file() and os.access(INSPECT, os.X_OK), INSPECT)
        self.assertTrue(VERIFY_TOOL.is_file(), VERIFY_TOOL)
        with ShortSocketWorkspace("wbverify-") as root:
            inputs = root / "inputs"
            inputs.mkdir()
            board = inputs / "board.tiwb"
            socket_path = root / "board.sock"
            run = inputs / "source.mindmap"
            (run / "work").mkdir(parents=True)
            source = inputs / "source.md"
            source.write_text("# Source\n", encoding="utf-8")
            shutil.copyfile(
                Path(__file__).with_name("fixtures") / "mindmap-plan.md",
                run / "plan.md",
            )
            (run / "state.tsv").write_text(
                "key\tvalue\n"
                f"source\t{source}\n"
                f"board_file\t{board}\n"
                f"socket\t{socket_path}\n"
                "phase\tplanned\n"
                "revision\t0\n"
                "dirty\t0\n"
                "saved\t0\n",
                encoding="utf-8",
            )

            def invoke(tool: Path, command: str, *arguments: str, code: int = 0) -> bytes:
                completed = subprocess.run(
                    [sys.executable, "-B", str(tool), command,
                     "--run-dir", str(run), *arguments],
                    cwd=ROOT,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    check=False,
                )
                if completed.returncode != code:
                    report = run / "work" / "verification" / "report.json"
                    detail = report.read_text(encoding="utf-8") if report.is_file() else ""
                    self.fail((completed.stdout + completed.stderr).decode(errors="replace") + detail)
                return completed.stdout

            invoke(MINDMAP_TOOL, "prepare")
            with (run / "units.tsv").open(encoding="utf-8", newline="") as stream:
                units = list(csv.DictReader(stream, delimiter="\t"))
            self.assertEqual(len(units), 8)
            layout = "id\tx\ty\n" + "".join(
                f"{unit['id']}\t{index * 48}\t0\n"
                for index, unit in enumerate(units)
            )
            (run / "work" / "provisional-unit-layout.tsv").write_text(layout, encoding="utf-8")
            invoke(MINDMAP_TOOL, "expand-layout", "--layout", "work/provisional-unit-layout.tsv",
                   "--output", "work/provisional-layout.tsv")
            invoke(MINDMAP_TOOL, "build-batch", "--layout", "work/provisional-layout.tsv",
                   "--output", "work/preview.cards")
            live_arguments = ("--whiteboardctl", str(CTL), "--timeout", "3")
            final_arguments = (*live_arguments, "--whiteboard-inspect", str(INSPECT))

            with OwnedTui(board, socket_path) as owner:
                client = owner.start()
                self.assertEqual(client.status().cards, 0)
                invoke(VERIFY_TOOL, "preview", *live_arguments)
                self.assertEqual(client.status().cards, 0)
                self.assertTrue((run / "work" / "preview.raw.png").is_file())
                (run / "unit-layout.tsv").write_text(layout, encoding="utf-8")
                invoke(MINDMAP_TOOL, "expand-layout", "--layout", "unit-layout.tsv",
                       "--output", "layout.tsv")
                state = run / "state.tsv"
                state.write_text(
                    state.read_text(encoding="utf-8").replace("phase\tplanned", "phase\tpositioned"),
                    encoding="utf-8",
                )
                materialized = invoke(VERIFY_TOOL, "materialize", *live_arguments)
                self.assertIn(b"cards=8 edges_ok=7 edges_error=0", materialized)
                self.assertTrue((run / "card-map.tsv").is_file())
                self.assertTrue((run / "edge-results.tsv").is_file())

                # Save through the same terminal input path as the user.
                owner.send(b"\x13")
                _wait_for_clean(client)
                self.assertEqual(struct.unpack("<III", board.read_bytes()[:12]),
                                 (0x42574954, 11, 3))
                self.assertIn(b"FINAL result=PASS", invoke(VERIFY_TOOL, "final", *final_arguments))
                self.assertIn(b"ATTESTATION result=CURRENT",
                              invoke(VERIFY_TOOL, "check-attestation", *final_arguments))
                self.assertTrue((run / "final.png").is_file())
                expected = client.snapshot(root / "expected.snapshot")
                snapshot = parse_canonical_snapshot(expected)
                self.assertEqual({card.card_format for card in snapshot.cards.values()},
                                 {"note", "markdown", "code", "todo", "csv", "folder", "text-art"})
                self.assertEqual((snapshot.card_slots, snapshot.live_cards, snapshot.live_edges),
                                 (16, 8, 7))
                saved_bytes = board.read_bytes()

                # Persisted evidence must become stale on both disk corruption
                # and live mutations; neither is allowed to report CURRENT.
                board.write_bytes(saved_bytes[:-1])
                invoke(VERIFY_TOOL, "check-attestation", *final_arguments, code=3)
                board.write_bytes(saved_bytes)
                first = next(iter(snapshot.cards.values()))
                client.replace_card(first.card_id, client.status().revision,
                                    first.width, first.height, b"unsaved")
                self.assertIn(b"ATTESTATION result=STALE",
                              invoke(VERIFY_TOOL, "check-attestation", *final_arguments, code=1))
                self.assertIn(b"FINAL result=FAIL",
                              invoke(VERIFY_TOOL, "final", *final_arguments, code=5))
                client.replace_card(first.card_id, client.status().revision,
                                    first.width, first.height, first.payload)
                owner.send(b"\x13")
                _wait_for_clean(client)
                self.assertIn(b"FINAL result=PASS", invoke(VERIFY_TOOL, "final", *final_arguments))
                self.assertIn(b"ATTESTATION result=CURRENT",
                              invoke(VERIFY_TOOL, "check-attestation", *final_arguments))
                self.assertEqual(board.read_bytes(), saved_bytes)

            # Remove the complete source tree, including the original board,
            # manifests, payloads, layout and verification artifacts. Only the
            # relocated .tiwb and in-memory expectations remain available.
            relocated = root / "搬移後" / "獨立白板.tiwb"
            relocated.parent.mkdir()
            shutil.copyfile(board, relocated)
            shutil.rmtree(inputs)
            self.assertFalse(inputs.exists())
            inspector = WhiteboardInspectClient(INSPECT)
            self.assertEqual(inspector.snapshot(relocated, root / "relocated.snapshot"), expected)
            self.assertEqual(list(relocated.parent.iterdir()), [relocated])
            with OwnedTui(relocated, root / "reopened.sock") as owner:
                reloaded = owner.start()
                status = reloaded.status()
                self.assertEqual((status.cards, status.edges, status.dirty), (8, 7, False))
                self.assertEqual(reloaded.snapshot(root / "reopened.snapshot"), expected)
                for card in snapshot.cards.values():
                    self.assertEqual(reloaded.get_card(card.card_id).payload, card.payload)
                self.assertEqual(relocated.read_bytes(), saved_bytes)
                owner.send(b"\x13")
                _wait_for_clean(reloaded)
                self.assertEqual(
                    inspector.snapshot(relocated, root / "resaved.snapshot"), expected,
                )
                self.assertEqual(relocated.read_bytes(), saved_bytes)
                self.assertEqual(list(relocated.parent.iterdir()), [relocated])

    def test_create_verify_save_and_reload_with_tombstone(self) -> None:
        self.assertTrue(CTL.is_file() and os.access(CTL, os.X_OK), CTL)
        self.assertTrue(TUI.is_file() and os.access(TUI, os.X_OK), TUI)
        self.assertTrue(INSPECT.is_file() and os.access(INSPECT, os.X_OK), INSPECT)
        with ShortSocketWorkspace("wbmat-") as root:
            board = root / "board.tiwb"
            first_socket = root / "s1.sock"
            second_socket = root / "s2.sock"
            rendered = root / "rendered"
            result_path = root / "materialization.json"
            options = RenderOptions(theme="unicode-light", max_width=20, max_height=10)
            manifest = write_result(
                RenderResult(
                    "fixture-note",
                    "unicode-light",
                    (
                        CardDraft("alpha", "A中\nok", 4, 2, 0, 0, {"source": "A"}),
                        CardDraft("beta", "e\u0301\tX\n\n尾", 5, 3, 8, 3, {}),
                    ),
                ),
                options,
                rendered,
            )

            with OwnedTui(board, first_socket) as owner:
                client = owner.start()
                self.assertEqual(client.status().cards, 0)

                # Leave an owned tombstone so live-card count cannot be mistaken
                # for FIRST_CARD_ID by the materializer.
                created = client.create_cards(b"text-art 0 0 1 1\n", client.status().revision)
                self.assertEqual(created.first_card_id, 0)
                _delete_one(client, created.first_card_id, created.revision)
                self.assertEqual(client.status().cards, 0)

                completed = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(MATERIALIZER),
                        "--manifest",
                        str(manifest),
                        "--socket",
                        str(first_socket),
                        "--origin-x",
                        "-40",
                        "--origin-y",
                        "25",
                        "--result",
                        str(result_path),
                        "--whiteboardctl",
                        str(CTL),
                        "--timeout",
                        "2",
                    ],
                    cwd=ROOT,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
                state = json.loads(result_path.read_text(encoding="utf-8"))
                self.assertEqual(state["status"], "complete")
                self.assertEqual([card["card_id"] for card in state["cards"]], [1, 2])
                self.assertEqual(state["final_board"]["cards"], 2)
                self.assertEqual(state["final_board"]["dirty"], 1)

                manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
                expected: dict[int, tuple[dict[str, object], bytes]] = {}
                for card_state, card_manifest in zip(state["cards"], manifest_data["cards"]):
                    payload = rendered / str(card_manifest["payload"])
                    expected[int(card_state["card_id"])] = (card_manifest, payload.read_bytes())
                for card_id, (card_manifest, payload) in expected.items():
                    observed = client.get_card(card_id)
                    self.assertEqual(observed.format_name, "text-art")
                    self.assertEqual((observed.x, observed.y), (
                        -40 + int(card_manifest["x"]),
                        25 + int(card_manifest["y"]),
                    ))
                    self.assertEqual((observed.width, observed.height), (
                        card_manifest["width"],
                        card_manifest["height"],
                    ))
                    self.assertEqual(observed.payload, payload)

                owner.send(b"\x13")  # Ctrl-S, on this test's owned PTY.
                _wait_for_clean(client)
                self.assertTrue(board.is_file())
                self.assertGreater(board.stat().st_size, 0)
                live_snapshot = root / "live.snapshot"
                disk_snapshot = root / "disk.snapshot"
                snapshot_environment = {
                    **os.environ,
                    "WHITEBOARD_TUI_SOCKET": str(first_socket),
                }
                subprocess.run(
                    [str(CTL), "snapshot", "--output", str(live_snapshot)],
                    cwd=ROOT,
                    env=snapshot_environment,
                    check=True,
                    timeout=10,
                )
                subprocess.run(
                    [
                        str(INSPECT),
                        "snapshot",
                        str(board),
                        "--output",
                        str(disk_snapshot),
                    ],
                    cwd=ROOT,
                    check=True,
                    timeout=10,
                )
                self.assertEqual(live_snapshot.read_bytes(), disk_snapshot.read_bytes())

            with OwnedTui(board, second_socket) as owner:
                reloaded = owner.start()
                status = reloaded.status()
                self.assertEqual((status.cards, status.edges, status.dirty), (2, 0, 0))
                for card_id, (card_manifest, payload) in expected.items():
                    observed = reloaded.get_card(card_id)
                    self.assertEqual(observed.payload, payload)
                    self.assertEqual((observed.x, observed.y), (
                        -40 + int(card_manifest["x"]),
                        25 + int(card_manifest["y"]),
                    ))
                    self.assertEqual((observed.width, observed.height), (
                        card_manifest["width"],
                        card_manifest["height"],
                    ))

if __name__ == "__main__":
    unittest.main()
