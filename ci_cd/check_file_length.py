"""CI 护栏：检查源码文件行数（monster file 禁令，借鉴 LiteLLM ci_cd/check_file_length.py）。

用法: python ci_cd/check_file_length.py <max_lines> <path...>
退出码 0 = 全部通过；1 = 存在超限文件（列出 TOP）。

覆盖范围：.py / .ts / .tsx（#281 前端护栏扩展，2026-08-13）。
自动排除 node_modules / dist / .venv / __pycache__ 等构建与依赖目录。

存量豁免（ALLOWLIST）：已清零（#307 拆分功能文件后归零）。
⚠️ 规则固化（#281 T4）：不再新增 ALLOWLIST 豁免——超限文件优先拆分，
而非贴线增长后申请豁免。
"""

import sys
from pathlib import Path

# 存量超限功能文件（#307 已清零：extraction_service.py 拆分至 ≤900 行，ALLOWLIST 归零）
ALLOWLIST: set[str] = set()

# 检查的扩展名（#281 起含前端 .ts/.tsx）
EXTENSIONS = (".py", ".ts", ".tsx")

# 跳过目录（构建产物 / 依赖，不参与行数护栏）
_SKIP_DIRS = {"node_modules", "dist", ".venv", "__pycache__"}


def check_file_length(max_lines: int, paths: list[str]) -> list[tuple[str, int]]:
    bad: list[tuple[str, int]] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files = sorted(f for f in p.rglob("*") if f.suffix in EXTENSIONS)
        elif p.is_file():
            files = [p]
        else:
            continue
        for f in files:
            if _SKIP_DIRS.intersection(f.parts):
                continue
            rel = str(f).replace("\\", "/")
            # 归一化: 移除 ../ 前缀和 backend/ 前缀，匹配 ALLOWLIST
            key = rel.lstrip("./")
            if key.startswith("../"):
                key = key[3:]
            if key.startswith("backend/"):
                key = key[len("backend/") :]
            if key in ALLOWLIST:
                continue
            try:
                lines = len(f.read_text(encoding="utf-8").splitlines())
            except (UnicodeDecodeError, OSError):
                continue
            if lines > max_lines:
                bad.append((str(f), lines))
    return bad


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    max_lines = int(sys.argv[1])
    bad = check_file_length(max_lines, sys.argv[2:])
    if bad:
        bad.sort(key=lambda x: x[1], reverse=True)
        print(f"[check_file_length] {len(bad)} file(s) exceed {max_lines} lines:")
        for filename, length in bad:
            print(f"  {filename}: {length} lines")
        return 1
    print(f"[check_file_length] OK: all files <= {max_lines} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
