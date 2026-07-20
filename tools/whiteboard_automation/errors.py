"""Errors shared by whiteboard automation clients and parsers."""

from __future__ import annotations


class ProtocolError(Exception):
    """A command response or canonical snapshot is malformed."""


class CtlError(Exception):
    """A command failed, timed out, or could not be executed."""

    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        stderr: bytes = b"",
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr
        self.outcome_unknown = outcome_unknown
