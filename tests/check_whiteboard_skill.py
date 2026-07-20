#!/usr/bin/env python3
"""Check the repository-local whiteboard skill structure and linear workflow."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "whiteboard-markdown-mind-map"


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if match is None:
        raise ValueError(f"{path}: missing YAML frontmatter")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator or not key or not value.strip() or key in fields:
            raise ValueError(f"{path}: invalid frontmatter line {line!r}")
        fields[key] = value.strip()
    return fields


def check_skill(directory: Path, expected_name: str) -> list[str]:
    failures: list[str] = []
    required = {
        "SKILL.md",
        "agents/openai.yaml",
        "references/artifact-contract.md",
        "references/board-workflow.md",
        "references/renderer-catalog.md",
    }
    for relative in sorted(required):
        if not (directory / relative).is_file():
            failures.append(f"{directory.relative_to(ROOT)}: missing {relative}")
    try:
        fields = frontmatter(directory / "SKILL.md")
    except (OSError, UnicodeError, ValueError) as error:
        failures.append(str(error))
        return failures
    if set(fields) != {"name", "description"}:
        failures.append(f"{directory.relative_to(ROOT)}: frontmatter keys must be name and description")
    if fields.get("name") != expected_name:
        failures.append(f"{directory.relative_to(ROOT)}: unexpected skill name")
    metadata = (directory / "agents" / "openai.yaml").read_text(encoding="utf-8")
    if f"${expected_name}" not in metadata:
        failures.append(f"{directory.relative_to(ROOT)}: default_prompt must name the skill")
    return failures


def main() -> int:
    failures = check_skill(SKILL, "whiteboard-markdown-mind-map")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("whiteboard skill structure is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
