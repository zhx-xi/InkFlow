"""#1172 多轮历史 reasoning_content 保留 — RED 契约。

缺陷：`_to_langchain_messages` 逐条构造 `AIMessage(content=msg.content)`，
assistant 轮次的 `reasoning_content` 丢失 → 下一轮请求缺该字段 →
LiteLLM 注入空格占位（`transformation.py:87` 告警），思考模型多轮质量静默退化。

本契约锁定「历史重建时 assistant 轮次必须携带 reasoning_content」。

可证伪性：当前实现（`langchain_client.py:301` 只传 content）→ 必然 FAIL。
"""

from __future__ import annotations

from inkflow.domain.ports.llm_client import ChatMessage
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient


class TestHistoryPreservesReasoningContent:
    """#1172：历史消息重建不得丢弃 reasoning_content。"""

    def test_assistant_history_message_carries_reasoning_content(self):
        """assistant 轮次带 reasoning_content → AIMessage 必须承载它（非丢弃）。

        可证伪性：恢复到「只传 content」的实现 → 本用例 FAIL。
        """
        messages = [
            ChatMessage(role="user", content="主角下一步做什么？"),
            ChatMessage(
                role="assistant",
                content="让他先去药庐。",
                reasoning_content="先评估伤势再决定去哪，避免编造从未出现的设定。",
            ),
        ]

        result = LangChainLLMClient._to_langchain_messages(messages)

        assistant = result[-1]
        blob = _flatten_message(assistant)
        assert "先评估伤势再决定去哪" in blob, (
            "assistant 轮次的 reasoning_content 必须进入 LangChain 消息"
            "（否则多轮请求缺该字段 → LiteLLM 空格占位 → 静默质量退化）"
        )

    def test_user_message_without_reasoning_is_unaffected(self):
        """无 reasoning 的消息（user / 旧数据）行为不变——不注入空 reasoning。

        防止实现「无条件塞空串」把 LiteLLM 的空占位告警换个形态复现。
        """
        messages = [ChatMessage(role="user", content="继续")]
        result = LangChainLLMClient._to_langchain_messages(messages)

        assert result[0].content == "继续"
        blob = _flatten_message(result[0])
        assert "reasoning_content" not in blob, (
            "无 reasoning 的消息不得凭空出现 reasoning_content 字段"
        )

    def test_system_message_role_map_still_enforced(self):
        """回归：非法角色仍抛 ValueError（不得因加字段而放宽角色校验）。"""
        import pytest

        with pytest.raises(ValueError, match="未知消息角色"):
            LangChainLLMClient._to_langchain_messages([ChatMessage(role="tool", content="x")])


def _flatten_message(msg: object) -> str:
    """把 LangChain 消息的可选字段序列化成一个字符串，供子串断言。

    覆盖 reasoning 可能落位的三类载体（实现方式未定，契约只要求「不丢」）：
      additional_kwargs / response_metadata / provider_specific_fields
    """
    parts: list[str] = []
    for attr in ("additional_kwargs", "response_metadata", "provider_specific_fields"):
        value = getattr(msg, attr, None)
        if value:
            parts.append(str(value))
    # 兜底：整个对象的 repr（实现若走未知载体，仍可被检出）
    parts.append(repr(msg))
    return "\n".join(parts)
