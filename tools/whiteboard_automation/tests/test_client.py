from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.whiteboard_automation.client import (
    WhiteboardCtlClient,
    resolve_executable,
    run_process,
)
from tools.whiteboard_automation.errors import CtlError


class ClientTests(unittest.TestCase):
    def test_executable_path_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            built = root / "build" / "whiteboardctl"
            built.parent.mkdir()
            built.write_text("#!/bin/sh\nexit 0\n")
            built.chmod(0o700)
            with (
                mock.patch("os.getcwd", return_value=str(root)),
                mock.patch.dict("os.environ", {"PATH": str(built.parent)}),
            ):
                self.assertEqual(resolve_executable("build/whiteboardctl"), built)
                with self.assertRaises(CtlError):
                    resolve_executable("whiteboardctl")
                with self.assertRaises(CtlError):
                    resolve_executable("missing/whiteboardctl")
            built.chmod(0o600)
            with self.assertRaises(CtlError):
                resolve_executable(built)

    def test_timeout_is_normalized(self) -> None:
        with self.assertRaises(CtlError) as caught:
            run_process(
                Path(sys.executable),
                ["-c", "import time; time.sleep(0.2)"],
                timeout=0.01,
            )
        self.assertIn("timed out", str(caught.exception))

    def test_read_only_methods_issue_only_read_commands(self) -> None:
        calls: list[str] = []
        snapshot = b"WHITEBOARD-SNAPSHOT 2\nMETA 0 0 0 0 0\nEND\n"

        def fake_run(_executable: Path, arguments: list[str], **_kwargs: object) -> bytes:
            calls.append(arguments[0])
            if arguments[0] == "status":
                return b"OK 1 STATUS 0 0 0\n"
            if arguments[0] == "get":
                return b"OK 1 CARD 0 note 0 0 12 5 0\n\nEND\n"
            if arguments[0] == "edges":
                return b"OK 1 EDGES 0 0\nEND\n"
            if arguments[0] == "snapshot":
                Path(arguments[2]).write_bytes(snapshot)
                return b""
            if arguments[0] == "board-png":
                return b"png"
            raise AssertionError(arguments)

        with tempfile.TemporaryDirectory() as name, mock.patch(
            "tools.whiteboard_automation.client.run_process", side_effect=fake_run
        ):
            client = WhiteboardCtlClient(Path("ctl"), "socket")
            client.status()
            client.get_card(0)
            client.edges(0)
            client.snapshot(Path(name) / "snapshot")
            client.board_png(Path(name) / "board.png")
        self.assertEqual(calls, ["status", "get", "edges", "snapshot", "board-png"])

    def test_create_cards_parses_the_typed_response(self) -> None:
        client = WhiteboardCtlClient(Path("ctl"), "socket")
        with mock.patch(
            "tools.whiteboard_automation.client.run_process",
            return_value=b"OK 8 CREATE_CARDS 2 50\n",
        ):
            created = client.create_cards(b"x", 2)
        self.assertEqual(
            (created.revision, created.count, created.first_card_id),
            (8, 2, 50),
        )


if __name__ == "__main__":
    unittest.main()
