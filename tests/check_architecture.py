#!/usr/bin/env python3
"""Check dependency boundaries that keep renderers and automation separate."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.textart_notes.render_note import STYLE_SPECS  # noqa: E402


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def renderer_modules() -> tuple[Path, ...]:
    registered = tuple(
        ROOT / "tools" / "textart_notes" / f"{spec.module}.py"
        for spec in STYLE_SPECS
    )
    shared = tuple(
        path
        for directory in (
            ROOT / "tools" / "textart_notes" / "core",
            ROOT / "tools" / "textart_notes" / "layouts",
        )
        for path in directory.glob("*.py")
        if path.name != "__init__.py"
    )
    return (*registered, *shared)


def shared_definitions(names: set[str]) -> dict[str, list[tuple[Path, int]]]:
    definitions = {name: [] for name in names}
    for base in (
        ROOT / "tools",
        ROOT / ".agents" / "skills" / "whiteboard-markdown-mind-map" / "scripts",
    ):
        for path in base.rglob("*.py"):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names:
                    definitions[node.name].append((path, node.lineno))
    return definitions


def main() -> int:
    failures: list[str] = []
    forbidden_roots = {"socket", "subprocess"}
    forbidden_prefix = "tools.whiteboard_automation"

    for path in renderer_modules():
        for module in sorted(imported_modules(path)):
            if module.split(".", 1)[0] in forbidden_roots or module.startswith(
                forbidden_prefix
            ):
                failures.append(
                    f"{path.relative_to(ROOT)}: forbidden renderer dependency {module}"
                )

    expected_definitions = {
        "WhiteboardCtlClient": ROOT / "tools" / "whiteboard_automation" / "client.py",
        "run_process": ROOT / "tools" / "whiteboard_automation" / "client.py",
        "parse_status": ROOT / "tools" / "whiteboard_automation" / "protocol.py",
        "parse_card_response": ROOT / "tools" / "whiteboard_automation" / "protocol.py",
        "parse_edges_response": ROOT / "tools" / "whiteboard_automation" / "protocol.py",
        "parse_create_cards_response": ROOT / "tools" / "whiteboard_automation" / "protocol.py",
        "parse_replace_card_response": ROOT / "tools" / "whiteboard_automation" / "protocol.py",
        "parse_connect_response": ROOT / "tools" / "whiteboard_automation" / "protocol.py",
        "parse_delete_cards_response": ROOT / "tools" / "whiteboard_automation" / "protocol.py",
        "parse_canonical_snapshot": ROOT / "tools" / "whiteboard_automation" / "snapshot.py",
        "encode_create_cards": ROOT / "tools" / "whiteboard_automation" / "batch.py",
        "encode_delete_cards": ROOT / "tools" / "whiteboard_automation" / "batch.py",
    }
    definitions = shared_definitions(set(expected_definitions))
    for name, expected in expected_definitions.items():
        found = definitions[name]
        if len(found) == 1 and found[0][0] == expected:
            continue
        rendered = ", ".join(
            f"{path.relative_to(ROOT)}:{line}" for path, line in found
        )
        failures.append(
            f"{name} must have one implementation in {expected.relative_to(ROOT)}; "
            f"found {rendered or 'none'}"
        )

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("architecture boundaries are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
