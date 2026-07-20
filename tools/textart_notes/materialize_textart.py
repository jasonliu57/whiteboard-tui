#!/usr/bin/env python3
"""Materialize a validated renderer generation into text-art cards."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.frozen_generation import (
    ManifestError,
    MaterialCard,
    MaterializationPlan,
    load_plan,
    open_directory_chain,
)
from tools.whiteboard_automation.client import (
    WhiteboardCtlClient,
    resolve_executable,
    validate_local_endpoint,
)
from tools.whiteboard_automation.errors import CtlError, ProtocolError
from tools.whiteboard_automation.models import LiveCard as ObservedCard


class MaterializerError(Exception):
    """Base class for materializer state and Board failures."""


class ResultStateError(MaterializerError):
    """The durable result state could not be updated."""


class BoardOperationError(MaterializerError):
    """A whiteboardctl operation failed or has an unknown outcome."""

    def __init__(self, message: str, *, outcome_unknown: bool = False) -> None:
        super().__init__(message)
        self.outcome_unknown = outcome_unknown


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    offset = 0
    while offset < len(view):
        written = os.write(descriptor, view[offset:])
        if written <= 0:
            raise OSError("short write while checkpointing result state")
        offset += written


class ResultWriter:
    """Create and atomically checkpoint a machine-readable state file."""

    def __init__(self, path: str | Path) -> None:
        absolute = Path(os.path.abspath(path))
        self.path = absolute
        self.name = absolute.name
        self.directory_fd = open_directory_chain(absolute.parent, "result directory")
        self.counter = 0
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(self.name, flags, 0o600, dir_fd=self.directory_fd)
        except OSError as error:
            os.close(self.directory_fd)
            raise ResultStateError(f"result path must be a new non-symlink file: {error}") from error
        os.close(descriptor)

    def close(self) -> None:
        if self.directory_fd >= 0:
            os.close(self.directory_fd)
            self.directory_fd = -1

    def write(self, state: Mapping[str, object]) -> None:
        if self.directory_fd < 0:
            raise ResultStateError("result writer is closed")
        try:
            encoded = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        except (TypeError, ValueError) as error:
            raise ResultStateError(f"result state is not JSON serializable: {error}") from error
        self.counter += 1
        temporary = f".{self.name}.tmp-{os.getpid()}-{self.counter}"
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = -1
        try:
            descriptor = os.open(temporary, flags, 0o600, dir_fd=self.directory_fd)
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(
                temporary,
                self.name,
                src_dir_fd=self.directory_fd,
                dst_dir_fd=self.directory_fd,
            )
            os.fsync(self.directory_fd)
        except OSError as error:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=self.directory_fd)
            except OSError:
                pass
            raise ResultStateError(f"cannot checkpoint result state: {error}") from error


def _plan_card_state(card: MaterialCard) -> dict[str, object]:
    return {
        "logical_id": card.logical_id,
        "card_id": None,
        "status": "pending",
        "format": "text-art",
        "payload": card.payload_name,
        "payload_sha256": card.payload_sha256,
        "x": card.absolute_x,
        "y": card.absolute_y,
        "width": card.width,
        "height": card.height,
    }


def _base_state(plan: MaterializationPlan, socket_path: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "preflight",
        "manifest": {
            "path": plan.manifest_path,
            "sha256": plan.manifest_sha256,
            "renderer": plan.renderer,
            "theme": plan.theme,
        },
        "socket": str(Path(os.path.abspath(socket_path))),
        "origin": {"x": plan.origin_x, "y": plan.origin_y},
        "initial_board": None,
        "latest_revision": None,
        "cards": [_plan_card_state(card) for card in plan.cards],
        "error": None,
        "outcome_unknown": False,
    }


def _verify_observed(card: MaterialCard, card_id: int, observed: ObservedCard, revision: int) -> None:
    expected = (
        card_id,
        "text-art",
        card.absolute_x,
        card.absolute_y,
        card.width,
        card.height,
        card.payload,
    )
    actual = (
        observed.card_id,
        observed.format_name,
        observed.x,
        observed.y,
        observed.width,
        observed.height,
        observed.payload,
    )
    if observed.revision != revision:
        raise BoardOperationError("get: Board revision changed during verification")
    if actual != expected:
        raise BoardOperationError(f"get: card {card_id} does not match materialization plan")


def materialize(
    plan: MaterializationPlan,
    client: WhiteboardCtlClient,
    result: ResultWriter,
    *,
    socket_path: str,
) -> dict[str, object]:
    """Create, populate, verify, and checkpoint one validated plan."""

    state = _base_state(plan, socket_path)
    result.write(state)
    try:
        initial = client.status()
        state["initial_board"] = {
            "revision": initial.revision,
            "cards": initial.cards,
            "edges": initial.edges,
            "dirty": initial.dirty,
        }
        created = client.create_cards(plan.create_body, initial.revision)
        if created.count != len(plan.cards):
            raise BoardOperationError("create-cards: response count mismatch", outcome_unknown=True)
        if created.first_card_id + created.count > 2**32 - 1:
            raise BoardOperationError("create-cards: invalid CardId range", outcome_unknown=True)
        revision = created.revision
        first = created.first_card_id
        state["status"] = "created"
        state["latest_revision"] = revision
        card_states = state["cards"]
        assert isinstance(card_states, list)
        for index, card_state in enumerate(card_states):
            assert isinstance(card_state, dict)
            card_state["card_id"] = first + index
        result.write(state)

        state["status"] = "materializing"
        for index, card in enumerate(plan.cards):
            card_id = first + index
            replaced = client.replace_card(card_id, revision, card.width, card.height, card.payload)
            if replaced.object_id != card_id:
                raise BoardOperationError("replace-card: CardId mismatch", outcome_unknown=True)
            if replaced.revision != revision + 1:
                raise BoardOperationError(
                    "replace-card: revision did not advance by exactly one",
                    outcome_unknown=True,
                )
            revision = replaced.revision
            state["latest_revision"] = revision
            card_state = card_states[index]
            assert isinstance(card_state, dict)
            card_state["status"] = "replaced"
            card_state["revision"] = revision
            result.write(state)

        state["status"] = "verifying"
        for index, card in enumerate(plan.cards):
            card_id = first + index
            observed = client.get_card(card_id)
            _verify_observed(card, card_id, observed, revision)
            card_state = card_states[index]
            assert isinstance(card_state, dict)
            card_state["status"] = "verified"
            result.write(state)

        final = client.status()
        if final.revision != revision:
            raise BoardOperationError("status: Board revision changed after verification")
        if final.cards != initial.cards + len(plan.cards) or final.edges != initial.edges:
            raise BoardOperationError("status: Board counts do not match materialization")
        state["status"] = "complete"
        state["final_board"] = {
            "revision": final.revision,
            "cards": final.cards,
            "edges": final.edges,
            "dirty": final.dirty,
        }
        result.write(state)
        return state
    except Exception as error:
        state["status"] = "partial"
        state["error"] = f"{type(error).__name__}: {error}"
        state["outcome_unknown"] = bool(getattr(error, "outcome_unknown", False))
        try:
            result.write(state)
        except ResultStateError:
            pass
        raise


def _validated_summary(plan: MaterializationPlan) -> dict[str, object]:
    return {
        "status": "validated",
        "renderer": plan.renderer,
        "theme": plan.theme,
        "manifest_sha256": plan.manifest_sha256,
        "card_count": len(plan.cards),
        "payload_bytes": sum(len(card.payload) for card in plan.cards),
        "create_request_bytes": len(plan.create_body),
        "origin": {"x": plan.origin_x, "y": plan.origin_y},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize a validated text-art manifest")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--origin-x", required=True, type=int)
    parser.add_argument("--origin-y", required=True, type=int)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument(
        "--whiteboardctl", type=Path, help="executable path; required unless --check-only"
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--check-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if not arguments.check_only and arguments.whiteboardctl is None:
        parser.error("--whiteboardctl is required unless --check-only")
    try:
        plan = load_plan(arguments.manifest, origin_x=arguments.origin_x, origin_y=arguments.origin_y)
        if arguments.check_only:
            print(json.dumps(_validated_summary(plan), ensure_ascii=False, sort_keys=True))
            return 0
        if not 0.1 <= arguments.timeout <= 60:
            raise ManifestError("timeout must be between 0.1 and 60 seconds")
        ctl_path = resolve_executable(arguments.whiteboardctl)
        validate_local_endpoint(ctl_path, arguments.socket)
        client = WhiteboardCtlClient(
            ctl_path,
            str(Path(os.path.abspath(arguments.socket))),
            arguments.timeout,
        )
        writer = ResultWriter(arguments.result)
        try:
            state = materialize(plan, client, writer, socket_path=str(arguments.socket))
        finally:
            writer.close()
        print(json.dumps(state, ensure_ascii=False, sort_keys=True))
        return 0
    except (ManifestError, ResultStateError) as error:
        print(f"materialize-textart: invalid input or state path: {error}", file=sys.stderr)
        return 2
    except (BoardOperationError, CtlError, ProtocolError) as error:
        print(f"materialize-textart: Board operation failed: {error}", file=sys.stderr)
        return 3
    except (OSError, ValueError, TypeError) as error:
        print(f"materialize-textart: unexpected validation failure: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
