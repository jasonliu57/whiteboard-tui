from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.textart_notes.render_note import STYLE_NAMES, STYLE_SPECS, list_styles, load_renderer


ROOT = Path(__file__).resolve().parents[3]
DISPATCHER = ROOT / "tools" / "textart_notes" / "render_note.py"

class DispatcherTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, "-B", str(DISPATCHER), *arguments],
            capture_output=True,
            check=False,
            env=environment,
        )

    def test_registry_has_exactly_twenty_one_unique_verified_styles(self) -> None:
        self.assertEqual(len(STYLE_SPECS), 21)
        self.assertEqual(len(STYLE_NAMES), len(set(STYLE_NAMES)))
        self.assertEqual(
            STYLE_NAMES,
            (
                "outline",
                "cornell",
                "mindmap",
                "concept-map",
                "flowchart",
                "comparison",
                "timeline",
                "qa",
                "atomic-card",
                "sentence",
                "boxed",
                "two-column",
                "three-column",
                "matrix",
                "kanban",
                "journal",
                "sketchnote",
                "annotated",
                "template",
                "summary",
                "fishbone",
            ),
        )
        for spec in STYLE_SPECS:
            loaded, renderer = load_renderer(spec.style)
            self.assertEqual(loaded, spec)
            self.assertTrue(callable(renderer))

    def test_list_styles_matches_the_registry(self) -> None:
        expected = list_styles() + "\n"
        completed = self.run_cli("--list-styles")
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertEqual(completed.stdout, expected.encode("utf-8"))
        self.assertEqual(len(expected.splitlines()), 22)

    def test_unknown_style_is_a_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            completed = self.run_cli(
                "--style",
                "not-a-style",
                "--input",
                str(root / "missing.json"),
                "--output-dir",
                str(root / "output"),
            )
            self.assertEqual(completed.returncode, 2)


if __name__ == "__main__":
    unittest.main()
