"""Coverage backfill batch 2: usage_accounting 非 dict 守卫。

纯 domain 公开函数黑盒：
- ``result_usage`` 非 dict 入参 -> 零三元组（88 行）
- ``draft_fallback_needed`` 非 dict 入参 -> 需兜底（173-174 行）
- ai 消息形态分派（对象 / dict / 非 ai）逐分支覆盖
"""

from __future__ import annotations

from types import SimpleNamespace

from inkflow.domain.services.usage_accounting import (
    draft_fallback_needed,
    result_usage,
)


def test_result_usage_non_dict_returns_zero() -> None:
    """非 dict 入参（防御守卫）-> (0, 0, 0)。"""
    assert result_usage(["not", "dict"]) == (0, 0, 0)  # type: ignore[arg-type]  # 故意传非 dict 触发守卫


def test_draft_fallback_needed_non_dict_returns_true() -> None:
    """非 dict 入参 -> 需兜底（True）。"""
    assert draft_fallback_needed(["not", "dict"]) is True  # type: ignore[arg-type]  # 故意传非 dict 触发守卫


def test_draft_fallback_needed_ai_object_tool_calls_checked() -> None:
    """ai 对象消息带 tool_calls（属性路径）-> 非 save_draft 仍需兜底。"""
    ai = SimpleNamespace(type="ai", tool_calls=[SimpleNamespace(name="search_characters")])
    assert draft_fallback_needed({"messages": [ai]}) is True


def test_draft_fallback_needed_ai_dict_without_tool_calls() -> None:
    """ai dict 消息无 tool_calls -> 属性为 None 走 dict 兜底取值。"""
    assert draft_fallback_needed({"messages": [{"type": "ai"}]}) is True


def test_draft_fallback_needed_save_draft_returns_false() -> None:
    """ai dict 消息显式 tool_calls 含 save_draft / 非 ai -> 分别 False / 跳过。"""
    messages = [
        {"role": "human"},
        {"type": "ai", "tool_calls": [{"name": "save_draft"}]},
    ]
    assert draft_fallback_needed({"messages": messages}) is False
