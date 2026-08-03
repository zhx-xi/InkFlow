"""CI 护栏：检查源码文件行数（monster file 禁令，借鉴 LiteLLM ci_cd/check_file_length.py）。

用法: python ci_cd/check_file_length.py <max_lines> <path...>
退出码 0 = 全部通过；1 = 存在超限文件（列出 TOP）。

存量豁免：ALLOWLIST 中文件不检查（历史遗留超限，拆分后从清单移除——护栏针对新增）。
"""

import sys
from pathlib import Path

# 存量超限文件（2026-08-03 基线）：拆分/瘦身后移除
ALLOWLIST = {
    "tests/unit/test_extraction_service.py",  # 1372 行（F14 横切门面测试）
    "tests/unit/test_audit_service.py",  # 1135 行（F15 审计规则测试）
    "tests/cli/test_cli_outline.py",  # 1021 行（F11 CLI 测试）
    "src/inkflow/domain/services/extraction_service.py",  # 920 行（F14 门面，计划拆分）
}


def check_file_length(max_lines: int, paths: list[str]) -> list[tuple[str, int]]:
    bad: list[tuple[str, int]] = []
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
