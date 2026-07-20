from __future__ import annotations

import tempfile
from pathlib import Path
from types import TracebackType


class ShortSocketWorkspace:
    """A unique temporary directory with paths short enough for Unix sockets."""

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._temporary: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> Path:
        short_root = "/tmp" if Path("/tmp").is_dir() else None
        self._temporary = tempfile.TemporaryDirectory(
            prefix=self._prefix,
            dir=short_root,
        )
        return Path(self._temporary.name)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
