from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.textart_notes.render_note import STYLE_SPECS, StyleSpec


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tools" / "textart_notes" / "tests" / "fixtures"


class RendererEntrypointTests(unittest.TestCase):
    """One process-boundary smoke per published renderer entrypoint."""


def entrypoint_test(spec: StyleSpec):
    def test(self: RendererEntrypointTests) -> None:
        with tempfile.TemporaryDirectory(prefix="renderer-entrypoint-") as name:
            root = Path(name)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "tools" / "textart_notes" / f"{spec.module}.py"),
                    "--input",
                    str(FIXTURES / spec.style.replace("-", "_") / "input.json"),
                    "--output-dir",
                    str(root / "output"),
                    "--max-width",
                    "160",
                    "--max-height",
                    "100",
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
            manifest = json.loads(
                (root / "output" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["renderer"], spec.manifest_renderer)

    return test


for style_spec in STYLE_SPECS:
    setattr(
        RendererEntrypointTests,
        f"test_{style_spec.style.replace('-', '_')}",
        entrypoint_test(style_spec),
    )


if __name__ == "__main__":
    unittest.main()
