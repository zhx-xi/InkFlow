"""context_errors.py 异常类行为测试（Phase 3 覆盖率补齐）。

两个错误类均有可选参数（suggestion / detail），消息格式随参数变化：
- ContextBudgetExceededError: 带 suggestion → 追加「建议: …」行
- SummaryGenerationError: 带 detail → 追加「 — …」后缀
"""

from __future__ import annotations

from inkflow.domain.ports.context_errors import (
    ContextBudgetExceededError,
    SummaryGenerationError,
)


def test_context_budget_exceeded_error_message_with_suggestion() -> None:
    """带 suggestion → 消息含预算/需求/建议三要素，属性可访问。"""
    err = ContextBudgetExceededError(budget=100, required=250, suggestion="精简写作要求")

    assert err.budget == 100
    assert err.required == 250
    assert err.suggestion == "精简写作要求"
    assert "需要 250 tokens" in str(err)
    assert "预算 100 tokens" in str(err)
    assert "建议: 精简写作要求" in str(err)


def test_context_budget_exceeded_error_without_suggestion() -> None:
    """suggestion 缺省 → 消息不含建议段。"""
    err = ContextBudgetExceededError(budget=100, required=250)

    assert err.suggestion == ""
    assert "建议" not in str(err)


def test_summary_generation_error_message_with_detail() -> None:
    """带 detail → 消息含 chapter_id 与 detail，属性可访问。"""
    err = SummaryGenerationError(chapter_id="c-1", detail="llm down")

    assert err.chapter_id == "c-1"
    assert err.detail == "llm down"
    assert "c-1" in str(err)
    assert "llm down" in str(err)


def test_summary_generation_error_without_detail() -> None:
    """detail 缺省 → 消息不含 detail 段。"""
    err = SummaryGenerationError(chapter_id="c-1")

    assert err.detail == ""
    assert " — " not in str(err)
