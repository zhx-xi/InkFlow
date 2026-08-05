"""CI 覆盖率门禁检查（#104 Phase 1）：解析 coverage.xml，断言行/分支双阈值。

用法: python ci_cd/check_coverage.py <line_min> <branch_min> [coverage.xml]

- line_min/branch_min 为百分比阈值（如 92 87）
- 从 coverage.xml（coverage.py `coverage xml` 产物）读 line-rate/branch-rate
- 任一低于阈值即 exit 1（CI 门禁红）
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "usage: check_coverage.py <line_min> <branch_min> [coverage.xml]",
            file=sys.stderr,
        )
        return 2
    line_min = float(sys.argv[1])
    branch_min = float(sys.argv[2])
    xml_path = sys.argv[3] if len(sys.argv) > 3 else "coverage.xml"

    root = ET.parse(xml_path).getroot()
    line_rate = float(root.get("line-rate", "0")) * 100
    branch_rate = float(root.get("branch-rate", "0")) * 100

    print(
        f"coverage.xml: line={line_rate:.2f}% (min {line_min}%), "
        f"branch={branch_rate:.2f}% (min {branch_min}%)"
    )
    ok = True
    if line_rate < line_min:
        print(f"FAIL: line coverage {line_rate:.2f}% < {line_min}%", file=sys.stderr)
        ok = False
    if branch_rate < branch_min:
        print(
            f"FAIL: branch coverage {branch_rate:.2f}% < {branch_min}%", file=sys.stderr
        )
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
