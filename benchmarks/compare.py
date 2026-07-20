#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EXACT_FIELDS = (
    "iterations",
    "input_objects",
    "input_bytes",
    "output_bytes",
    "observed",
    "output_checksum",
)


def load(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != 1:
        raise ValueError(f"{path}: unsupported baseline schema")
    return document


def compare_documents(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    failures: list[str] = []

    if baseline.get("environment") != current.get("environment"):
        failures.append("benchmark environment differs")

    baseline_scenarios = baseline.get("scenarios", {})
    current_scenarios = current.get("scenarios", {})
    missing_scenarios = sorted(baseline_scenarios.keys() - current_scenarios.keys())
    new_scenarios = sorted(current_scenarios.keys() - baseline_scenarios.keys())
    failures.extend(f"missing scenario: {name}" for name in missing_scenarios)
    failures.extend(f"new scenario: {name}" for name in new_scenarios)

    for scenario in sorted(baseline_scenarios.keys() & current_scenarios.keys()):
        baseline_scenario = baseline_scenarios[scenario]
        current_scenario = current_scenarios[scenario]

        for field in ("board_file_bytes", "checksum"):
            if baseline_scenario.get(field) != current_scenario.get(field):
                failures.append(f"{scenario}: {field} differs")

        baseline_metrics = baseline_scenario.get("metrics", {})
        current_metrics = current_scenario.get("metrics", {})
        missing_metrics = sorted(baseline_metrics.keys() - current_metrics.keys())
        new_metrics = sorted(current_metrics.keys() - baseline_metrics.keys())
        failures.extend(
            f"{scenario}: missing metric: {name}" for name in missing_metrics
        )
        failures.extend(f"{scenario}: new metric: {name}" for name in new_metrics)

        for name in sorted(baseline_metrics.keys() & current_metrics.keys()):
            before = baseline_metrics[name]
            after = current_metrics[name]
            label = f"{scenario}/{name}"

            for field in EXACT_FIELDS:
                if before.get(field) != after.get(field):
                    failures.append(f"{label}: {field} differs")

            baseline_time = float(before["total_ms_median"])
            current_time = float(after["total_ms_median"])
            if before.get("timing_gate", False):
                if baseline_time == 0.0:
                    if current_time != 0.0:
                        failures.append(f"{label}: timing changed from zero")
                elif current_time > baseline_time * 1.15:
                    failures.append(
                        f"{label}: time regressed "
                        f"{(current_time / baseline_time - 1.0) * 100:.1f}%"
                    )

            if baseline.get("environment", {}).get("mode") == "full":
                baseline_rss = float(before["peak_rss_mib_median"])
                current_rss = float(after["peak_rss_mib_median"])
                if baseline_rss == 0.0:
                    if current_rss != 0.0:
                        failures.append(f"{label}: RSS changed from zero")
                elif current_rss > baseline_rss * 1.10:
                    failures.append(
                        f"{label}: RSS regressed "
                        f"{(current_rss / baseline_rss - 1.0) * 100:.1f}%"
                    )

    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    arguments = parser.parse_args()
    failures = compare_documents(load(arguments.baseline), load(arguments.current))

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1

    print("PASS benchmark baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
