#!/usr/bin/env python3
"""List statically declared unittest methods without importing test modules."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


def selectors(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(
        f"{node.name}.{member.name}"
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for member in node.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
        and member.name.startswith("test_")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    arguments = parser.parse_args()
    seen: set[tuple[Path, str]] = set()
    for path in arguments.paths:
        for selector in selectors(path):
            key = (path, selector)
            if key in seen:
                parser.error(f"duplicate test selector: {path}:{selector}")
            seen.add(key)
            print(f"{path}\t{selector}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
