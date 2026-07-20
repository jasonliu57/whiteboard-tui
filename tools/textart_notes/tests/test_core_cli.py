from __future__ import annotations

import argparse
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from tools.textart_notes.core.cli import execute_renderer, load_input
from tools.textart_notes.core.models import (
    CardDraft,
    FitError,
    InputError,
    RenderOptions,
    RenderResult,
)


class CliInputTests(unittest.TestCase):
    def test_duplicate_keys_are_rejected_at_every_object_depth(self) -> None:
        for source in ('{"id": 1, "id": 2}', '{"outer": {"id": 1, "id": 2}}'):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as name:
                path = Path(name) / "input.json"
                path.write_text(source, encoding="utf-8")
                with self.assertRaisesRegex(InputError, "duplicate JSON object key 'id'"):
                    load_input(path)


class CliExecutionTests(unittest.TestCase):
    @staticmethod
    def arguments(root: Path, *, check_only: bool = False) -> argparse.Namespace:
        source = root / "input.json"
        source.write_text('{"title":"Example"}\n', encoding="utf-8")
        return argparse.Namespace(
            input=source,
            output_dir=root / "output",
            theme="ascii",
            max_width=20,
            max_height=10,
            check_only=check_only,
            single_card=False,
        )

    @staticmethod
    def renderer(
        data: dict[str, object],
        options: RenderOptions,
    ) -> RenderResult:
        if data != {"title": "Example"}:
            raise AssertionError(data)
        return RenderResult(
            "fixture-note",
            options.theme,
            (CardDraft("card", "ok", 2, 1),),
        )

    def test_success_writes_one_valid_generation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            result = execute_renderer(
                "fixture-note",
                self.renderer,
                self.arguments(root),
            )
            self.assertEqual(result, 0)
            self.assertTrue((root / "output" / "manifest.json").is_file())

    def test_check_only_validates_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            result = execute_renderer(
                "fixture-note",
                self.renderer,
                self.arguments(root, check_only=True),
            )
            self.assertEqual(result, 0)
            self.assertFalse((root / "output").exists())

    def test_fit_error_maps_to_exit_one(self) -> None:
        def cannot_fit(
            _data: dict[str, object],
            _options: RenderOptions,
        ) -> RenderResult:
            raise FitError("too small")

        with tempfile.TemporaryDirectory() as name, redirect_stderr(io.StringIO()):
            root = Path(name)
            result = execute_renderer(
                "fixture-note",
                cannot_fit,
                self.arguments(root, check_only=True),
            )
            self.assertEqual(result, 1)

    def test_invalid_input_maps_to_exit_two(self) -> None:
        def invalid(
            _data: dict[str, object],
            _options: RenderOptions,
        ) -> RenderResult:
            raise InputError("invalid fixture")

        with tempfile.TemporaryDirectory() as name, redirect_stderr(io.StringIO()):
            root = Path(name)
            result = execute_renderer(
                "fixture-note",
                invalid,
                self.arguments(root, check_only=True),
            )
            self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
