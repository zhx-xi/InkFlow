"""本地检查（**不挂 CI**）：文档与代码不得新增「历史标记」。

背景：仓库里混入大量 issue/PR 号、日期、项目版本号，且常以元叙述形态出现
（`（#NNNN 实测）`、`用户拍板：选项 B，YYYY-MM-DD`、`已实现（PR #NNNN）`）。这些内容
对 AI agent 是噪音（跳转线索而非可执行信息），且随时间腐烂。正确归属 = git 履历 + ADR
+ issue 页。

规则（判定）：
- 三类标记：issue 号（3-5 位数字）、日期（`YYYY-MM-DD`）、项目版本（`X.Y.Z`，0.x / 1.x 形态；
  **短号不检**——实测约 345 处是本地枚举，如 spec 小节内的编号引用）。
- 路径豁免（EXEMPT_FILES / EXEMPT_PREFIXES）：CHANGELOG 版本+日期、FEATURES/README 版本表、
  adr/README 决策日期列、生成物、证据目录、检出器自身的契约测试（样本即用途）。
- 行豁免（LINE_EXEMPT）：ADR 头部 `> **日期**` / `> **状态**` / `> **依据**`、spec 头部
  `**Spec 版本**` —— Nygard 格式与头部元数据是文件用途本身。
- 假阳性抑制：URL（先剥除）、ISO 时间戳、依赖/工具版本、版本键值形态
  （`version: "X.Y.Z"`）、IPv4、CSS 十六进制色、章节号、SVG path。
- **不校验什么**：短号（1-2 位，混合面，人工判）；spec 元叙述（`用户拍板`/`已合入`）与
  实现代码块（一次性治理，判据需语义理解，非正则可覆盖）；豁免面内的一切。

用法:
  python ci_cd/check_marker_discipline.py --diff [--base origin/main]
      ↑ **只扫本次新增的行**（`git diff` 的 `+` 行）——存量脏文件可正常编辑，
        只有「新写进历史标记」才报。可从任意 cwd 调用（脚本自寻 git 根）。
  python ci_cd/check_marker_discipline.py --all
      ↑ 扫全仓整文件（收尾/验收用；豁免面外应清零）。

退出码: 0 无命中；1 有命中；2 参数错误。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ── 豁免面：整文件豁免（这些位置的标记是文件用途本身）────────────────
EXEMPT_FILES = frozenset(
    {
        "CHANGELOG.md",  # 版本 + 发布日期（Keep a Changelog 节标题骨架）
        "FEATURES.md",  # 版本→功能映射唯一权威
        "README.md",  # 版本进度表
        "adr/README.md",  # ADR 索引决策日期列
        "ci_cd/openapi_snapshot.json",  # 生成物（源自 docstring，勿手改）
        "frontend/packages/renderer/src/api/schema/openapi.d.ts",  # 同上（pnpm gen:api）
        # 检出器自身的契约测试：测试样本（真形态标记字面量）即该文件的用途 → 精确单文件豁免
        "ci_cd/tests/test_check_marker_discipline.py",
    }
)
EXEMPT_PREFIXES = ("docs/evidence/", "evidence/", "design/images/")
EXEMPT_SUFFIXES = (".png", ".jpg", ".jpeg", ".ico", ".svg", ".woff2", ".db", ".lock")
SKIP_DIR_PARTS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "dist",
        "build",
        "__pycache__",
        ".hermes",
        ".tmp",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
    }
)
SCAN_SUFFIXES = frozenset(
    {
        ".md",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".cjs",
        ".mjs",
        ".yml",
        ".yaml",
        ".json",
        ".toml",
        ".html",
        ".css",
    }
)

# ── 三类标记 ────────────────────────────────────────────────────────
ISSUE_RE = re.compile(r"#\d{3,5}(?![0-9a-fA-F])")
# 排除 ISO 时间戳（后紧跟 T 或数字/短横）
DATE_RE = re.compile(r"(?<![\d-])20\d{2}-\d{2}-\d{2}(?![\dT-])")
VERSION_RE = re.compile(r"(?<![\w.])v?(?:0\.\d{1,2}\.\d{1,2}|1\.\d{1,2}\.\d{1,2}|2\.0\.0)(?![\d.])")

URL_RE = re.compile(r"https?://\S+")
# 版本**键值**形态（`version: "X.Y.Z"` / `"version" = "X.Y.Z"`）= 配置数据，非历史标记
VERSION_KV_RE = re.compile(r"""\bversion\b\s*[:=]""")
# ADR / spec 头部元数据行（Nygard 格式与头部字段是文件用途本身）
LINE_EXEMPT_RE = re.compile(
    r">\s*\*\*(日期|状态|来源|依据|决策)\*\*|\*\*Spec 版本\*\*|\*\*依据\*\*|^\s*Spec 版本"
)
# 依赖 / 工具名（其后的版本号不是项目版本标记）
EXTERNAL_TOOLS = (
    "chromadb",
    "ruff",
    "loguru",
    "deepagents",
    "langchain",
    "langgraph",
    "openapi-typescript",
    "setup-uv",
    "actions/",
    "python",
    "pydantic",
    "sqlalchemy",
    "fastapi",
    "typer",
    "pnpm",
    "vite",
    "react",
    "uv ",
    "node",
    "electron",
    "pytest",
    "alembic",
    "httpx",
    "tailwind",
    "zustand",
)
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def is_exempt_path(rel: str) -> bool:
    """rel 为 POSIX 风格仓库相对路径。"""
    norm = rel.replace("\\", "/")
    if norm in EXEMPT_FILES:
        return True
    if norm.startswith(EXEMPT_PREFIXES) or norm.endswith(EXEMPT_SUFFIXES):
        return True
    return any(part in SKIP_DIR_PARTS for part in norm.split("/"))


def _version_is_external(line: str, start: int) -> bool:
    """命中位置前的窗口判定：已知依赖/工具名，或版本**键值**形态 → 假阳性。

    `version: "X.Y.Z"` 这类是配置数据（第三方 action 钉版、app 元数据），不是「历史标记」。
    """
    window = line[max(0, start - 24) : start]
    if VERSION_KV_RE.search(window):
        return True
    low = window.lower()
    return any(tool in low for tool in EXTERNAL_TOOLS)


def scan_text(text: str, rel: str = "") -> list[tuple[int, str, str]]:
    """返回 [(行号(1 基), 类型, 片段)]；豁免路径 → []。"""
    if rel and is_exempt_path(rel):
        return []
    hits: list[tuple[int, str, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if LINE_EXEMPT_RE.search(raw):
            continue
        # 先剥除 URL（URL 路径段里的版本号不是历史标记）
        line = URL_RE.sub("", raw)
        for kind, rx in (("issue", ISSUE_RE), ("date", DATE_RE), ("version", VERSION_RE)):
            for m in rx.finditer(line):
                if kind == "version" and _version_is_external(line, m.start()):
                    continue
                snippet = raw.strip()[:80]
                hits.append((lineno, kind, snippet))
                break
    return hits


def _git(args: list[str], cwd: Path) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return out.stdout


def parse_added_lines(diff_text: str) -> dict[str, list[tuple[int, str]]]:
    """解析 unified diff 的 `+` 行 → {相对路径: [(新行号, 文本)]}。

    只取新增行：`-` 删除行与上下文行不计（存量脏文件因此可正常编辑）。
    """
    result: dict[str, list[tuple[int, str]]] = {}
    cur: str | None = None
    lineno = 0
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            cur = line[4:].strip()
            cur = cur[2:] if cur.startswith("b/") else cur
            result.setdefault(cur, [])
            continue
        m = HUNK_RE.match(line)
        if m:
            lineno = int(m.group(1))
            continue
        if cur is None:
            continue
        if line.startswith("+"):
            result[cur].append((lineno, line[1:]))
            lineno += 1
        elif line.startswith(" "):
            lineno += 1
    return {k: v for k, v in result.items() if v}


def added_lines(root: Path, base: str) -> dict[str, list[tuple[int, str]]]:
    """本分支已提交改动 ∪ 工作区改动的**新增行**。"""
    merged: dict[str, list[tuple[int, str]]] = {}
    for args in ([f"{base}...HEAD"], ["--cached"], []):
        for rel, lines in parse_added_lines(
            _git(["diff", "--unified=0", "--no-color", *args], root)
        ).items():
            merged.setdefault(rel, []).extend(lines)
    return merged


def all_files(root: Path) -> list[str]:
    out: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in SCAN_SUFFIXES:
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        if is_exempt_path(rel):
            continue
        out.append(rel)
    return sorted(out)


def scan_files(root: Path, rels: list[str]) -> list[tuple[str, int, str, str]]:
    """返回 [(相对路径, 行号, 类型, 片段)]。"""
    hits: list[tuple[str, int, str, str]] = []
    for rel in rels:
        if is_exempt_path(rel) or Path(rel).suffix.lower() not in SCAN_SUFFIXES:
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, kind, snippet in scan_text(text, rel):
            hits.append((rel, lineno, kind, snippet))
    return hits


def _repo_root() -> Path:
    """git 仓库根（脚本可从任意 cwd 调用）；非 git 环境回退 cwd。"""
    top = _git(["rev-parse", "--show-toplevel"], Path.cwd()).strip()
    return Path(top) if top else Path.cwd()


def _report(hits: list[tuple[str, int, str, str]], scanned: str) -> int:
    if not hits:
        print(f"[check_marker_discipline] OK: {scanned}, no history marker")
        return 0
    files = sorted({h[0] for h in hits})
    print(f"[check_marker_discipline] {len(hits)} hit(s) in {len(files)} file(s):")
    for rel, lineno, kind, snippet in hits[:60]:
        print(f"  {rel}:{lineno}: {kind}: {snippet}")
    if len(hits) > 60:
        print(f"  ... and {len(hits) - 60} more")
    print("\n豁免面见 ci_cd/marker-discipline.md（策略）。需删除标记或改写为规范陈述后重跑。")
    return 1


def main() -> int:
    # Windows CI/控制台 stdout 可能是 cp1252：报告行含中文时直写会抛 UnicodeEncodeError
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    argv = sys.argv[1:]
    if not argv or argv[0] not in {"--diff", "--all"}:
        print(__doc__)
        return 2
    root = _repo_root()
    if argv[0] == "--all":
        rels = all_files(root)
        return _report(scan_files(root, rels), f"{len(rels)} file(s) scanned")

    base = "origin/main"
    if "--base" in argv:
        base = argv[argv.index("--base") + 1]
    added = added_lines(root, base)
    hits: list[tuple[str, int, str, str]] = []
    for rel, lines in added.items():
        if is_exempt_path(rel) or Path(rel).suffix.lower() not in SCAN_SUFFIXES:
            continue
        for lineno, text in lines:
            for _, kind, _snippet in scan_text(text, rel):
                hits.append((rel, lineno, kind, text.strip()[:80]))
    return _report(hits, f"{len(added)} changed file(s), added lines only")


if __name__ == "__main__":
    sys.exit(main())
