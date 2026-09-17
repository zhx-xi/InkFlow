"""#1236 契约（#1253 起转动）：CHAPTER_SUMMARY 已接线。

取证结论（见 issue #1236 / #1253 与 specs/f6-context/spec.md）：
- spec §3.2 明确规划 chapter_summary（dynamic 层，前文摘要）；
- 基础设施：ChapterSummary 模型 / chapter_summaries 表 / SummaryService（§4.6）/
  ContextService(summary_repo=) 注入点；
- #1236 时唯一缺口 = ContextSourceProtocol 的 SummarySource 适配器未实现，
  故运行时注册表（api/deps.py get_context_service）不含该槽位；
- **#1253 已补齐该缺口** → 注册表含 CHAPTER_SUMMARY，组装通道产出该 source。

本文件原为「保留 + 显式未实现标记」的哨兵（#1236）。哨兵按设计触发（#1253），
故原三条标记断言（docstring / deps 注释 / spec 表行必须带「未实现」）已删除，
替换为「已注册」正向断言。本文件现钉住两个面：
1. 枚举契约：CHAPTER_SUMMARY 保留，层级映射为 DYNAMIC；
2. 注册表事实：有生产者（在 get_context_service 装配的 sources 中）。

端到端产出/降级行为见 tests/unit/infrastructure/context/test_summary_source_1253.py。
"""

from __future__ import annotations

import pathlib

from inkflow.api import deps
from inkflow.domain.models.context import (
    SOURCE_LAYER,
    ContextLayer,
    ContextSourceType,
)

_HERE = pathlib.Path(__file__).resolve()
_BACKEND_ROOT = next(p for p in _HERE.parents if p.name == "backend")
_REPO_ROOT = _BACKEND_ROOT.parent
_CONTEXT_MODEL = _BACKEND_ROOT / "src" / "inkflow" / "domain" / "models" / "context.py"
_DEPS = _BACKEND_ROOT / "src" / "inkflow" / "api" / "deps.py"
_SPEC = _REPO_ROOT / "specs" / "f6-context" / "spec.md"


def _chapter_summary_docstring_line() -> str:
    """取 context.py 枚举 docstring 表格里 chapter_summary 那一行."""
    text = _CONTEXT_MODEL.read_text(encoding="utf-8")
    hits = [line for line in text.splitlines() if "chapter_summary" in line and "│" in line]
    assert len(hits) == 1, f"docstring 表格应恰有一行 chapter_summary，实得 {hits}"
    return hits[0]


# ── 1. 枚举契约：保留（spec 规划项） ─────────────────────────────


def test_chapter_summary_enum_retained_as_planned_source() -> None:
    """CHAPTER_SUMMARY 保留在枚举中（spec §3.2 规划项，删除即契约面分叉）."""
    assert ContextSourceType.CHAPTER_SUMMARY == "chapter_summary"
    assert SOURCE_LAYER[ContextSourceType.CHAPTER_SUMMARY] is ContextLayer.DYNAMIC


# ── 2. 注册表事实：已接线（#1253 翻转自「无生产者」哨兵）────────


def test_chapter_summary_has_registered_producer() -> None:
    """运行时注册表含 CHAPTER_SUMMARY —— SummarySource 已实现（#1253 事实钉）.

    #1236 的 `has_no_registered_producer` 哨兵在此按设计翻转。
    """
    from unittest.mock import MagicMock

    from inkflow.infrastructure.context.sources import SummarySource

    svc = deps.get_context_service(MagicMock())
    assert ContextSourceType.CHAPTER_SUMMARY in svc._sources
    assert isinstance(svc._sources[ContextSourceType.CHAPTER_SUMMARY], SummarySource)
    # 注入点本身已就位（保留决策的依据之一）
    assert svc._summary_repo is not None


# ── 3. 标记面：三处「未实现」标记已随实施移除 ───────────────────


def test_enum_docstring_marks_chapter_summary_implemented() -> None:
    """context.py docstring 表格行须反映已实现（不得残留「未实现」标记）."""
    line = _chapter_summary_docstring_line()
    assert "未实现" not in line, f"docstring 行仍标「未实现」（#1253 已实施）: {line!r}"
    assert "#1253" in line, f"docstring 行缺实施 issue 溯源: {line!r}"


def test_deps_has_no_stale_unimplemented_comment() -> None:
    """deps.py 注册表处不得残留「CHAPTER_SUMMARY 未实现」的过期注释（#1253）."""
    text = _DEPS.read_text(encoding="utf-8")
    stale = [line for line in text.splitlines() if "CHAPTER_SUMMARY" in line and "未实现" in line]
    assert stale == [], f"deps.py 残留过期「未实现」注释: {stale!r}"


def test_spec_table_marks_chapter_summary_implemented() -> None:
    """spec §3.2 数据源表格行须标注已实现 + 实施 issue 溯源（#1253）."""
    text = _SPEC.read_text(encoding="utf-8")
    rows = [
        line
        for line in text.splitlines()
        if line.strip().startswith("|") and "`chapter_summary`" in line
    ]
    assert rows, "spec §3.2 表格缺 chapter_summary 行"
    row = rows[0]
    assert "未实现" not in row, f"spec 表行仍标「未实现」（#1253 已实施）: {row!r}"
    assert "#1253" in row, f"spec 表行缺实施 issue 溯源: {row!r}"


def test_spec_flow_no_longer_says_summary_source_unimplemented() -> None:
    """spec §4.1 收集流程不得再声明「SummarySource 未实现、当前 5 源」（#1253）."""
    text = _SPEC.read_text(encoding="utf-8")
    stale = [line for line in text.splitlines() if "SummarySource 未实现" in line]
    assert stale == [], f"spec §4.1 残留未实现标注: {stale!r}"
