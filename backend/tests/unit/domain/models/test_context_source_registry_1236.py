"""#1236 契约：CHAPTER_SUMMARY 是「规划中、注入通道未接线」的上下文来源。

取证结论（见 issue #1236 与 specs/f6-context/spec.md）：
- spec §3.2 明确规划 chapter_summary（dynamic 层，前文摘要）；
- 基础设施大半就位：ChapterSummary 模型 / chapter_summaries 表 /
  SummaryService（§4.6）/ ContextService(summary_repo=) 注入点（deps 已传入）；
- 唯一缺口 = ContextSourceProtocol 的 SummarySource 适配器未实现，
  故运行时注册表（api/deps.py get_context_service）不含该槽位；
- 摘要功能的真实消费路径在 agentic 轨（agent_service 直接调 ensure_summary）
  与调试端点，均不经过 ContextSourceType 通道。

本文件钉住「保留 + 显式未实现标记」决策的三个面：
1. 枚举契约：CHAPTER_SUMMARY 保留（spec 规划项），层级映射为 DYNAMIC；
2. 注册表事实：无生产者（不在 get_context_service 装配的 sources 中）；
3. 标记面：context.py docstring / deps.py 注册表注释 / spec §3.2 表行
   必须带「未实现 + #1236」显式标记，且不得再虚假声称已实现
   （原 docstring「LLM 生成 + 缓存表 (本模块)」是失真文案，#1236 修正）。
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

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


# ── 2. 注册表事实：无生产者 ─────────────────────────────────────


def test_chapter_summary_has_no_registered_producer() -> None:
    """运行时注册表不含 CHAPTER_SUMMARY —— SummarySource 未实现（#1236 事实钉）.

    若未来实现并注册，本断言 FAIL 是**预期信号**：届时应删除本测试，
    并同步移除三处「未实现」标记（docstring / deps 注释 / spec 表行）。
    """
    svc = deps.get_context_service(MagicMock())
    assert ContextSourceType.CHAPTER_SUMMARY not in svc._sources
    # 注入点本身已就位（保留决策的依据之一）
    assert svc._summary_repo is not None


# ── 3. 标记面：三处显式「未实现 + #1236」 ───────────────────────


def test_enum_docstring_marks_chapter_summary_unimplemented() -> None:
    """context.py docstring 表格行必须显式标记未实现，且不再虚假声称已实现."""
    line = _chapter_summary_docstring_line()
    assert "未实现" in line, f"docstring 行缺「未实现」标记: {line!r}"
    assert "#1236" in line, f"docstring 行缺 issue 溯源标记: {line!r}"
    # 反向断言：失真文案「LLM 生成 + 缓存表 (本模块)」不得再以「已实现」口吻出现
    assert "LLM 生成 + 缓存表 (本模块)" not in line, (
        "docstring 仍保留 #1236 前的失真声称（暗示本模块已实现生产者）"
    )


def test_deps_registry_comment_marks_chapter_summary_unimplemented() -> None:
    """deps.py 注册表处必须注释说明 CHAPTER_SUMMARY 为何缺席（#1236 标记）."""
    text = _DEPS.read_text(encoding="utf-8")
    hits = [line for line in text.splitlines() if "#1236" in line]
    assert hits, "deps.py 缺 #1236 注释：注册表 5 项与枚举 7 项的差异无解释"
    assert any("CHAPTER_SUMMARY" in line for line in hits), (
        f"#1236 注释须点名 CHAPTER_SUMMARY: {hits!r}"
    )


def test_spec_table_marks_chapter_summary_unimplemented() -> None:
    """spec §3.2 数据源表格行必须标注「规划/未实现」状态（#1236）."""
    text = _SPEC.read_text(encoding="utf-8")
    rows = [
        line
        for line in text.splitlines()
        if line.strip().startswith("|") and "`chapter_summary`" in line
    ]
    assert rows, "spec §3.2 表格缺 chapter_summary 行"
    row = rows[0]
    assert "未实现" in row, f"spec 表行缺「未实现」标注: {row!r}"
    assert "#1236" in row, f"spec 表行缺 issue 溯源: {row!r}"
