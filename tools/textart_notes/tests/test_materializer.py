from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from tools.whiteboard_automation.models import (
    CreateCardsResponse,
    LiveCard as ObservedCard,
    LiveStatus as BoardStatus,
    MutationResponse,
)

from tools.textart_notes.materialize_textart import (
    BoardOperationError,
    ManifestError,
    ResultStateError,
    ResultWriter,
    load_plan,
    main,
    materialize,
)


GENERATION = "a" * 64


def write_output(root: Path, cards: list[dict[str, object]] | None = None) -> Path:
    payloads = root / "generations" / GENERATION / "payloads"
    payloads.mkdir(parents=True)
    if cards is None:
        cards = [
            {
                "id": "alpha",
                "format": "text-art",
                "payload": f"generations/{GENERATION}/payloads/alpha.txt",
                "width": 4,
                "height": 2,
                "x": 0,
                "y": 0,
                "metadata": {"source": "A"},
            },
            {
                "id": "beta",
                "format": "text-art",
                "payload": f"generations/{GENERATION}/payloads/beta.txt",
                "width": 5,
                "height": 1,
                "x": 8,
                "y": 3,
                "metadata": {},
            },
        ]
    content = {"manifest_version": 2, "generation": GENERATION, "renderer": "fixture-note", "theme": "unicode-light", "cards": cards}
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(content, ensure_ascii=False) + "\n", encoding="utf-8")
    if any(card.get("id") == "alpha" for card in cards):
        (payloads / "alpha.txt").write_bytes("A中\nok\n".encode())
    if any(card.get("id") == "beta" for card in cards):
        (payloads / "beta.txt").write_bytes("e\u0301\tX\n".encode())
    return manifest


class FakeClient:
    def __init__(self, *, fail_second: bool = False) -> None:
        self.revision = 10
        self.first = 40
        self.fail_second = fail_second
        self.created = False
        self.replaced: list[int] = []
        self.plan = None

    def status(self) -> BoardStatus:
        if not self.created:
            return BoardStatus(10, 3, 1, 0)
        return BoardStatus(self.revision, 5, 1, 1)

    def create_cards(
        self,
        body: bytes,
        expected_revision: int,
    ) -> CreateCardsResponse:
        if expected_revision != self.revision:
            raise AssertionError("materializer did not guard batch creation")
        self.created = True
        self.revision = 11
        self.body = body
        return CreateCardsResponse(self.revision, 2, self.first)

    def replace_card(
        self,
        card_id: int,
        revision: int,
        width: int,
        height: int,
        payload: bytes,
    ) -> MutationResponse:
        self.assert_revision = revision
        if revision != self.revision:
            raise AssertionError("materializer precomputed or lost a revision")
        if self.fail_second and len(self.replaced) == 1:
            raise BoardOperationError("replace-card: ERR injected")
        self.replaced.append(card_id)
        self.revision += 1
        return MutationResponse(self.revision, card_id)

    def get_card(self, card_id: int) -> ObservedCard:
        assert self.plan is not None
        card = self.plan.cards[card_id - self.first]
        return ObservedCard(
            self.revision,
            card_id,
            "text-art",
            card.absolute_x,
            card.absolute_y,
            card.width,
            card.height,
            card.payload,
        )


