#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import statistics
import subprocess
from typing import Any


def load_scenarios() -> tuple[str, ...]:
    definition = Path(__file__).with_name("stress_scenarios.def")
    pattern = re.compile(r'^WHITEBOARD_STRESS_SCENARIO\("([^"]+)", [^)]+\)$')
    scenarios: list[str] = []
    for line in definition.read_text(encoding="utf-8").splitlines():
        match = pattern.fullmatch(line)
        if match is None:
            raise RuntimeError(f"invalid stress scenario entry: {line!r}")
        scenarios.append(match.group(1))
    if not scenarios or len(scenarios) != len(set(scenarios)):
        raise RuntimeError("invalid stress scenario registry")
    return tuple(scenarios)


SCENARIOS = load_scenarios()
EXACT_FIELDS = (
    "iterations",
    "input_objects",
    "input_bytes",
    "output_bytes",
    "observed",
    "output_checksum",
)
FLOAT_FIELDS = (
    "total_ms",
    "ns_per_item",
    "mib_per_second",
    "peak_rss_mib",
)
ENVIRONMENT_FIELDS = (
    "mode",
    "compiler",
    "compiler_version",
    "build_type",
    "os",
    "architecture",
)


def parse_output(output: str) -> dict[str, Any]:
    lines = output.splitlines()
    header = next(
        (index for index, line in enumerate(lines) if line.startswith("name,")),
        None,
    )

    if header is None:
        raise ValueError("benchmark output has no metric header")

    metadata: dict[str, str] = {}
    for line in lines[:header]:
        key, separator, value = line.partition(",")
        if not separator or not key:
            raise ValueError(f"invalid benchmark metadata: {line!r}")
        metadata[key] = value

    if metadata.get("benchmark_schema") != "2":
        raise ValueError("unsupported benchmark schema")

    rows: dict[str, dict[str, int | float]] = {}
    for row in csv.DictReader(lines[header:]):
        name = row.pop("name", None)
        if not name or name in rows or None in row:
            raise ValueError("invalid or duplicate benchmark metric")
        parsed: dict[str, int | float] = {}
        for field in EXACT_FIELDS:
            parsed[field] = int(row[field])
        for field in FLOAT_FIELDS:
            parsed[field] = float(row[field])
        rows[name] = parsed

    if not rows:
        raise ValueError("benchmark output has no metrics")

    return {"metadata": metadata, "metrics": rows}


def aggregate(
    scenario: str,
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    first = runs[0]
    names = set(first["metrics"])

    for run in runs[1:]:
        if run["metadata"] != first["metadata"]:
            raise ValueError(f"{scenario}: metadata changed between runs")
        if set(run["metrics"]) != names:
            raise ValueError(f"{scenario}: metric set changed between runs")

    metrics: dict[str, dict[str, int | float]] = {}
    for name in sorted(names):
        rows = [run["metrics"][name] for run in runs]
        metric: dict[str, int | float] = {}

        for field in EXACT_FIELDS:
            values = {row[field] for row in rows}
            if len(values) != 1:
                raise ValueError(f"{scenario}/{name}: {field} is not repeatable")
            metric[field] = values.pop()

        for field in FLOAT_FIELDS:
            metric[f"{field}_median"] = statistics.median(
                float(row[field]) for row in rows
            )

        metric["timing_gate"] = (
            first["metadata"]["mode"] == "full"
            and (scenario != "board" or metric["total_ms_median"] >= 5.0)
        )

        metrics[name] = metric

    metadata = first["metadata"]
    return {
        "board_file_bytes": int(metadata["board_file_bytes"]),
        "checksum": int(metadata["checksum"]),
        "metrics": metrics,
        "raw": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--scenario", action="append", choices=SCENARIOS)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--quick", action="store_true")
    arguments = parser.parse_args()

    if arguments.runs < 1:
        parser.error("--runs must be positive")

    executable = arguments.executable.resolve()
    scenarios = tuple(arguments.scenario or SCENARIOS)
    scenario_results: dict[str, Any] = {}
    environment: dict[str, str] | None = None

    for scenario in scenarios:
        runs: list[dict[str, Any]] = []
        for run in range(arguments.runs):
            command = [str(executable), "--scenario", scenario]
            if arguments.quick:
                command.insert(1, "--quick")
            completed = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode != 0:
                raise SystemExit(
                    f"{scenario} run {run + 1} failed:\n{completed.stderr}"
                )
            parsed = parse_output(completed.stdout)
            current_environment = {
                field: parsed["metadata"][field]
                for field in ENVIRONMENT_FIELDS
            }
            if environment is None:
                environment = current_environment
            elif current_environment != environment:
                raise SystemExit("benchmark environment changed between processes")
            runs.append(parsed)
        scenario_results[scenario] = aggregate(scenario, runs)

    document = {
        "schema": 1,
        "reason": arguments.reason,
        "runs": arguments.runs,
        "environment": environment,
        "scenarios": scenario_results,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
