"""按 B1 口径重置 func_coverage_baseline.json（#1206）。

用法: python ci_cd/regen_func_cov_baseline.py <called.json> <exempt.json> <baseline.json> <out.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_func_coverage import (
    discover_functions,
    load_called,
    load_exemption,
    split_exemption,
)


def main() -> int:
    if len(sys.argv) != 6:
        print(__doc__, file=sys.stderr)
        return 2
    called_json, exempt_json, baseline_json, out_json = sys.argv[2:]
    old = json.loads(Path(baseline_json).read_text(encoding="utf-8"))
    src_root = sys.argv[1]

    all_fns = discover_functions(src_root)
    called = load_called(called_json)
    valid, _exempted = split_exemption(all_fns, load_exemption(exempt_json))
    uncalled = valid - called
    pct = round(len(valid & called) / len(valid) * 100, 2)

    Path(out_json).write_text(
        json.dumps(
            {"baseline_pct": pct, "baseline_uncalled": sorted(uncalled)},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    old_set = set(old.get("baseline_uncalled", []))
    print(f"old: pct={old.get('baseline_pct')} uncalled={len(old_set)}")
    print(f"new: pct={pct} uncalled={len(uncalled)} -> {out_json}")
    print("newly-uncalled (settrace 误判为已调用，需人工核实):")
    for key in sorted(uncalled - old_set):
        print(f"  {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