class MaterializerTests(unittest.TestCase):
    def test_parent_directory_alias_resolves_before_safe_open(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symbolic links are unavailable")
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            manifest_directory = root / "manifest-target"
            manifest = write_output(manifest_directory)
            manifest_alias = root / "manifest-alias"
            manifest_alias.symlink_to(manifest_directory, target_is_directory=True)
            plan = load_plan(manifest_alias / manifest.name, origin_x=0, origin_y=0)
            self.assertEqual([card.logical_id for card in plan.cards], ["alpha", "beta"])

            result_directory = root / "result-target"
            result_directory.mkdir()
            result_alias = root / "result-alias"
            result_alias.symlink_to(result_directory, target_is_directory=True)
            writer = ResultWriter(result_alias / "result.json")
            try:
                writer.write({"status": "ok"})
            finally:
                writer.close()
            self.assertEqual(
                json.loads((result_directory / "result.json").read_text(encoding="utf-8")),
                {"status": "ok"},
            )

    def test_valid_plan_freezes_payloads_and_preserves_manifest_order(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            plan = load_plan(write_output(root), origin_x=-12, origin_y=20)
            self.assertEqual([card.logical_id for card in plan.cards], ["alpha", "beta"])
            self.assertEqual([(card.absolute_x, card.absolute_y) for card in plan.cards], [(-12, 20), (-4, 23)])
            self.assertEqual(
                plan.create_body,
                b"text-art -12 20 4 2\ntext-art -4 23 5 1\n",
            )
            (root / "generations" / GENERATION / "payloads" / "alpha.txt").write_text("changed\n", encoding="utf-8")
            self.assertEqual(plan.cards[0].payload, "A中\nok\n".encode())

    def test_manifest_requires_current_schema(self) -> None:
        for version in (None, 0, 999, True):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as name:
                manifest = write_output(Path(name))
                content = json.loads(manifest.read_text())
                if version is None:
                    del content["manifest_version"]
                else:
                    content["manifest_version"] = version
                manifest.write_text(json.dumps(content))
                with self.assertRaises(ManifestError):
                    load_plan(manifest, origin_x=0, origin_y=0)

    def test_check_only_does_not_require_a_real_socket_or_result_path(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            manifest = write_output(root)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main([
                    "--manifest", str(manifest),
                    "--socket", str(root / "missing.sock"),
                    "--origin-x", "0",
                    "--origin-y", "0",
                    "--result", str(root / "not-created.json"),
                    "--check-only",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["card_count"], 2)
            self.assertFalse((root / "not-created.json").exists())

    def test_materialization_requires_an_explicit_executable(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            main([
                "--manifest", "manifest.json",
                "--socket", "board.sock",
                "--origin-x", "0",
                "--origin-y", "0",
                "--result", "result.json",
            ])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("--whiteboardctl is required", stderr.getvalue())

    def test_schema_format_geometry_and_canonical_path_fail_preflight(self) -> None:
        cases = (
            ("format", lambda card: card.__setitem__("format", "note")),
            ("payload", lambda card: card.__setitem__("payload", "../alpha.txt")),
            ("bool-width", lambda card: card.__setitem__("width", True)),
            ("negative-x", lambda card: card.__setitem__("x", -1)),
            ("unknown", lambda card: card.__setitem__("extra", 1)),
        )
        for label, mutate in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                cards = [{
                    "id": "alpha", "format": "text-art", "payload": f"generations/{GENERATION}/payloads/alpha.txt",
                    "width": 4, "height": 2, "x": 0, "y": 0, "metadata": {},
                }]
                mutate(cards[0])
                manifest = write_output(root, cards)
                with self.assertRaises(ManifestError):
                    load_plan(manifest, origin_x=0, origin_y=0)

    def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(self) -> None:
        for source in (
            '{"renderer":"x","renderer":"y","theme":"ascii","cards":[]}',
            '{"renderer":"x","theme":"ascii","cards":[],"n":NaN}',
        ):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                manifest = root / "manifest.json"
                manifest.write_text(source, encoding="utf-8")
                with self.assertRaises(ManifestError):
                    load_plan(manifest, origin_x=0, origin_y=0)

    def test_payload_newline_width_anchor_and_symlink_are_rejected(self) -> None:
        invalid_payloads = (b"A\n", b"A\nok\n\n", " \u0301\nok\n".encode(), "中文中\nok\n".encode())
        for index, payload in enumerate(invalid_payloads):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                manifest = write_output(root)
                (root / "generations" / GENERATION / "payloads" / "alpha.txt").write_bytes(payload)
                with self.assertRaises(ManifestError):
                    load_plan(manifest, origin_x=0, origin_y=0)

    def test_manifest_payload_directory_and_fifo_are_rejected_without_following_or_blocking(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symbolic links are unavailable")
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            manifest = write_output(root / "rendered")
            linked_manifest = root / "linked-manifest.json"
            linked_manifest.symlink_to(manifest)
            with self.assertRaises(ManifestError):
                load_plan(linked_manifest, origin_x=0, origin_y=0)

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            rendered = root / "rendered"
            manifest = write_output(rendered)
            payloads = rendered / "generations" / GENERATION / "payloads"
            real_payloads = rendered / "real-payloads"
            payloads.rename(real_payloads)
            payloads.symlink_to(real_payloads, target_is_directory=True)
            with self.assertRaises(ManifestError):
                load_plan(manifest, origin_x=0, origin_y=0)

        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory() as name:
                root = Path(name)
                manifest = write_output(root)
                payload = root / "generations" / GENERATION / "payloads" / "alpha.txt"
                payload.unlink()
                os.mkfifo(payload)
                with self.assertRaises(ManifestError):
                    load_plan(manifest, origin_x=0, origin_y=0)

    def test_absolute_geometry_overflow_fails_preflight(self) -> None:
        for origin, relative in ((2**63 - 1, 0), (2**63 - 4, 1), (1, 2**63 - 1)):
            with self.subTest(origin=origin, relative=relative), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                cards = [{
                    "id": "alpha", "format": "text-art", "payload": f"generations/{GENERATION}/payloads/alpha.txt",
                    "width": 4, "height": 2, "x": relative, "y": 0, "metadata": {},
                }]
                manifest = write_output(root, cards)
                with self.assertRaises(ManifestError):
                    load_plan(manifest, origin_x=origin, origin_y=0)
        if hasattr(os, "symlink"):
            with tempfile.TemporaryDirectory() as name:
                root = Path(name)
                manifest = write_output(root)
                target = root / "real.txt"
                target.write_bytes("A中\nok\n".encode())
                (root / "generations" / GENERATION / "payloads" / "alpha.txt").unlink()
                (root / "generations" / GENERATION / "payloads" / "alpha.txt").symlink_to(target)
                with self.assertRaises(ManifestError):
                    load_plan(manifest, origin_x=0, origin_y=0)

    def test_materialize_serializes_revisions_and_verifies_exact_cards(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            plan = load_plan(write_output(root / "rendered"), origin_x=-5, origin_y=7)
            client = FakeClient()
            client.plan = plan
            result_path = root / "result.json"
            writer = ResultWriter(result_path)
            try:
                state = materialize(plan, client, writer, socket_path="/tmp/owned.sock")
            finally:
                writer.close()
            self.assertEqual(client.replaced, [40, 41])
            self.assertEqual(state["status"], "complete")
            self.assertEqual([card["card_id"] for card in state["cards"]], [40, 41])
            self.assertTrue(all(card["status"] == "verified" for card in state["cards"]))
            self.assertEqual(json.loads(result_path.read_text(encoding="utf-8")), state)

    def test_known_partial_failure_preserves_mapping_and_error(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            plan = load_plan(write_output(root / "rendered"), origin_x=0, origin_y=0)
            client = FakeClient(fail_second=True)
            client.plan = plan
            result_path = root / "result.json"
            writer = ResultWriter(result_path)
            try:
                with self.assertRaises(BoardOperationError):
                    materialize(plan, client, writer, socket_path="/tmp/owned.sock")
            finally:
                writer.close()
            state = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "partial")
            self.assertFalse(state["outcome_unknown"])
            self.assertEqual([card["card_id"] for card in state["cards"]], [40, 41])
            self.assertEqual([card["status"] for card in state["cards"]], ["replaced", "pending"])

    def test_result_path_must_be_new_and_non_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path = root / "result.json"
            path.write_text("existing", encoding="utf-8")
            with self.assertRaises(ResultStateError):
                ResultWriter(path)
            if hasattr(os, "symlink"):
                path.unlink()
                target = root / "target.json"
                target.write_text("target", encoding="utf-8")
                path.symlink_to(target)
                with self.assertRaises(ResultStateError):
                    ResultWriter(path)

    def test_replace_response_must_advance_exactly_one_revision(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            plan = load_plan(write_output(root / "rendered"), origin_x=0, origin_y=0)
            client = FakeClient()
            client.plan = plan
            original = client.replace_card

            def wrong_revision(*args, **kwargs):
                response = original(*args, **kwargs)
                return MutationResponse(response.revision + 1, response.object_id)

            client.replace_card = wrong_revision  # type: ignore[method-assign]
            writer = ResultWriter(root / "result.json")
            try:
                with self.assertRaisesRegex(BoardOperationError, "exactly one"):
                    materialize(plan, client, writer, socket_path="/tmp/owned.sock")
            finally:
                writer.close()


if __name__ == "__main__":
    unittest.main()
