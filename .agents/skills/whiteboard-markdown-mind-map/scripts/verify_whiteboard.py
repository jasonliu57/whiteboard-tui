#!/usr/bin/env python3
"""Verify compiled whiteboard artifacts against live and persisted state."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from whiteboard_validation.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
