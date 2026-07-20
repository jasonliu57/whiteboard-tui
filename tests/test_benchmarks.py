from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.compare import compare_documents
from benchmarks.run import aggregate, parse_output

CSV_OUTPUT = """benchmark_schema,2
mode,quick
compiler,test
compiler_version,1
build_type,Release
os,test
architecture,test
board_file_bytes,123
checksum,456
name,iterations,input_objects,input_bytes,output_bytes,observed,output_checksum,total_ms,ns_per_item,mib_per_second,peak_rss_mib
operation,2,3,4,5,6,7,8.0,9.0,10.0,11.0
"""


class BenchmarkToolTests(unittest.TestCase):
    def test_output_parser_and_aggregation(self) -> None:
        parsed = parse_output(CSV_OUTPUT)
        scenario = aggregate("board", [parsed, parsed])

        self.assertEqual((scenario["board_file_bytes"], scenario["checksum"]), (123, 456))
        metric = scenario["metrics"]["operation"]
        self.assertEqual(metric["output_checksum"], 7)
        self.assertEqual(metric["total_ms_median"], 8.0)
        self.assertFalse(metric["timing_gate"])

    def test_comparator_reports_exact_output_change(self) -> None:
        parsed = parse_output(CSV_OUTPUT)
        scenario = aggregate("board", [parsed])
        baseline = {
            "schema": 1,
            "environment": {"mode": "quick"},
            "scenarios": {"board": scenario},
        }
        current = json.loads(json.dumps(baseline))
        current["scenarios"]["board"]["metrics"]["operation"]["output_checksum"] += 1

        self.assertEqual(
            compare_documents(baseline, current),
            ["board/operation: output_checksum differs"],
        )

    def test_runner_executes_only_the_requested_scenario(self) -> None:
        with tempfile.TemporaryDirectory(prefix="whiteboard-benchmark-tool-") as name:
            root = Path(name)
            fake = root / "fake-benchmark"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "expected = ['--quick', '--scenario', 'board']\n"
                "if sys.argv[1:] != expected:\n"
                "    raise SystemExit(2)\n"
                f"print({CSV_OUTPUT!r})\n",
                encoding="utf-8",
            )
            os.chmod(fake, 0o700)
            output = root / "result.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "benchmarks" / "run.py"),
                    str(fake),
                    "--quick",
                    "--runs",
                    "1",
                    "--scenario",
                    "board",
                    "--reason",
                    "test",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(tuple(document["scenarios"]), ("board",))


if __name__ == "__main__":
    unittest.main()
