#!/usr/bin/env python3
"""Frontend coverage gate: assert renderer/electron coverage meets thresholds.

Mirrors backend ci_cd/check_coverage.py but reads Vitest json-summary reports
(coverage-summary.json, emitted by `vitest run --coverage` with reporter
'json-summary'). The `coverage-frontend` GitHub Actions job downloads the
renderer + electron coverage artifacts, then runs this script.

Thresholds ARE ALIGNED with unit-frontend's vitest.config.ts thresholds
(renderer: 92/85/80/92, electron: 88/90/80/88). When raising thresholds later,
BOTH this file and the vitest.config.ts must be bumped together (see issue
tracking the coverage-frontend gate).

Usage:
    python3 ci_cd/check_frontend_coverage.py <renderer_summary.json> <electron_summary.json>
Exit code 0 = all packages meet thresholds; 1 = any metric below threshold.
"""

from __future__ import annotations

import json
import sys

# Aligned with unit-frontend vitest.config.ts (coverage.thresholds).
PACKAGE_THRESHOLDS: dict[str, dict[str, float]] = {
    "renderer": {"lines": 92, "branches": 85, "functions": 80, "statements": 92},
    "electron": {"lines": 88, "branches": 90, "functions": 80, "statements": 88},
}

METRICS = ["lines", "branches", "functions", "statements"]


def _check_package(package: str, summary_path: str) -> list[str]:
    """Return a list of 'metric: pct < min' failure strings (empty = pass)."""
    with open(summary_path, encoding="utf-8") as fh:
        data = json.load(fh)
    total = data["total"]
    thresholds = PACKAGE_THRESHOLDS[package]
    fails: list[str] = []
    for metric in METRICS:
        pct = float(total[metric]["pct"])
        minimum = thresholds[metric]
        status = "OK" if pct >= minimum else "FAIL"
        print(f"  {package:<10} {metric:<10} {pct:6.2f}%  (min {minimum})  [{status}]")
        if status == "FAIL":
            fails.append(f"{package}.{metric}={pct:.2f}% < {minimum}%")
    return fails


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: python3 check_frontend_coverage.py "
            "<renderer_summary.json> <electron_summary.json>"
        )
        return 2

    renderer_path, electron_path = sys.argv[1], sys.argv[2]
    all_fails: list[str] = []

    print("--- renderer coverage gate ---")
    all_fails += _check_package("renderer", renderer_path)
    print("--- electron coverage gate ---")
    all_fails += _check_package("electron", electron_path)

    if all_fails:
        print("\nFAIL: coverage below threshold for:")
        for f in all_fails:
            print(f"  {f}")
        return 1

    print("\nPASS: all frontend coverage metrics meet thresholds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
