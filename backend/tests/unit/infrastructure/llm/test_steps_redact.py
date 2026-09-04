"""#872 非功能安全 C5①：AgentRun.steps 决策轨迹脱敏（S3a 补测）。

背景：chat_stream/agent 端点在把 prompt 发给 LLM 前已脱敏（redact_secrets），但
**决策轨迹 AgentRun.steps**（message_content + tool_calls[].arguments/result）会回显
工具参数链——若工具参数/结果里出现密钥形态（LLM 从上下文回显、或工具处理含 key 的
文本），steps 落库即泄漏到磁盘。本契约要求：steps 在落库前经 `redact_step` 全量脱敏。

RED 阶段：redact.py 尚无 redact_step（import 失败 → 收集级 FAIL）。
"""

from __future__ import annotations

from inkflow.infrastructure.llm.redact import redact_step

# 案列用拼接构造（源码不出连续敏感形态）
KEY = "sk-" + ("z" * 18)  # 18 位体（A 正则命中）
RESULT_KEY = "Bea" + "rer " + ("w" * 20)  # Bearer <20w>（_BEARER_PATTERN 命中）


def _step(message_content: str = "", tool_calls: list | None = None):
    from inkflow.domain.models.agent_run import AgentStep

    return AgentStep(index=0, message_content=message_content, tool_calls=tool_calls or [])


def test_message_content_key_redacted():
    """steps 的 message_content 含 key → 脱敏后无 key。"""
    step = _step(message_content=f"先用 {KEY} 再继续")
    out = redact_step(step)
    assert KEY not in out.message_content
    assert "****" in out.message_content


def test_tool_call_arguments_key_redacted():
    """steps 的 tool_calls[].arguments（dict 值）含 key → 递归脱敏。"""
    from inkflow.domain.models.agent_run import AgentToolCall

    step = _step(
        message_content="tool time",
        tool_calls=[
            AgentToolCall(
                step_index=0,
                tool_name="save_draft",
                arguments={"content": f"正文含 {KEY}", "summary": "ok"},
                result="",
            )
        ],
    )
    out = redact_step(step)
    args = out.tool_calls[0].arguments
    # 递归进 dict 值字符串
    assert KEY not in str(args)
    assert "****" in str(args)


def test_tool_call_result_key_redacted():
    """steps 的 tool_calls[].result（str）含 Bearer token → 脱敏。"""
    from inkflow.domain.models.agent_run import AgentToolCall

    step = _step(
        tool_calls=[
            AgentToolCall(
                step_index=0,
                tool_name="search",
                arguments={},
                result=f"返回了 {RESULT_KEY}",
            )
        ]
    )
    out = redact_step(step)
    assert RESULT_KEY not in out.tool_calls[0].result
    assert "****" in out.tool_calls[0].result


def test_nested_tool_call_list_is_redacted():
    """steps 多个 tool_calls 都脱敏（不只第一条）。"""
    from inkflow.domain.models.agent_run import AgentToolCall

    step = _step(
        tool_calls=[
            AgentToolCall(
                step_index=0,
                tool_name="t1",
                arguments={"a": KEY},
                result="",
            ),
            AgentToolCall(
                step_index=1,
                tool_name="t2",
                arguments={"b": KEY},
                result="",
            ),
        ]
    )
    out = redact_step(step)
    for call in out.tool_calls:
        assert KEY not in str(call.arguments)
