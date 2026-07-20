"""Subprocess adapter for whiteboardctl and whiteboard-inspect."""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .batch import encode_delete_cards
from .errors import CtlError
from .files import atomic_write_bytes
from .models import (
    CreateCardsResponse,
    DeleteCardsResponse,
    EdgeResponse,
    LiveCard,
    LiveStatus,
    MutationResponse,
    QueryResponse,
    ViewState,
)
from .protocol import (
    parse_card_response,
    parse_connect_response,
    parse_create_cards_response,
    parse_delete_cards_response,
    parse_edges_response,
    parse_query_response,
    parse_replace_card_response,
    parse_status,
    parse_view,
)


def resolve_executable(path: str | Path) -> Path:
    """Validate an explicit executable path without searching other locations."""
    candidate = Path(os.path.abspath(path))
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise CtlError(f"executable not found at {candidate}")
    return candidate


def validate_local_endpoint(executable: Path, socket: str | Path) -> None:
    socket_path = Path(os.path.abspath(socket))
    try:
        executable_info = os.lstat(executable)
        socket_info = os.lstat(socket_path)
    except OSError as error:
        raise CtlError(f"cannot inspect whiteboardctl/socket: {error}") from error
    if stat.S_ISLNK(executable_info.st_mode) or not stat.S_ISREG(executable_info.st_mode):
        raise CtlError("whiteboardctl must be a non-symlink regular file")
    if not os.access(executable, os.X_OK):
        raise CtlError("whiteboardctl is not executable")
    if stat.S_ISLNK(socket_info.st_mode) or not stat.S_ISSOCK(socket_info.st_mode):
        raise CtlError("socket must be an existing non-symlink Unix socket")


def run_process(
    executable: Path,
    arguments: list[str],
    *,
    socket: str | None = None,
    timeout: float = 10.0,
    input_bytes: bytes | None = None,
    mutation: bool = False,
) -> bytes:
    environment = os.environ.copy()
    if socket is not None:
        environment["WHITEBOARD_TUI_SOCKET"] = str(socket)
    try:
        result = subprocess.run(
            [str(executable), *arguments],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise CtlError(
            f"{executable.name}: timed out after {timeout:g} seconds",
            outcome_unknown=mutation,
        ) from error
    except OSError as error:
        raise CtlError(
            f"{executable.name}: {error}",
            outcome_unknown=mutation,
        ) from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        message = f"{executable.name}: exit {result.returncode}"
        if detail:
            message += f": {detail}"
        known_rejection = result.stderr.startswith(b"ERR ")
        raise CtlError(
            message,
            returncode=result.returncode,
            stderr=result.stderr,
            outcome_unknown=mutation and not known_rejection,
        )
    return result.stdout


@dataclass(frozen=True)
class WhiteboardCtlClient:
    executable: Path
    socket: str
    timeout: float = 10.0

    def raw(self, *arguments: str) -> bytes:
        return run_process(
            self.executable,
            list(arguments),
            socket=self.socket,
            timeout=self.timeout,
        )

    def _mutate(self, arguments: list[str], body: bytes | None = None) -> bytes:
        return run_process(
            self.executable,
            arguments,
            socket=self.socket,
            timeout=self.timeout,
            input_bytes=body,
            mutation=True,
        )

    def status(self) -> LiveStatus:
        return parse_status(self.raw("status"))

    def view(self) -> ViewState:
        return parse_view(self.raw("view"))

    def get_card(self, card_id: int) -> LiveCard:
        return parse_card_response(self.raw("get", str(card_id)))

    def query(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        limit: int = 256,
    ) -> QueryResponse:
        return parse_query_response(
            self.raw(
                "query",
                str(left),
                str(top),
                str(right),
                str(bottom),
                str(limit),
            )
        )

    def edges(self, card_id: int) -> EdgeResponse:
        return parse_edges_response(self.raw("edges", str(card_id)))

    def create_cards(self, batch: bytes, revision: int) -> CreateCardsResponse:
        return parse_create_cards_response(
            self._mutate(["create-cards", str(revision)], batch)
        )

    def replace_card(
        self,
        card_id: int,
        revision: int,
        width: int,
        height: int,
        payload: bytes,
    ) -> MutationResponse:
        return parse_replace_card_response(
            self._mutate(
                [
                    "replace-card",
                    str(card_id),
                    str(revision),
                    str(width),
                    str(height),
                ],
                payload,
            )
        )

    def connect(
        self,
        source_card_id: int,
        target_card_id: int,
        revision: int,
    ) -> MutationResponse:
        return parse_connect_response(
            self._mutate(
                [
                    "connect",
                    str(source_card_id),
                    str(target_card_id),
                    str(revision),
                ]
            )
        )

    def delete_cards(self, card_ids: tuple[int, ...], revision: int) -> DeleteCardsResponse:
        return parse_delete_cards_response(
            self._mutate(
                ["delete-cards", str(revision)],
                encode_delete_cards(card_ids),
            )
        )

    def snapshot(self, output: Path) -> bytes:
        self.raw("snapshot", "--output", str(output))
        try:
            return output.read_bytes()
        except OSError as error:
            raise CtlError(f"whiteboardctl: cannot read snapshot {output}: {error}") from error

    def board_png(self, output: Path, max_side: int = 1600) -> bytes:
        data = self.raw("board-png", str(max_side), "id")
        atomic_write_bytes(output, data)
        return data


@dataclass(frozen=True)
class WhiteboardInspectClient:
    executable: Path
    timeout: float = 10.0

    def snapshot(self, board_path: Path, output: Path) -> bytes:
        run_process(
            self.executable,
            ["snapshot", str(board_path), "--output", str(output)],
            timeout=self.timeout,
        )
        try:
            return output.read_bytes()
        except OSError as error:
            raise CtlError(f"whiteboard-inspect: cannot read snapshot {output}: {error}") from error
