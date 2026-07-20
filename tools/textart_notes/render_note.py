#!/usr/bin/env python3
"""Dispatch the uniform renderer CLI to one of the registered note styles."""

from __future__ import annotations

import argparse
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.textart_notes.core.cli import (
    Renderer,
    add_render_arguments,
    execute_renderer,
)


@dataclass(frozen=True)
class StyleSpec:
    style: str
    module: str
    manifest_renderer: str


STYLE_SPECS = (
    StyleSpec("outline", "outline_note", "outline-note"),
    StyleSpec("cornell", "cornell_note", "cornell-note"),
    StyleSpec("mindmap", "mindmap_note", "mindmap-note"),
    StyleSpec("concept-map", "concept_map_note", "concept-map"),
    StyleSpec("flowchart", "flowchart_note", "flowchart-note"),
    StyleSpec("comparison", "comparison_table_note", "comparison-table"),
    StyleSpec("timeline", "timeline_note", "timeline-note"),
    StyleSpec("qa", "qa_note", "qa-note"),
    StyleSpec("atomic-card", "atomic_card_note", "atomic-card-note"),
    StyleSpec("sentence", "sentence_note", "sentence-note"),
    StyleSpec("boxed", "boxed_note", "boxed-note"),
    StyleSpec("two-column", "two_column_note", "two-column-note"),
    StyleSpec("three-column", "three_column_note", "three-column"),
    StyleSpec("matrix", "matrix_note", "matrix-note"),
    StyleSpec("kanban", "kanban_note", "kanban-note"),
    StyleSpec("journal", "journal_note", "journal-note"),
    StyleSpec("sketchnote", "sketchnote", "sketchnote"),
    StyleSpec("annotated", "annotated_note", "annotated-note"),
    StyleSpec("template", "template_note", "template-note"),
    StyleSpec("summary", "summary_card_note", "summary-card"),
    StyleSpec("fishbone", "fishbone_note", "fishbone-note"),
)
STYLE_NAMES = tuple(spec.style for spec in STYLE_SPECS)
_BY_STYLE = {spec.style: spec for spec in STYLE_SPECS}


def load_renderer(style: str) -> tuple[StyleSpec, Renderer]:
    """Load a registered renderer lazily and verify its public identity."""

    try:
        spec = _BY_STYLE[style]
    except KeyError as error:
        raise ValueError(f"unknown style {style!r}") from error
    module = importlib.import_module(f"tools.textart_notes.{spec.module}")
    if getattr(module, "RENDERER", None) != spec.manifest_renderer:
        raise RuntimeError(
            f"registry mismatch for {style!r}: expected renderer "
            f"{spec.manifest_renderer!r}"
        )
    renderer = getattr(module, "render", None)
    if not callable(renderer):
        raise RuntimeError(f"registered module {spec.module!r} has no render function")
    return spec, renderer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render one of the registered note styles as text-art cards"
    )
    parser.add_argument("--style", required=True, choices=STYLE_NAMES)
    parser.add_argument(
        "--list-styles",
        action="store_true",
        help="list the style, manifest renderer, and module registry",
    )
    add_render_arguments(parser)
    return parser


def list_styles() -> str:
    rows = ["style\tmanifest-renderer\tmodule"]
    rows.extend(
        f"{spec.style}\t{spec.manifest_renderer}\t{spec.module}"
        for spec in STYLE_SPECS
    )
    return "\n".join(rows)


def main(argv: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if values == ["--list-styles"]:
        print(list_styles())
        return 0
    arguments = build_parser().parse_args(values)
    if arguments.list_styles:
        build_parser().error("--list-styles must be used by itself")
    spec, renderer = load_renderer(arguments.style)
    return execute_renderer(spec.manifest_renderer, renderer, arguments)


if __name__ == "__main__":
    raise SystemExit(main())
