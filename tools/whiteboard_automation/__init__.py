"""Shared whiteboard command-line automation contracts."""

from .client import (
    WhiteboardCtlClient,
    WhiteboardInspectClient,
    resolve_executable,
    run_process,
)
from .errors import CtlError, ProtocolError

__all__ = [
    "CtlError",
    "ProtocolError",
    "WhiteboardCtlClient",
    "WhiteboardInspectClient",
    "resolve_executable",
    "run_process",
]
