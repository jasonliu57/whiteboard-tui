#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "mindmap_tools.py"
ROOT = SCRIPT.parents[4]
SPEC = importlib.util.spec_from_file_location("mindmap_tools", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MINDMAP_TOOLS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MINDMAP_TOOLS
SPEC.loader.exec_module(MINDMAP_TOOLS)


PLAN = textwrap.dedent(
    """\
    # Design

    A left-to-right format sampler.

    # Units

    ## n-root

    kind: native
    format: markdown
    group: -
    title: Root

    why: Preserve the authored content in its native format.

    ~~~payload
    # Root

    Overview.
    ~~~

    ## n-note

    kind: native
    format: note
    group: note-group
    title: Note

    why: Preserve the authored content in its native format.

    ~~~payload
    A concise note.
    ~~~

    ## n-code

    kind: native
    format: code
    group: code-group
    title: Code

    why: Preserve the authored content in its native format.

    ~~~payload
    int main() { return 0; }
    ~~~

    ## n-todo

    kind: native
    format: todo
    group: todo-group
    title: Todo

    why: Preserve the authored content in its native format.

    ~~~payload
    - [ ] first
    - [x] second
    ~~~

    ## n-table

    kind: native
    format: csv
    group: table-group
    title: Table

    why: Preserve the authored content in its native format.

    ~~~payload
    name,value
    alpha,"x,y"
    ~~~

    ## n-folder

    kind: native
    format: folder
    group: folder-group
    title: Folder

    why: Preserve the authored content in its native format.

    ~~~payload
    ROOT\tIndex
    0\tCARD\t@n-root\t0\tRoot
    0\tCARD\t@n-art\t0\tArt
    ~~~

    ## n-art

    kind: native
    format: text-art
    group: art-group
    title: Art

    why: Preserve the authored content in its native format.

    ~~~payload
    A界
    x́
    ~~~

    # Groups

    - `note-group`: note
    - `code-group`: code
    - `todo-group`: todo
    - `table-group`: table
    - `folder-group`: folder
    - `art-group`: art

    # Connections

    ```tsv
    from	to
    n-root	n-note
    n-note	n-code
    n-code	n-todo
    n-todo	n-table
    n-table	n-folder
    n-folder	n-art
    ```
    """
)


FORMAT_FIRST_PLAN = textwrap.dedent(
    """\
    # Design

    Read left to right from one preserved code sample into a causal diagnosis.

    # Units

    ## u-code

    kind: native
    format: code
    group: implementation
    title: Validation entry
    why: Exact source syntax is more important than a diagram.

    ~~~payload
    int validate(Input value) { return value.ok; }
    ~~~

    ## u-causes

    kind: renderer
    renderer: fishbone
    group: diagnosis
    title: Delivery delay causes
    why: Several cause families converge on one observable effect.
    theme: unicode-light
    max-width: 80
    max-height: 100
    single-card: false

    ~~~input
    {
      "effect": "交付 Delay",
      "layout": "classic",
      "branches": [
        {"name": "人員 People", "side": "top", "nodes": ["訓練不足", "staff onboarding"]},
        {"name": "流程 Process", "side": "auto", "causes": ["review queue", "需求反覆"]},
        {"name": "工具 Tools", "side": "bottom", "nodes": ["env drift", "版本老舊"]},
        {"name": "管理 Ops", "nodes": ["priority unclear", "溝通延遲"]}
      ]
    }
    ~~~

    # Groups

    - `implementation`: exact source
    - `diagnosis`: causal analysis

    # Connections

    ```tsv
    from\tto
    u-code\tu-causes
    ```
    """
)


class MindMapToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temporary.name) / "sample.mindmap"
        self.run_dir.mkdir()
        (self.run_dir / "plan.md").write_text(
            PLAN,
            encoding="utf-8",
            newline="\n",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def prepare(self) -> list[dict[str, str]]:
        result = self.run_cli(
            "prepare",
            "--run-dir",
            str(self.run_dir),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        with (self.run_dir / "cards.tsv").open(
            encoding="utf-8",
            newline="",
        ) as stream:
            return list(csv.DictReader(stream, delimiter="\t"))

    def write_layout(self, rows: list[dict[str, str]]) -> None:
        lines = ["id\tx\ty"]
        for row in rows:
            index = int(row["index"])
            lines.append(f"{row['id']}\t{index * 220}\t0")
        (self.run_dir / "layout.tsv").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def test_native_todo_payload_omits_terminal_newline(self) -> None:
        unit = MINDMAP_TOOLS.PlannedUnit(
            logical_id="u-todo",
            kind="native",
            native_format="todo",
            renderer=None,
            group="checklist",
            title="Checklist",
            why="Keep completion state editable.",
            content="- [ ] first\n- [x] second",
        )

        prepared = MINDMAP_TOOLS.prepare_unit(unit, self.run_dir)

        self.assertEqual(
            prepared.cards[0].payload_text,
            "- [ ] first\n- [x] second",
        )

    def test_native_csv_payload_matches_canonical_export(self) -> None:
        for content, expected in (
            ('name,value\n"中文","x,y"\nquote,"a""b"', 'name,value\n中文,"x,y"\nquote,"a""b"'),
            ('"a\r\nb",c\n"",\n""', '"a\r\nb",c\n,\n,'),
            ('a\n""', 'a\n""'),
        ):
            with self.subTest(content=content):
                unit = MINDMAP_TOOLS.PlannedUnit(
                    logical_id="u-csv", kind="native", native_format="csv", renderer=None,
                    group="-", title="CSV", why="Preserve cells.", content=content,
                )
                prepared = MINDMAP_TOOLS.prepare_unit(unit, self.run_dir)
                self.assertEqual(prepared.cards[0].payload_text, expected)

    def test_prepare_rejects_invalid_native_payloads_before_writing(self) -> None:
        for old, new, diagnostic in (
            ("ROOT\tIndex", "Index", "folder payload must begin with ROOT"),
            ("- [ ] first", "- first", "todo lines must begin"),
        ):
            with self.subTest(diagnostic=diagnostic):
                (self.run_dir / "plan.md").write_text(PLAN.replace(old, new), encoding="utf-8")
                result = self.run_cli("prepare", "--run-dir", str(self.run_dir))
                self.assertEqual(result.returncode, 2)
                self.assertIn(diagnostic, result.stderr)
                self.assertFalse((self.run_dir / "cards.tsv").exists())
                self.assertFalse((self.run_dir / "payloads").exists())

    def geometry_arguments(self, **overrides: object) -> SimpleNamespace:
        values: dict[str, object] = {
            "horizontal_gap": 6,
            "vertical_gap": 4,
            "group_area_ratio": 7.0,
            "max_board_width": 0,
            "max_board_height": 0,
            "corridor_margin": 1,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def geometry_card(
        self,
        logical_id: str,
        title: str,
        *,
        group: str = "-",
    ) -> object:
        return MINDMAP_TOOLS.CardRow(
            logical_id,
            0,
            "note",
            10,
            5,
            group,
            title,
            f"payloads/{logical_id}.txt",
        )

    def test_clearance_error_explains_measurement_and_rule(self) -> None:
        cards = [
            self.geometry_card("u-one", "One"),
            self.geometry_card("u-two", "Two"),
        ]
        errors, warnings, _ = MINDMAP_TOOLS.validate_geometry(
            cards,
            {"u-one": (0, 0), "u-two": (12, 0)},
            [],
            self.geometry_arguments(),
        )
        self.assertFalse(warnings)
        self.assertEqual(len(errors), 1)
        self.assertIn("horizontal gap of 2 cells; the minimum is 6", errors[0])
        self.assertIn("horizontal clearance rule", errors[0])

    def test_group_spread_warning_explains_reference(self) -> None:
        cards = [
            self.geometry_card("u-one", "One", group="topic"),
            self.geometry_card("u-two", "Two", group="topic"),
        ]
        errors, warnings, _ = MINDMAP_TOOLS.validate_geometry(
            cards,
            {"u-one": (0, 0), "u-two": (100, 0)},
            [],
            self.geometry_arguments(group_area_ratio=2.0),
        )
        self.assertFalse(errors)
        self.assertEqual(len(warnings), 1)
        self.assertIn('Group "topic" spans', warnings[0])
        self.assertIn("reference ratio is 2", warnings[0])
        self.assertIn("harder to recognize as one visual group", warnings[0])

    def test_corridor_warning_explains_visual_risk(self) -> None:
        cards = [
            self.geometry_card("u-one", "One"),
            self.geometry_card("u-two", "Two"),
            self.geometry_card("u-blocker", "Blocker"),
        ]
        errors, warnings, _ = MINDMAP_TOOLS.validate_geometry(
            cards,
            {"u-one": (0, 0), "u-two": (100, 0), "u-blocker": (45, 0)},
            [("u-one", "u-two")],
            self.geometry_arguments(),
        )
        self.assertFalse(errors)
        self.assertEqual(len(warnings), 1)
        self.assertIn('passes through "Blocker" (u-blocker)', warnings[0])
        self.assertIn("harder to follow visually", warnings[0])

    def test_prepare_writes_all_formats_and_exact_text_art_extent(self) -> None:
        rows = self.prepare()
        self.assertEqual(len(rows), 7)
        self.assertEqual(
            [int(row["index"]) for row in rows],
            list(range(7)),
        )
        art = next(row for row in rows if row["id"] == "n-art")
        self.assertEqual((art["format"], art["width"], art["height"]), ("text-art", "3", "2"))
        self.assertEqual(
            (self.run_dir / art["payload"]).read_text(encoding="utf-8"),
            "A界\nx́\n",
        )
        with (self.run_dir / "edges.tsv").open(
            encoding="utf-8",
            newline="",
        ) as stream:
            edges = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(len(edges), 6)

    def test_prepare_rejects_unresolved_folder_reference(self) -> None:
        plan = (self.run_dir / "plan.md").read_text(encoding="utf-8")
        (self.run_dir / "plan.md").write_text(
            plan.replace("@n-art", "@n-missing"),
            encoding="utf-8",
            newline="\n",
        )
        result = self.run_cli(
            "prepare",
            "--run-dir",
            str(self.run_dir),
            "--check-only",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unresolved target", result.stderr)

    def test_validate_layout_and_build_multiple_batches(self) -> None:
        rows = self.prepare()
        self.write_layout(rows)
        validation = self.run_cli(
            "validate-layout",
            "--run-dir",
            str(self.run_dir),
            "--max-board-width",
            "0",
            "--max-board-height",
            "0",
        )
        self.assertEqual(validation.returncode, 0, validation.stdout)
        self.assertIn("The card layout is valid.", validation.stdout)
        self.assertIn("Result: 0 errors and 0 warnings.", validation.stdout)

        result = self.run_cli(
            "build-batch",
            "--run-dir",
            str(self.run_dir),
            "--output",
            "work/draft.cards",
            "--output",
            "work/create.cards",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        draft = (self.run_dir / "work" / "draft.cards").read_text(
            encoding="utf-8"
        )
        final = (self.run_dir / "work" / "create.cards").read_text(
            encoding="utf-8"
        )
        self.assertEqual(draft, final)
        self.assertEqual(len(draft.splitlines()), 7)
        self.assertTrue(draft.startswith("markdown 0 0 "))

    def test_validate_layout_reports_overlap(self) -> None:
        rows = self.prepare()
        self.write_layout(rows)
        layout = (self.run_dir / "layout.tsv").read_text(encoding="utf-8")
        layout = layout.replace("n-note\t220\t0", "n-note\t0\t0")
        (self.run_dir / "layout.tsv").write_text(
            layout,
            encoding="utf-8",
            newline="\n",
        )
        result = self.run_cli(
            "validate-layout",
            "--run-dir",
            str(self.run_dir),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn('"Root" (n-root) and "Note" (n-note) overlap', result.stdout)
        self.assertIn("Both items occupy the same board area.", result.stdout)
        self.assertIn("Result: 1 error", result.stdout)

    def test_validate_layout_warning_explains_reason_without_failing(self) -> None:
        rows = self.prepare()
        self.write_layout(rows)
        result = self.run_cli(
            "validate-layout",
            "--run-dir",
            str(self.run_dir),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("The card layout is valid with 1 warning.", result.stdout)
        self.assertIn("The layout spans", result.stdout)
        self.assertIn("A larger board may be harder to view in one preview.", result.stdout)
        self.assertIn("Result: 0 errors and 1 warning.", result.stdout)

    def test_validate_layout_rejects_missing_card(self) -> None:
        rows = self.prepare()
        self.write_layout(rows[:-1])
        result = self.run_cli(
            "validate-layout",
            "--run-dir",
            str(self.run_dir),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("layout ID mismatch", result.stderr)

    def use_format_first_plan(self) -> None:
        (self.run_dir / "plan.md").write_text(
            FORMAT_FIRST_PLAN,
            encoding="utf-8",
            newline="\n",
        )

    def test_format_first_plan_compiles_renderer_group(self) -> None:
        self.use_format_first_plan()
        rows = self.prepare()
        self.assertEqual(len(rows), 3)
        rendered = [row for row in rows if row["id"].startswith("u-causes--")]
        self.assertEqual(len(rendered), 2)
        self.assertTrue(all(row["format"] == "text-art" for row in rendered))

        with (self.run_dir / "units.tsv").open(
            encoding="utf-8", newline=""
        ) as stream:
            units = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual([row["id"] for row in units], ["u-code", "u-causes"])
        fishbone = units[1]
        self.assertEqual((fishbone["kind"], fishbone["renderer"]), ("renderer", "fishbone"))
        self.assertEqual(fishbone["anchor"], rendered[0]["id"])

        manifest_path = (
            self.run_dir / "work" / "rendered" / "u-causes" / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["renderer"], "fishbone-note")
        self.assertEqual(len(manifest["cards"]), 2)
        self.assertTrue((self.run_dir / "renderer-inputs" / "u-causes.json").is_file())

        with (self.run_dir / "edges.tsv").open(
            encoding="utf-8", newline=""
        ) as stream:
            edges = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(
            edges,
            [{"from": "u-code", "to": fishbone["anchor"]}],
        )

    def test_unit_layout_expands_renderer_offsets_without_relayout(self) -> None:
        self.use_format_first_plan()
        rows = self.prepare()
        (self.run_dir / "unit-layout.tsv").write_text(
            "id\tx\ty\nu-code\t0\t0\nu-causes\t250\t20\n",
            encoding="utf-8",
            newline="\n",
        )
        validated = self.run_cli(
            "validate-units",
            "--run-dir",
            str(self.run_dir),
            "--max-board-width",
            "0",
            "--max-board-height",
            "0",
        )
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
        expanded = self.run_cli(
            "expand-layout",
            "--run-dir",
            str(self.run_dir),
            "--max-board-width",
            "0",
            "--max-board-height",
            "0",
        )
        self.assertEqual(expanded.returncode, 0, expanded.stdout + expanded.stderr)

        with (self.run_dir / "unit-members.tsv").open(
            encoding="utf-8", newline=""
        ) as stream:
            members = list(csv.DictReader(stream, delimiter="\t"))
        with (self.run_dir / "layout.tsv").open(
            encoding="utf-8", newline=""
        ) as stream:
            positions = {
                row["id"]: (int(row["x"]), int(row["y"]))
                for row in csv.DictReader(stream, delimiter="\t")
            }
        for member in members:
            origin = (0, 0) if member["unit"] == "u-code" else (250, 20)
            self.assertEqual(
                positions[member["card"]],
                (origin[0] + int(member["dx"]), origin[1] + int(member["dy"])),
            )
        final_validation = self.run_cli(
            "validate-layout",
            "--run-dir",
            str(self.run_dir),
            "--max-board-width",
            "0",
            "--max-board-height",
            "0",
        )
        self.assertEqual(
            final_validation.returncode,
            0,
            final_validation.stdout + final_validation.stderr,
        )
        self.assertEqual(len(rows), len(positions))

    def test_expand_layout_warning_writes_output(self) -> None:
        self.use_format_first_plan()
        self.prepare()
        (self.run_dir / "unit-layout.tsv").write_text(
            "id\tx\ty\nu-code\t0\t0\nu-causes\t700\t20\n",
            encoding="utf-8",
            newline="\n",
        )
        result = self.run_cli(
            "expand-layout",
            "--run-dir",
            str(self.run_dir),
            "--output",
            "work/warning-layout.tsv",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Warnings:", result.stdout)
        self.assertIn("A larger board may be harder to view in one preview.", result.stdout)
        self.assertIn("Wrote the expanded card layout", result.stdout)
        self.assertTrue((self.run_dir / "work" / "warning-layout.tsv").is_file())

    def test_expand_layout_error_leaves_existing_output_unchanged(self) -> None:
        self.use_format_first_plan()
        self.prepare()
        (self.run_dir / "unit-layout.tsv").write_text(
            "id\tx\ty\nu-code\t0\t0\nu-causes\t0\t0\n",
            encoding="utf-8",
            newline="\n",
        )
        output = self.run_dir / "work" / "existing-layout.tsv"
        output.parent.mkdir(exist_ok=True)
        output.write_text("existing\n", encoding="utf-8", newline="\n")
        result = self.run_cli(
            "expand-layout",
            "--run-dir",
            str(self.run_dir),
            "--output",
            "work/existing-layout.tsv",
            "--max-board-width",
            "0",
            "--max-board-height",
            "0",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Both items occupy the same board area.", result.stdout)
        self.assertIn("any existing output was left unchanged", result.stdout)
        self.assertEqual(output.read_text(encoding="utf-8"), "existing\n")

    def test_format_first_plan_requires_choice_reason(self) -> None:
        self.use_format_first_plan()
        plan = (self.run_dir / "plan.md").read_text(encoding="utf-8")
        (self.run_dir / "plan.md").write_text(
            plan.replace(
                "why: Exact source syntax is more important than a diagram.\n",
                "",
            ),
            encoding="utf-8",
            newline="\n",
        )
        result = self.run_cli(
            "prepare",
            "--run-dir",
            str(self.run_dir),
            "--check-only",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing metadata", result.stderr)

    def test_renderer_check_only_leaves_no_derived_artifacts(self) -> None:
        self.use_format_first_plan()
        result = self.run_cli(
            "prepare",
            "--run-dir",
            str(self.run_dir),
            "--check-only",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in (
            "cards.tsv",
            "units.tsv",
            "unit-members.tsv",
            "unit-edges.tsv",
            "edges.tsv",
            "renderer-inputs",
        ):
            self.assertFalse((self.run_dir / name).exists(), name)

if __name__ == "__main__":
    unittest.main()
