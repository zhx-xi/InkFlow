"""CI 护栏：noqa 抑制必须带理由（借鉴 LiteLLM 类型纪律：抑制命名规则 + 理由注释）。

规则：
- `# noqa: X` 后面必须跟 `# <reason>` 注释
- `# type: ignore[...]` / `# mypy: ignore[...]` 同理（由 mypy warn_unused_ignores 互补检查）

用法: python ci_cd/check_noqa_reason.py <path...>
退出码 0 = 全部通过；1 = 存在无理由抑制。
"""

import re
import sys
from pathlib import Path

NOQA_RE = re.compile(r"#\s*noqa(?::\s*[A-Za-z0-9, ]+)?")
IGNORE_RE = re.compile(r"#\s*(?:type|mypy):\s*ignore(?:\[[^\]]*\])?")
# 理由必须非空（尾部 \S 拒绝 `# ` 空理由）；格式示例见模块 docstring
REASON_RE = re.compile(
    r"#\s*(?:(?:noqa(?::\s*[A-Za-z0-9, ]+)?)|(?:type|mypy):\s*ignore(?:\[[^\]]*\])?).*?#\s*\S"
)


def check(paths: list[str]) -> list[tuple[str, int, str]]:
    bad: list[tuple[str, int, str]] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files = sorted(p.rglob("*.py"))
        elif p.is_file():
            files = [p]
        else:
            continue
        for f in files:
            if "__pycache__" in f.parts:
                continue
            for lineno, line in enumerate(
                f.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if (
                    NOQA_RE.search(line) or IGNORE_RE.search(line)
                ) and not REASON_RE.search(line):
                    bad.append((str(f), lineno, line.strip()))
    return bad


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    bad = check(sys.argv[1:])
    if bad:
        print(f"[check_noqa_reason] {len(bad)} suppression(s) without reason:")
        for filename, lineno, line in bad:
            print(f"  {filename}:{lineno}: {line}")
        print("  修复: 追加理由注释, 如 `# noqa: X  # <reason>`")
        return 1
    print("[check_noqa_reason] OK: all suppressions carry a reason")
    return 0


if __name__ == "__main__":
    sys.exit(main())
