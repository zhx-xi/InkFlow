"""CI 护栏：GUI 原型目录 ↔ 页交互规格 双向一一对应 + 页规格头部指针（#1326）。

背景：GUI 设计为「双件套」结构——
- `design/GUI/<page>/`    = 交互原型（HTML + 各状态 PNG）
- `specs/f19-gui/<page>.md` = 该页交互规格

两者自 #795/#796（2026-08-29/30）建立后**零校验**，实测漂移到「15 个原型目录中
唯一一个无对应页规格的孤儿」（#1326 盘点：`design/GUI/book/` 有原型无 `specs/f19-gui/book.md`）。
本护栏做**存在性对应 + 头部指针**检查，防止再出现孤儿/幽灵，以及页规格失去原型指引。

规则（判定）：
- 页面目录集 = `design/GUI/*/` 下全部子目录，**排除** `_tools`（截图脚本，非页面）。
- 页规格集 = `specs/f19-gui/*.md`，**排除** `spec.md`（壳/内核/渲染层联合契约，非页面规格）。
- 有目录无规格 → 报「孤儿」（orphan）：原型在但无规格，后续会话找不到实现对照面。
- 有规格无目录 → 报「幽灵」（ghost）：规格在但无原型资产，规格失去设计基准。
- 页规格第 4 行（L4）必含 `> 对应 design/GUI/<page>/` 指针（<page> = 该规格文件名 stem）；
  缺失 / 指向他页 → 报「无指针」（pointer）。15 页 L4 格式已于 #1338 统一，故严格校验。
- 两侧同名且头部指针自指即通过。

⚠️ **不校验什么**（能力边界，务必知晓）：
- **不校验**「改了 UI 但没同步规格/原型」——需要 diff 分析 + PR 上下文，本脚本做不到。
  那条靠 `AGENTS.md §4.6` 的「三件同步」纪律 + PR 自查（PR 同步提醒见
  `.github/workflows/ui-spec-sync-reminder.yml`，**仅评论警告不阻断**）。
- **不校验** mtime 顺序（重命名/格式化会改 mtime，误报率高）。
- **不校验** L8「- 原型引用：」的 PNG 状态枚举是否与磁盘上真实 PNG 集一致
  （#1338 已统一 15 页粒度，但逐图比对需读文件集，超出门禁的轻量定位）。
- **不校验** PNG 内容是否反映新 UI（截图脚本为本地 headless，非 CI）。

用法: python ci_cd/check_gui_spec_sync.py <repo_root>
退出码 0 = 双向一一对应且头部指针自指；1 = 存在孤儿/幽灵/无指针；2 = 缺参数。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# 非页面目录/文件排除名单（相对 design/GUI/ 与 specs/f19-gui/）
EXCLUDED_PROTO_DIRS = frozenset({"_tools"})
EXCLUDED_SPEC_FILES = frozenset({"spec.md"})

PROTO_DIR_REL = ("design", "GUI")
SPEC_DIR_REL = ("specs", "f19-gui")

ORPHAN = "orphan"
GHOST = "ghost"
POINTER = "pointer"

# 页规格头部 L4 指针形态（#1338 统一 15/15）：`> 对应 design/GUI/<page>/（…）`
POINTER_RE = re.compile(r"^>\s*对应\s+design/GUI/([A-Za-z0-9_-]+)/")
POINTER_LINE_INDEX = 3  # 0-based → 文件第 4 行


def _page_dirs(repo_root: Path) -> list[str]:
    """design/GUI/ 下的页面目录名（排除 _tools 等非页面项）。"""
    proto_root = repo_root.joinpath(*PROTO_DIR_REL)
    if not proto_root.is_dir():
        return []
    return sorted(
        p.name for p in proto_root.iterdir() if p.is_dir() and p.name not in EXCLUDED_PROTO_DIRS
    )


def _page_specs(repo_root: Path) -> list[str]:
    """specs/f19-gui/ 下的页规格名（去掉 .md，排除 spec.md）。"""
    spec_root = repo_root.joinpath(*SPEC_DIR_REL)
    if not spec_root.is_dir():
        return []
    return sorted(
        p.stem
        for p in spec_root.iterdir()
        if p.is_file() and p.suffix == ".md" and p.name not in EXCLUDED_SPEC_FILES
    )


def _header_pointer(page: str, repo_root: Path) -> str | None:
    """读页规格 L4，返回其声明的目标页名；无 L4 / 不匹配形态 → None。

    读取失败（文件不存在/编码异常）同样返回 None，由调用方归为 pointer 问题。
    """
    spec_path = repo_root.joinpath(*SPEC_DIR_REL) / f"{page}.md"
    try:
        text = spec_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    lines = text.splitlines()
    if len(lines) <= POINTER_LINE_INDEX:
        return None
    match = POINTER_RE.match(lines[POINTER_LINE_INDEX].strip())
    return match.group(1) if match else None


def check_gui_spec_sync(repo_root: str) -> list[tuple[str, str]]:
    """返回不匹配项列表 [(kind, page)]，kind ∈ {"orphan", "ghost", "pointer"}；空列表 = 通过。

    orphan = 有原型目录无页规格；ghost = 有页规格无原型目录；
    pointer = 页规格 L4 缺「对应 design/GUI/<page>/」指针或指向他页
    （只对有原型目录的页面判 pointer，避免与 ghost 重复报同一根因）。
    """
    root = Path(repo_root)
    dirs = set(_page_dirs(root))
    specs = set(_page_specs(root))
    problems: list[tuple[str, str]] = []
    for page in sorted(dirs - specs):
        problems.append((ORPHAN, page))
    for page in sorted(specs - dirs):
        problems.append((GHOST, page))
    for page in sorted(specs & dirs):
        if _header_pointer(page, root) != page:
            problems.append((POINTER, page))
    return problems


def main() -> int:
    # Windows CI stdout 默认 cp1252：报告行含中文路径时直写会抛 UnicodeEncodeError。
    # sys.stdout.reconfigure(errors="replace") 官方兜底：任意编码不崩，非 ASCII 显示为 ?
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    repo_root = sys.argv[1]
    problems = check_gui_spec_sync(repo_root)
    root = Path(repo_root)
    if problems:
        print(f"[check_gui_spec_sync] {len(problems)} mismatch(es):")
        for kind, page in problems:
            spec_path = root.joinpath(*SPEC_DIR_REL) / f"{page}.md"
            if kind == ORPHAN:
                print(f"  {ORPHAN}: design/GUI/{page}/ has no spec -> expected {spec_path}")
            elif kind == GHOST:
                print(
                    f"  {GHOST}: {spec_path} has no prototype "
                    f"-> expected {root.joinpath(*PROTO_DIR_REL) / page}/"
                )
            else:
                print(
                    f"  {POINTER}: {spec_path} line {POINTER_LINE_INDEX + 1} "
                    f"must be '> 对应 design/GUI/{page}/（…）'"
                )
        return 1
    dirs = _page_dirs(root)
    print(
        f"[check_gui_spec_sync] OK: {len(dirs)} page(s) matched prototype <-> spec "
        f"+ header pointer self-reference"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
