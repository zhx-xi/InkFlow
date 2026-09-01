"""合并多个 function-coverage called-set JSON（并集）。

用法: python ci_cd/merge_func_cov_calls.py <in1.json> [<in2.json> ...] <out.json>
每个输入文件为 func_cov_plugin.py 产出的 {"callable": [keys...]}（或裸数组）。
输出 <out.json> 为所有输入的并集。

独立 function-coverage job 将 4 个测试轨（unit/api/cli/integration）各自收集的 called-set
合并后再交 ci_cd/check_func_coverage.py 门禁——双 tests/ 目录不能同一进程运行（同 #685 分轨）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def merge_called(inputs: list[str]) -> set[str]:
    """读取多个 called-set JSON 文件，返回并集。"""
    union: set[str] = set()
    for raw in inputs:
        data = json.loads(Path(raw).read_text(encoding="utf-8"))
        keys = data.get("callable", data) if isinstance(data, dict) else data
        union |= {str(k) for k in keys}
    return union


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    out_path = sys.argv[-1]
    inputs = sys.argv[1:-1]
    union = merge_called(inputs)
    Path(out_path).write_text(
        json.dumps({"callable": sorted(union)}), encoding="utf-8"
    )
    print(
        f"[merge_func_cov] {len(union)} unique called functions from "
        f"{len(inputs)} file(s) -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
