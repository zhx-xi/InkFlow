"""CI 护栏：AGENTS.md 里的仓库内路径指针必须真实存在（#1190 批 C）。

背景：AGENTS.md 是 AI 唯一自动注入的项目上下文，其反引号引用的仓库内路径即「指针」；
指针失效 = 后续会话照指引去找必然扑空（批 A/B 实测：悬空 plan.md 尾注 15 处 /
手写行号漂移 62/62 / 测试路径失效 151 处）。本护栏做轻量防复发检查。

规则（提取 + 判定）：
- 提取：文档中全部反引号 token。
- 接受（仓库根相对路径，二选一）：白名单顶层目录前缀；或不含 `/` 且以 .md 结尾的根级文件。
- 排除（非仓库内指针）：含 `<` `>` `*` `|` 或 `NNN` 的占位符/通配；含 `://` 的 URL/DSN；
  以 `/` 开头的 HTTP 端点；含空格的命令行片段；以 `D:` `C:` `http` `git ` `python `
  `uv ` `gh ` `grep` `#` 开头的绝对路径/命令行。
- 判定：`Path(repo_root) / token` 存在（token 以 `/` 结尾时按目录判存在）。
- 同一 token 多次出现按首次出现行号去重（指针数口径 = 去重后数量；#1190 批 C 基线 31）。

用法: python ci_cd/check_doc_pointers.py <repo_root>
退出码 0 = 全部有效；1 = 存在失效指针；2 = 缺参数。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# 白名单顶层目录：只有这些目录开头的 token 才可能是「仓库根相对路径」
TOP_LEVEL_DIRS = (
    "adr/",
    "specs/",
    "backend/",
    "docs/",
    "design/",
    "ci_cd/",
    "tests/",
    "frontend/",
    ".specify/",
    ".githooks/",
    ".github/",
    "skills/",
)
# 行首形态排除：Windows 绝对路径 / URL / 命令行 / shell 注释
EXCLUDE_PREFIXES = ("D:", "C:", "http", "git ", "python ", "uv ", "gh ", "grep", "#")
PLACEHOLDER_CHARS = ("<", ">", "*", "|")
TOKEN_RE = re.compile(r"`([^`\n]+)`")


def _is_pointer(token: str) -> bool:
    """token 是否形如仓库根相对路径（占位符/URL/端点/命令行片段一律不算）。"""
    if any(ch in token for ch in PLACEHOLDER_CHARS) or "NNN" in token:
        return False
    if "://" in token or token.startswith("/") or " " in token:
        return False
    if token.startswith(EXCLUDE_PREFIXES):
        return False
    return token.startswith(TOP_LEVEL_DIRS) or (
        "/" not in token and token.endswith(".md")
    )


def _find_pointers(text: str) -> list[tuple[int, str]]:
    """按文档顺序返回 (行号, token)；同一 token 只保留首次出现（去重口径）。"""
    seen: dict[str, int] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        for token in TOKEN_RE.findall(line):
            if _is_pointer(token) and token not in seen:
                seen[token] = lineno
    return [(lineno, token) for token, lineno in seen.items()]


def _resolves(root: Path, token: str) -> bool:
    """token 指向的路径是否存在；以 `/` 结尾的 token 按目录判存在。"""
    target = root / token
    return target.is_dir() if token.endswith("/") else target.exists()


def _scan(repo_root: str, doc: str) -> tuple[int, list[tuple[str, int, str]]]:
    """返回 (指针总数, 失效指针列表)。"""
    root = Path(repo_root)
    doc_path = root / doc
    pointers = _find_pointers(doc_path.read_text(encoding="utf-8"))
    broken = [
        (str(doc_path), lineno, token)
        for lineno, token in pointers
        if not _resolves(root, token)
    ]
    return len(pointers), broken


def check_doc_pointers(
    repo_root: str, doc: str = "AGENTS.md"
) -> list[tuple[str, int, str]]:
    """返回失效指针列表：(文件, 行号, token)。空列表 = 全部有效。"""
    return _scan(repo_root, doc)[1]


def main() -> int:
    # Windows CI stdout 默认 cp1252：报告行含中文路径时直写会抛 UnicodeEncodeError。
    # sys.stdout.reconfigure(errors="replace") 官方兜底：任意编码不崩，非 ASCII 显示为 ?
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    repo_root = sys.argv[1]
    total, broken = _scan(repo_root, "AGENTS.md")
    if broken:
        print(f"[check_doc_pointers] {len(broken)} broken pointer(s):")
        for filename, lineno, token in broken:
            print(f"  {filename}:{lineno}: {token}")
        return 1
    print(f"[check_doc_pointers] OK: {total} pointer(s) resolved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
