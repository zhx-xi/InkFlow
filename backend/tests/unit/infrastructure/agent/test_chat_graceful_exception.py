"""#832 对话优雅异常处理——工具循环/递归超限自动优雅降级，不裸抛.

spec f47 §14.2 异常处理增量：GraphRecursionError（工具循环/递归超限）触发时，
ChatAgentService 不再把原始异常转成 error 帧（对话「对话失败」），而是自动优雅
降级——整理已完成的工具结果/部分产出，返回「已尝试 N 步，未完全成功，已返回部分
结果」摘要 delta 帧 + done 终帧，对话不失败。

#832 拍板（核心：异常处理不是「抛出去」，而是「处理掉」）：
1. 递归超限 → 不裸抛 GRAPH_RECURSION_LIMIT（不转 error 帧，对话不失败）
2. 优雅降级 → 产出含「已尝试 N 步，未完全成功，已返回部分结果」摘要的 delta 帧
   + done 终帧（已流出的部分结果保留）
3. 正常路径零回归 → 无异常时 SSE 完整（delta/tool_call/tool_result/done，无 error）

说明：#839 已合入「GraphRecursionError → 裸 done 帧 + recursion_limit 60 护栏」；
本文件锁定 #832 剩余的「优雅降级摘要」增量——done 帧前须产出含
「未完全成功 / 已返回部分结果」的摘要文本（#839 的裸 done 缺此摘要）。

HITL 中断确认：#766 的 interrupt 帧 + resume 骨架仅适用于真实 `interrupt()` 点
（删除授权）；GraphRecursionError 是被 executor 抛出的异常、非可 resume 的暂停点，
故递归超限走「自动优雅降级」而非 HITL 中断（设计权衡，见 PR body）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langgraph.errors import GraphRecursionError

from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"
SYSTEM_PROMPT = "你是 InkFlow 系统级 Agent，拥有全部创作工具（检索/写入/审计）"
RECURSION_MSG = "Recursion limit of 25 reached without hitting a stop condition"


# ── 辅助 ──────────────────────────────────────


def _chunk(content: str) -> SimpleNamespace:
    """AIMessageChunk 鸭子替身（.content）。"""
    return SimpleNamespace(content=content)


def _llm_chunk_event(content: str) -> dict:
    """astream_events v2：on_chat_model_stream（run_type='llm'）→ delta 帧源。"""
    return {"event": "on_chat_model_stream", "run_type": "llm", "data": {"chunk": _chunk(content)}}


def _model_end_event(run_id: str, output: object) -> dict:
    """astream_events v2：on_chat_model_end（完整 AIMessage）→ AgentStep 收集源。"""
    return {
        "event": "on_chat_model_end",
        "name": "ChatOpenAI",
        "run_id": run_id,
        "data": {"output": output},
    }


def _tool_start_event(run_id: str, name: str, args: dict) -> dict:
    """astream_events v2：on_tool_start → tool_call 帧源。"""
    return {"event": "on_tool_start", "run_id": run_id, "name": name, "data": {"input": args}}


def _tool_end_event(run_id: str, name: str, output: str) -> dict:
    """astream_events v2：on_tool_end → tool_result 帧源。"""
    return {"event": "on_tool_end", "run_id": run_id, "name": name, "data": {"output": output}}


def _model_output(content: str, tool_calls: list[dict], tokens: int = 10) -> SimpleNamespace:
    """完整 AIMessage 鸭子替身（content + tool_calls + usage）。"""
    return SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        response_metadata={"usage": {"total_tokens": tokens}},
    )


class _FakeAgent:
    """fake deepagents agent — astream_events 为 async generator，按预置事件 dict 列表 yield。

    error_after=N：yield 前 N 个事件后抛 error（None = 不抛），模拟工具循环到上限抛
    GraphRecursionError。calls 记录每次 astream_events 的 inputs/version/config。
    """

    def __init__(
        self,
        events: list[dict] | None = None,
        error: Exception | None = None,
        error_after: int | None = None,
    ) -> None:
        self._events = list(events or [])
        self._error = error
        self._error_after = error_after
        self.calls: list[dict] = []

    async def astream_events(self, inputs, version="v2", config=None):
        self.calls.append({"inputs": inputs, "version": version, "config": config})
        for i, ev in enumerate(self._events):
            if self._error is not None and self._error_after is not None and i >= self._error_after:
                raise self._error
            yield ev
        if self._error is not None and (
            self._error_after is None or self._error_after >= len(self._events)
        ):
            raise self._error


def _make_svc(events=None, error=None, error_after=None, system_prompt: str = SYSTEM_PROMPT):
    """构造 ChatAgentService(agent=fake, system_prompt=...)。"""
    agent = _FakeAgent(events=events, error=error, error_after=error_after)
    svc = ChatAgentService(agent=agent, system_prompt=system_prompt)
    return svc, agent


# ── 契约用例 ──────────────────────────────────


class TestChatGracefulException:
    """#832 递归超限优雅降级契约。"""

    @pytest.mark.asyncio
    async def test_recursion_limit_done_not_error_frame(self) -> None:
        """#832 契约①（#839 已实现，回归锁定）：GraphRecursionError → 不裸抛，
        转发为 done 终帧（非 error 帧），对话不失败。"""
        svc, _ = _make_svc(
            events=[
                _llm_chunk_event("部分结果"),
                _tool_start_event("call_1", "search_characters", {}),
            ],
            error=GraphRecursionError(RECURSION_MSG),
            error_after=1,
        )
        frames = [ev async for ev in svc.stream_events(prompt="你好")]
        assert not any(ev.type == "error" for ev in frames)
        assert frames[-1].type == "done"
        assert frames[-1].done is True

    @pytest.mark.asyncio
    async def test_recursion_limit_yields_graceful_summary_delta(self) -> None:
        """#832 契约②（本增量 RED）：递归超限 → 优雅降级，产出含
        「已尝试 N 步，未完全成功，已返回部分结果」摘要的 delta 帧 + done 终帧。

        RED 期（#839 裸 done）：无此摘要 delta → 断言 FAIL（正确 RED）。
        """
        tool_output = _model_output(
            "试图查询主角",
            [{"name": "search_characters", "args": {"project_id": PROJECT_ID}, "id": "call_1"}],
        )
        svc, _ = _make_svc(
            events=[
                _llm_chunk_event("正在"),
                _model_end_event("llm_1", tool_output),
                _tool_end_event("call_1", "search_characters", '{"ok":true,"data":[]}'),
            ],
            error=GraphRecursionError(RECURSION_MSG),
            error_after=3,
        )
        frames = [ev async for ev in svc.stream_events(prompt="帮我查角色")]

        # 优雅降级摘要 delta：含「已尝试 N 步 + 未完全成功 + 已返回部分结果」
        summaries = [ev.delta for ev in frames if ev.type == "delta" and "未完全成功" in ev.delta]
        assert summaries, "递归超限应产出含「未完全成功」的优雅降级摘要 delta"
        assert any(("已尝试" in s) and ("已返回部分结果" in s) for s in summaries), (
            "摘要应含「已尝试 N 步，未完全成功，已返回部分结果」文案"
        )

        # 对话不失败：done 终帧收束，无 error 帧；已流出的部分结果保留
        assert frames[-1].type == "done"
        assert frames[-1].done is True
        assert not any(ev.type == "error" for ev in frames)
        assert any(ev.type == "tool_result" for ev in frames)  # 已完成工具结果保留

    @pytest.mark.asyncio
    async def test_recursion_limit_summary_reports_step_count(self) -> None:
        """#832 契约②b：摘要中的「已尝试 N 步」N 以已完成 agent 步（model 轮数）计，
        有工具调用的场景 N>0，而非恒 0/恒 1。"""
        tool_output = _model_output(
            "查角色",
            [{"name": "search_characters", "args": {"project_id": PROJECT_ID}, "id": "call_1"}],
        )
        svc, _ = _make_svc(
            events=[
                _model_end_event("llm_1", tool_output),
                _tool_end_event("call_1", "search_characters", '{"ok":true,"data":[]}'),
            ],
            error=GraphRecursionError(RECURSION_MSG),
            error_after=2,
        )
        frames = [ev async for ev in svc.stream_events(prompt="帮我查角色")]
        summary = next(
            (ev.delta for ev in frames if ev.type == "delta" and "已尝试" in ev.delta), ""
        )
        assert summary
        # 至少完成了 1 步（有 model_end → AgentStep），摘要应报告 N>=1
        assert "已尝试 1 步" in summary or "已尝试 2 步" in summary

    @pytest.mark.asyncio
    async def test_normal_path_no_regression(self) -> None:
        """#832 契约③：无异常时 SSE 完整——delta/tool_call/tool_result/done，无 error。"""
        svc, _ = _make_svc(
            events=[
                _llm_chunk_event("你"),
                _tool_start_event("call_1", "search_characters", {"project_id": PROJECT_ID}),
                _tool_end_event("call_1", "search_characters", '{"ok":true,"data":[]}'),
            ]
        )
        frames = [ev async for ev in svc.stream_events(prompt="你好")]
        assert [ev.type for ev in frames] == ["delta", "tool_call", "tool_result", "done"]
        assert not any(ev.type == "error" for ev in frames)
        assert frames[-1].done is True

    @pytest.mark.asyncio
    async def test_recursion_limit_does_not_propagate_msgs_when_zero_events(self) -> None:
        """#832 契约①b：流尚未产出任何事件即到上限（空事件 + 立即抛）→ 仍优雅降级
        为 done 终帧，不把 GraphRecursionError 抛给调用方。"""
        svc, _ = _make_svc(
            events=[],
            error=GraphRecursionError(RECURSION_MSG),
            error_after=0,
        )
        frames = [ev async for ev in svc.stream_events(prompt="你好")]
        assert frames[-1].type == "done"
        assert not any(ev.type == "error" for ev in frames)
