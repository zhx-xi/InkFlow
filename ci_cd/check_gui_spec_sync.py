"""CI 护栏：GUI 原型目录 ↔ 页交互规格 双向一一对应（#1326 PR 1）。

背景：GUI 设计为「双件套」结构——
- `design/GUI/<page>/`    = 交互原型（HTML + 各状态 PNG）
- `specs/f19-gui/<page>.md` = 该页交互规格

两者自 #795/#796（2026-08-29/30）建立后**零校验**，实测漂移到「15 个原型目录中
唯一一个无对应页规格的孤儿」（#1326 盘点：`design/GUI/book/` 有原型无 `specs/f19-gui/book.md`）。
本护栏做**存在性对应**检查，防止再出现孤儿/幽灵。

规则（判定）：
- 页面目录集 = `design/GUI/*/` 下全部子目录，**排除** `_tools`（截图脚本，非页面）。
- 页规格集 = `specs/f19-gui/*.md`，**排除** `spec.md`（壳/内核/渲染层联合契约，非页面规格）。
- 有目录无规格 → 报「孤儿」（orphan）：原型在但无规格，后续会话找不到实现对照面。
- 有规格无目录 → 报「幽灵」（ghost）：规格在但无原型资产，规格失去设计基准。
- 两侧同名即通过。

⚠️ **不校验什么**（能力边界，务必知晓）：
- **不校验**「改了 UI 但没同步规格/原型」——需要 diff 分析 + PR 上下文，本脚本做不到。
  那条靠 `AGENTS.md §4.6` 的「三件同步」纪律 + PR 自查。
- **不校验** mtime 顺序（重命名/格式化会改 mtime，误报率高）。
- **不校验** 页规格头部是否含「对应 design/GUI/<page>/」指针（现状 14/14 格式统一，
  但存在两档粒度差异，强制化需先统一格式，见 #1326 评论）。
- **不校验** PNG 内容是否反映新 UI（截图脚本为本地 headless，非 CI）。

用法: python ci_cd/check_gui_spec_sync.py <repo_root>
退出码 0 = 双向一一对应；1 = 存在孤儿/幽灵；2 = 缺参数。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 非页面目录/文件排除名单（相对 design/GUI/ 与 specs/f19-gui/）
EXCLUDED_PROTO_DIRS = frozenset({"_tools"})
EXCLUDED_SPEC_FILES = frozenset({"spec.md"})

PROTO_DIR_REL = ("design", "GUI")
SPEC_DIR_REL = ("specs", "f19-gui")

ORPHAN = "orphan"
GHOST = "ghost"


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


def check_gui_spec_sync(repo_root: str) -> list[tuple[str, str]]:
    """返回不匹配项列表 [(kind, page)]，kind ∈ {"orphan", "ghost"}；空列表 = 一一对应。

    orphan = 有原型目录无页规格；ghost = 有页规格无原型目录。
    """
    root = Path(repo_root)
    dirs = set(_page_dirs(root))
    specs = set(_page_specs(root))
    problems: list[tuple[str, str]] = []
    for page in sorted(dirs - specs):
        problems.append((ORPHAN, page))
    for page in sorted(specs - dirs):
        problems.append((GHOST, page))
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
            if kind == ORPHAN:
                print(
                    f"  {ORPHAN}: design/GUI/{page}/ has no spec -> "
                    f"expected {root.joinpath(*SPEC_DIR_REL) / (page + '.md')}"
                )
            else:
                print(
                    f"  {GHOST}: {root.joinpath(*SPEC_DIR_REL) / (page + '.md')} has no prototype "
                    f"-> expected {root.joinpath(*PROTO_DIR_REL) / page}/"
                )
        return 1
    dirs = _page_dirs(root)
    print(f"[check_gui_spec_sync] OK: {len(dirs)} page(s) matched prototype <-> spec")
    return 0


if __name__ == "__main__":
    sys.exit(main())
