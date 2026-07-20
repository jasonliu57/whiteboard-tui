#!/usr/bin/env python3
"""Compare selected C++ and Python values from the frozen Unicode contract."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.textart_notes.core.cell_width import (
    char_width,
    is_control_character,
    is_mark_character,
    is_whitespace_character,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    arguments = parser.parse_args()
    output = subprocess.check_output(
        [arguments.executable, "unicode-dump"],
        text=True,
    )
    for row in output.splitlines():
        raw_codepoint, raw_width, raw_mark, raw_whitespace = row.split(",")
        codepoint = int(raw_codepoint)
        character = chr(codepoint)
        expected_width = -1 if is_control_character(character) else char_width(character)
        observed = (
            int(raw_width),
            bool(int(raw_mark)),
            bool(int(raw_whitespace)),
        )
        expected = (
            expected_width,
            is_mark_character(character),
            is_whitespace_character(character),
        )
        if observed != expected:
            raise SystemExit(
                f"U+{codepoint:04X}: C++ {observed!r} != Python {expected!r}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
