#!/usr/bin/env python3
"""Reject broken local Markdown links in the project documentation."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = [
    ROOT / "README.md",
    ROOT / "web" / "README.md",
    *sorted((ROOT / "docs").glob("*.md")),
    *sorted((ROOT / ".agents" / "skills").rglob("*.md")),
]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def local_target(raw: str) -> str | None:
    target = raw.strip()

    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    else:
        target = target.split(maxsplit=1)[0]

    if target.startswith(("#", "http://", "https://", "mailto:")):
        return None

    path = unquote(target.split("#", 1)[0])
    return path or None


def main() -> int:
    failures: list[str] = []

    for document in DOCUMENTS:
        text = document.read_text(encoding="utf-8")

        for match in LINK.finditer(text):
            target = local_target(match.group(1))

            if target is None:
                continue

            resolved = (document.parent / target).resolve()

            try:
                resolved.relative_to(ROOT)
            except ValueError:
                failures.append(
                    f"{document.relative_to(ROOT)}: local link escapes repository: {target}"
                )
                continue

            if not resolved.exists():
                failures.append(
                    f"{document.relative_to(ROOT)}: missing local link target: {target}"
                )

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    print(f"checked {len(DOCUMENTS)} documentation files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
