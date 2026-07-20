"""Uniform command-line adapter used by all style entry scripts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Sequence

from .manifest import write_result
from .models import FitError, InputError, RenderOptions, RenderResult, ValidationError
from .contracts import MAX_RENDERER_INPUT_BYTES
from .strict_json import StrictJsonError, loads_object
from .validate import validate_result

Renderer = Callable[[dict[str, object], RenderOptions], RenderResult]


def build_parser(renderer_name: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"Render {renderer_name} notes as text-art cards")
    add_render_arguments(parser)
    return parser


def add_render_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the frozen renderer CLI options to an existing parser."""

    parser.add_argument("--input", required=True, type=Path, help="UTF-8 JSON object")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--theme",
        choices=("ascii", "unicode-light", "unicode-rich"),
        default="unicode-light",
    )
    parser.add_argument("--max-width", type=int, default=120)
    parser.add_argument("--max-height", type=int, default=70)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--single-card", action="store_true")


def load_input(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise InputError(f"cannot read input: {error}") from error

    if len(raw) > MAX_RENDERER_INPUT_BYTES:
        raise InputError(
            f"input exceeds {MAX_RENDERER_INPUT_BYTES} bytes"
        )

    try:
        return loads_object(raw, label="input")
    except StrictJsonError as error:
        raise InputError(str(error)) from error


def execute_renderer(
    renderer_name: str,
    renderer: Renderer,
    arguments: argparse.Namespace,
) -> int:
    """Execute one renderer from an already parsed common CLI namespace."""

    options = RenderOptions(
        theme=arguments.theme,
        max_width=arguments.max_width,
        max_height=arguments.max_height,
        single_card=arguments.single_card,
    )
    try:
        result = renderer(load_input(arguments.input), options)
        validate_result(result, options)
        if not arguments.check_only:
            write_result(result, options, arguments.output_dir)
    except FitError as error:
        print(f"{renderer_name}: cannot fit: {error}", file=sys.stderr)
        return 1
    except (InputError, ValidationError, ValueError, TypeError) as error:
        print(f"{renderer_name}: invalid input or output: {error}", file=sys.stderr)
        return 2
    return 0


def run_renderer(renderer_name: str, renderer: Renderer, argv: Sequence[str] | None = None) -> int:
    parser = build_parser(renderer_name)
    return execute_renderer(renderer_name, renderer, parser.parse_args(argv))
