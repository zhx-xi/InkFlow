"""#902 usage 提取 helper — agent.invoke 结果 / llm.chat 返回值 → 用量三元组.

纯 domain 函数（仅 stdlib + typing，无 langchain/fastapi/sqlalchemy 依赖）：
- result_usage: agent.invoke 结果（dict，含 "messages"）→ (prompt, completion, total)。
  主源：逐 message usage_metadata（input_tokens/output_tokens/total_tokens，兼容
  prompt_tokens/completion_tokens 别名键）全消息求和；回退：顶层 result["usage"]
  （legacy/fake 形态）；双源皆缺 → (0, 0, 0)。total 以 total_tokens 为准
  （不用 p+c 推算）。
- chat_response_usage: llm.chat 返回值 → (prompt, completion, total)。主源：
  response.token_usage（ChatResponse：prompt_tokens/completion_tokens/total_tokens，
  None 安全）；回退：response.usage_metadata dict（AIMessage 鸭子）；皆缺 → 零三元组。

依据: .hermes/plans/contract-902.md §1.2 + backend/tests/unit/domain/services/
test_usage_accounting_902.py（RED 契约）。
"""

from __future__ import annotations

import json
from typing import Any, cast


def _int_or_zero(value: object) -> int:
    """None / 非数值 → 0（int(None) 不抛）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _as_int(value: object) -> int:
    """dict 值 → int（None 防御 → 0）。"""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _usage_prompt_tokens(usage: dict[str, Any]) -> int:
    """usage dict → prompt 侧 tokens：input_tokens / prompt_tokens 别名键（None 防御）。"""
    return _as_int(usage.get("input_tokens")) or _as_int(usage.get("prompt_tokens"))


def _usage_completion_tokens(usage: dict[str, Any]) -> int:
    """usage dict → completion 侧 tokens：output_tokens / completion_tokens 别名键."""
    return _as_int(usage.get("output_tokens")) or _as_int(usage.get("completion_tokens"))


def _usage_total_tokens(usage: dict[str, Any]) -> int:
    """usage dict → total tokens（total_tokens 键为准，不用 p+c 推算）。"""
    return _as_int(usage.get("total_tokens"))


def _message_usage(message: object) -> dict[str, Any] | None:
    """message 对象/dict → usage_metadata dict；无 → None."""
    usage = getattr(message, "usage_metadata", None)
    if usage is None and isinstance(message, dict):
        usage = message.get("usage_metadata")
    return usage if isinstance(usage, dict) else None


def _result_message_usage(result: dict[str, Any]) -> tuple[bool, int, int, int]:
    """逐 message usage_metadata 求和 → (has_usage, prompt, completion, total)."""
    messages = result.get("messages") or []
    has_usage = False
    prompt_total = 0
    completion_total = 0
    total = 0
    for msg in messages:
        usage = _message_usage(msg)
        if usage is None:
            continue
        has_usage = True
        prompt_total += _usage_prompt_tokens(usage)
        completion_total += _usage_completion_tokens(usage)
        total += _usage_total_tokens(usage)
    return has_usage, prompt_total, completion_total, total


def result_usage(result: dict) -> tuple[int, int, int]:
    """agent.invoke 结果 → (prompt, completion, total).

    主源：逐 message usage_metadata（langchain-core 1.x：input_tokens/output_tokens/
    total_tokens，兼容 prompt_tokens/completion_tokens 别名键）全消息求和；
    回退：顶层 result["usage"]（legacy/fake：total_tokens/prompt_tokens/
    completion_tokens）。双源皆缺 → (0, 0, 0)。total 以 total_tokens 为准
    （不用 p+c 推算）。
    """
    if not isinstance(result, dict):
        return (0, 0, 0)
    has_message_usage, prompt_total, completion_total, total = _result_message_usage(result)
    if has_message_usage:
        return (prompt_total, completion_total, total)
    usage = result.get("usage")
    if isinstance(usage, dict):
        return (
            _usage_prompt_tokens(usage),
            _usage_completion_tokens(usage),
            _usage_total_tokens(usage),
        )
    return (0, 0, 0)


def chat_response_usage(response: object) -> tuple[int, int, int]:
    """llm.chat 返回值 → (prompt, completion, total).

    主源：response.token_usage（ChatResponse：prompt_tokens/completion_tokens/
    total_tokens，None 安全）；回退：response.usage_metadata dict（AIMessage 鸭子）；
    皆缺 → 零三元组。全部 getattr/None 守卫，鸭子对象（SimpleNamespace 无 usage）→
    (0, 0, 0) 不抛。
    """
    token_usage = getattr(response, "token_usage", None)
    if token_usage is not None:
        return (
            _int_or_zero(getattr(token_usage, "prompt_tokens", None)),
            _int_or_zero(getattr(token_usage, "completion_tokens", None)),
            _int_or_zero(getattr(token_usage, "total_tokens", None)),
        )
    usage_metadata = getattr(response, "usage_metadata", None)
    if isinstance(usage_metadata, dict):
        metadata: dict[str, Any] = cast(dict[str, Any], usage_metadata)
        return (
            _usage_prompt_tokens(metadata),
            _usage_completion_tokens(metadata),
            _usage_total_tokens(metadata),
        )
    return (0, 0, 0)


def extract_total_tokens(result: dict) -> int:
    """总 token 视图（#860 旧 helper 语义迁移，book_service 经 re-export 暴露）.

    Primary source (real deepagents 0.7.5 graph result): per-AIMessage
    usage_metadata dicts ({'total_tokens': N, ...}) — sum over ALL messages.
    Fallback (legacy/service-level contract, older fakes): top-level
    result["usage"]["total_tokens"] when present.
    """
    messages = result.get("messages") or []
    total = 0
    for msg in messages:
        usage = _message_usage(msg)
        if usage is not None:
            total += _usage_total_tokens(usage)
    if total == 0:
        usage = result.get("usage")
        if isinstance(usage, dict):
            total = _usage_total_tokens(usage)
    return total


def _message_kind(message: object) -> str:
    """消息 type/role 读取（dict 双键 + 对象 .type 双形态，None 防御）."""
    if isinstance(message, dict):
        kind = message.get("type") or message.get("role")
        return str(kind) if kind is not None else ""
    return str(getattr(message, "type", "") or "")


def _message_content(message: object) -> object:
    """消息 content 读取（dict/对象双形态，缺失 → None）."""
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return content


def draft_fallback_needed(result: dict[str, Any]) -> bool:
    """#975 守卫：agent 是否已显式 save_draft（False = 不需要服务层兜底建草稿）.

    镜像 agentic_writer_service._history_has_tool_call 语义：遍历 result["messages"]
    的 AI 消息（dict type=="ai" / 对象 .type=="ai"），任一 tool_calls 含
    name=="save_draft" → False；无消息历史/非 dict 输入 → True（需兜底）。
    纯 domain 函数，零框架依赖（dict/对象双形态 getattr 读取）。
    """
    if not isinstance(result, dict):
        return True
    messages = result.get("messages") or []
    for message in messages:
        if _message_kind(message) != "ai":
            continue
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls is None and isinstance(message, dict):
            tool_calls = message.get("tool_calls")
        for call in tool_calls or []:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name == "save_draft":
                return False
    return True


def _extract_saved_draft_id(result: dict[str, Any]) -> str:
    """#975：从消息历史反向提取 agent save_draft 工具结果的 draft_id（私有）.

    简化裁定（GREEN 可执行形态）：反向扫 messages，找 type=="tool"/role=="tool"
    的消息中 content 可 json.loads 且 ok==True 且含 draft_id 键 → 返回该 draft_id
    字符串；否则 ""（提取失败不新建草稿的语义由 draft_fallback_needed 守卫保证）。
    """
    if not isinstance(result, dict):
        return ""
    messages = result.get("messages") or []
    for message in reversed(messages):
        if _message_kind(message) != "tool":
            continue
        content = _message_content(message)
        if not isinstance(content, str):
            continue
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("ok") is True and "draft_id" in data:
            return str(data["draft_id"])
    return ""
