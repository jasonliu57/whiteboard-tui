#!/usr/bin/env python3
"""Black-box protocol, error, timeout, and snapshot tests for whiteboardctl."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import threading
import time
import unittest
from pathlib import Path

from short_socket_workspace import ShortSocketWorkspace


def serve(path: Path, response: bytes | None, delay: float, ready: threading.Event) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        listener.listen(1)
        ready.set()
        connection, _ = listener.accept()
        with connection:
            while connection.recv(65536):
                pass
            if delay:
                time.sleep(delay)
            if response is not None:
                connection.sendall(response)


def serve_sequence(
    path: Path,
    responses: list[bytes],
    requests: list[bytes],
    ready: threading.Event,
) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        listener.listen(1)
        ready.set()
        for response in responses:
            connection, _ = listener.accept()
            with connection:
                request = bytearray()
                while chunk := connection.recv(65536):
                    request.extend(chunk)
                requests.append(bytes(request))
                connection.sendall(response)


def invoke(
    executable: Path,
    root: Path,
    response: bytes | None,
    *,
    delay: float = 0.0,
    timeout_ms: int = 1000,
) -> subprocess.CompletedProcess[bytes]:
    socket_path = root / "agent.sock"
    ready = threading.Event()
    thread = threading.Thread(
        target=serve,
        args=(socket_path, response, delay, ready),
        daemon=True,
    )
    thread.start()
    if not ready.wait(2):
        raise AssertionError("fake agent did not start")
    completed = subprocess.run(
        [str(executable), "status"],
        env={
            **os.environ,
            "WHITEBOARD_TUI_SOCKET": str(socket_path),
            "WHITEBOARDCTL_TIMEOUT_MS": str(timeout_ms),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3,
        check=False,
    )
    thread.join(timeout=2)
    if thread.is_alive():
        raise AssertionError("fake agent did not stop")
    return completed


def invoke_snapshot(
    executable: Path,
    root: Path,
    responses: list[bytes],
    *,
    existing: bytes | None = None,
) -> tuple[subprocess.CompletedProcess[bytes], bytes | None, list[bytes]]:
    socket_path = root / "agent.sock"
    output_path = root / "board.snapshot"
    if existing is not None:
        output_path.write_bytes(existing)
    requests: list[bytes] = []
    ready = threading.Event()
    thread = threading.Thread(
        target=serve_sequence,
        args=(socket_path, responses, requests, ready),
        daemon=True,
    )
    thread.start()
    if not ready.wait(2):
        raise AssertionError("fake snapshot agent did not start")
    completed = subprocess.run(
        [str(executable), "snapshot", "--output", str(output_path)],
        env={
            **os.environ,
            "WHITEBOARD_TUI_SOCKET": str(socket_path),
            "WHITEBOARDCTL_TIMEOUT_MS": "1000",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3,
        check=False,
    )
    thread.join(timeout=2)
    if thread.is_alive():
        raise AssertionError("fake snapshot agent did not stop")
    output = output_path.read_bytes() if output_path.exists() else None
    return completed, output, requests


def snapshot_pages() -> tuple[bytes, bytes]:
    first_body = (
        b"META 1 1 0 0 1\n"
        b"CARD 0 note 0 0 4 2 7\n"
        b"\xe4\xb8\xad\nEND\n"
    )
    second_body = b"GLYPH 8 9 65\n"
    first_page = (
        f"OK 9 SNAPSHOT 2 1 0 0 0 {len(first_body)}\n".encode("ascii")
        + first_body
    )
    second_page = (
        f"OK 9 SNAPSHOT 2 1 0 1 1 {len(second_body)}\n".encode("ascii")
        + second_body
    )
    return first_page, second_page


class WhiteboardCtlTests(unittest.TestCase):
    executable: Path

    def test_status_success(self) -> None:
        with ShortSocketWorkspace("whiteboardctl-") as root:
            completed = invoke(self.executable, root, b"OK 7 STATUS 0 0 0 0\n")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.startswith(b"OK 7 STATUS"))

    def test_server_error(self) -> None:
        with ShortSocketWorkspace("whiteboardctl-") as root:
            completed = invoke(self.executable, root, b"ERR missing_card\n")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(b"ERR missing_card", completed.stderr)
        self.assertFalse(completed.stdout)

    def test_invalid_response(self) -> None:
        with ShortSocketWorkspace("whiteboardctl-") as root:
            completed = invoke(self.executable, root, b"garbage\n")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(b"invalid response", completed.stderr)

    def test_timeout(self) -> None:
        with ShortSocketWorkspace("whiteboardctl-") as root:
            completed = invoke(
                self.executable,
                root,
                None,
                delay=0.3,
                timeout_ms=50,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(b"timed out", completed.stderr.lower())

    def test_oversized_batch_is_rejected_before_connecting(self) -> None:
        with ShortSocketWorkspace("whiteboardctl-") as root:
            missing_socket = root / "missing.sock"
            completed = subprocess.run(
                [str(self.executable), "create-cards"],
                input=b"x" * (256 * 1024 + 1),
                env={**os.environ, "WHITEBOARD_TUI_SOCKET": str(missing_socket)},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3,
                check=False,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(b"too large", completed.stderr)

    def test_snapshot_pages_are_assembled_atomically(self) -> None:
        first_page, second_page = snapshot_pages()
        with ShortSocketWorkspace("whiteboardctl-") as root:
            completed, snapshot, requests = invoke_snapshot(
                self.executable,
                root,
                [first_page, second_page],
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(completed.stdout)
        self.assertEqual(
            requests,
            [b"SNAPSHOT - 0 0 0\n", b"SNAPSHOT 9 1 0 0\n"],
        )
        first_body = first_page.split(b"\n", 1)[1]
        second_body = second_page.split(b"\n", 1)[1]
        self.assertEqual(
            snapshot,
            b"WHITEBOARD-SNAPSHOT 2\n" + first_body + second_body + b"END\n",
        )

    def test_stale_snapshot_preserves_existing_output(self) -> None:
        first_page, _ = snapshot_pages()
        with ShortSocketWorkspace("whiteboardctl-") as root:
            completed, snapshot, requests = invoke_snapshot(
                self.executable,
                root,
                [first_page, b"ERR stale_revision 10\n"],
                existing=b"keep",
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(b"stale_revision", completed.stderr)
        self.assertEqual(snapshot, b"keep")
        self.assertEqual(requests[-1], b"SNAPSHOT 9 1 0 0\n")

    def test_unsupported_snapshot_schema_preserves_existing_output(self) -> None:
        first_page, _ = snapshot_pages()
        unsupported_page = first_page.replace(b"SNAPSHOT 2 ", b"SNAPSHOT 999 ", 1)
        with ShortSocketWorkspace("whiteboardctl-") as root:
            completed, snapshot, _ = invoke_snapshot(
                self.executable, root, [unsupported_page], existing=b"keep"
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(b"invalid snapshot response", completed.stderr)
        self.assertEqual(snapshot, b"keep")

    def test_malformed_snapshot_preserves_existing_output(self) -> None:
        malformed_page = b"OK 9 SNAPSHOT 2 1 0 0 1 999\nshort"
        with ShortSocketWorkspace("whiteboardctl-") as root:
            completed, snapshot, _ = invoke_snapshot(
                self.executable,
                root,
                [malformed_page],
                existing=b"keep",
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(b"invalid snapshot response", completed.stderr)
        self.assertEqual(snapshot, b"keep")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    arguments, remaining = parser.parse_known_args()
    WhiteboardCtlTests.executable = arguments.executable.resolve()
    program = unittest.main(argv=[__file__, *remaining], exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
