from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from tools.textart_notes.core import manifest as manifest_module
from tools.textart_notes.core.manifest import manifest_data, write_result
from tools.textart_notes.core.models import CardDraft, RenderOptions, RenderResult, ValidationError
from tools.textart_notes.core.validate import validate_result


def published_payload(manifest_path: Path) -> bytes:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return (manifest_path.parent / manifest["cards"][0]["payload"]).read_bytes()


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.options = RenderOptions(theme="ascii", max_width=10, max_height=5)
        self.result = RenderResult(
            renderer="test-card",
            theme="ascii",
            cards=(CardDraft("card-000", "A中", 3, 1),),
        )

    def test_manifest_is_text_art_and_payload_has_one_final_newline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = write_result(self.result, self.options, directory)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["cards"][0]["format"], "text-art")
            payload = Path(directory, manifest["cards"][0]["payload"]).read_bytes()
            self.assertEqual(payload, "A中\n".encode())

    def test_extent_mismatch_is_rejected(self) -> None:
        invalid = RenderResult(
            renderer="test-card",
            theme="ascii",
            cards=(CardDraft("card-000", "too wide", 3, 1),),
        )
        with self.assertRaises(ValidationError):
            validate_result(invalid, self.options)

    def test_boolean_geometry_is_not_accepted_as_an_integer(self) -> None:
        with self.assertRaisesRegex(ValidationError, "max_width must be an integer"):
            validate_result(self.result, RenderOptions(theme="ascii", max_width=True, max_height=5))

    def test_unsafe_id_is_rejected(self) -> None:
        invalid = RenderResult(
            renderer="test-card",
            theme="ascii",
            cards=(CardDraft("../escape", "x", 1, 1),),
        )
        with self.assertRaisesRegex(ValidationError, "invalid card id"):
            validate_result(invalid, self.options)

    def test_payload_symlink_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "generations").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValidationError, "symbolic link"):
                write_result(self.result, self.options, root)

    def test_payload_file_and_manifest_symlinks_are_rejected(self) -> None:
        generation = manifest_data(self.result)["generation"]
        targets = (
            f"generations/{generation}/payloads/card-000.txt",
            "manifest.json",
        )

        for target_name in targets:
            with self.subTest(target=target_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "out"
                (root / target_name).parent.mkdir(parents=True)
                outside = Path(directory) / "outside.txt"
                outside.write_text("unchanged", encoding="utf-8")
                (root / target_name).symlink_to(outside)
                with self.assertRaises(ValidationError):
                    write_result(self.result, self.options, root)
                self.assertEqual(outside.read_text(encoding="utf-8"), "unchanged")

    def test_unanchored_combining_mark_is_rejected(self) -> None:
        invalid = RenderResult(
            renderer="test-card",
            theme="ascii",
            cards=(CardDraft("card-000", "\u0301", 1, 1),),
        )
        with self.assertRaisesRegex(ValidationError, "combining character"):
            validate_result(invalid, self.options)

    def test_generation_switch_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = write_result(self.result, self.options, root)
            previous = manifest_path.read_bytes()
            self.assertEqual(published_payload(manifest_path), "A中\n".encode())

            replacement = RenderResult(
                renderer="test-card",
                theme="ascii",
                cards=(CardDraft("card-000", "new", 3, 1),),
            )
            atomic_write = manifest_module._atomic_write

            def fail_pointer(path: Path, content: bytes) -> None:
                if path == manifest_path:
                    raise OSError("injected pointer failure")
                atomic_write(path, content)

            with patch.object(manifest_module, "_atomic_write", fail_pointer):
                with self.assertRaisesRegex(OSError, "pointer failure"):
                    write_result(replacement, self.options, root)

            self.assertEqual(manifest_path.read_bytes(), previous)
            self.assertEqual(
                published_payload(manifest_path),
                "A中\n".encode(),
            )

            write_result(replacement, self.options, root)
            self.assertEqual(
                published_payload(manifest_path),
                b"new\n",
            )

    def test_identical_generation_publishers_converge_without_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            with ThreadPoolExecutor(max_workers=8) as workers:
                paths = list(
                    workers.map(
                        lambda _: write_result(self.result, self.options, root),
                        range(32),
                    )
                )

            self.assertTrue(all(path == root / "manifest.json" for path in paths))
            generation = manifest_data(self.result)["generation"]
            entries = list((root / "generations").iterdir())
            self.assertEqual(entries, [root / "generations" / generation])
            self.assertEqual(
                published_payload(root / "manifest.json"),
                "A中\n".encode(),
            )


if __name__ == "__main__":
    unittest.main()
