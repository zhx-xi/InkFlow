"""#680 chat agent 上下文注入 RED 契约测试 — ChatAgentService 服务层.

背景（G13a 实锤）: chat agent 是唯一不接上下文注入的路径——`stream_events` 签名
无 project_id，端点收到 project_id 后丢弃，系统消息零项目上下文；5 个只读工具 schema
强制 LLM 自报 project_id（#275 编造全零 UUID 孤儿数据先例）。

本文件锁定的契约（决策已拍板方案 b）:
1. `ChatAgentService()` 构造可注入 `project_context_getter`（装配期闭包，接收
   prompt + project_id → 返回渲染后的项目上下文段）。决策点: getter 由一个
   callable 承载（对齐 PlannerService 的 project_context_getter 先例），其内部
   走 context_service.build_context + render_system_prompt（与右侧 ContextPanel
   同源，7 源注入）。
2. `stream_events(prompt, project_id, chapter_context=None)` 签名含 `project_id`。
3. `stream_events` 组装 SystemMessage 前调用 getter 增强系统提示词；失败回退基础
   提示词（失败隔离，不阻断流）。

被测模块（已实现但本项目下即 RED — 目标契约未实现）:
    from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

RED 预期（对照当前实现）:
- 当前 __init__ 只有 (agent, system_prompt)，无 project_context_getter
  → 构造传 getter 抛 TypeError（FAILED）
- 当前 stream_events 签名 (prompt, chapter_context) 无 project_id
  → inspect 断言 FAILED
- 系统消息不含项目上下文 → 断言 FAILED
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

BASE_PROMPT = "你是 InkFlow 系统级写作 Agent"
PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"
CONTEXT_SEGMENT = "## 角色\n林晚：冷静、果决"


class _FakeAgent:
    """fake deepagents agent — astream_events 记录 inputs 并 yield 单个 delta 后 done."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def astream_events(self, inputs, version="v2"):
        self.calls.append({"inputs": inputs, "version": version})
        yield {
            "event": "on_chat_model_stream",
            "run_type": "llm",
            "data": {"chunk": SimpleNamespace(content="好")},
        }


def _make_svc(*, project_context_getter=None, system_prompt: str = BASE_PROMPT):
    """构造 ChatAgentService（agent=fake + 可选 getter）。"""
    from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

    agent = _FakeAgent()
    svc = ChatAgentService(
        agent=agent,
        system_prompt=system_prompt,
        project_context_getter=project_context_getter,
    )
    return svc, agent


async def _drain(svc, agent, **kwargs):
    """跑完 stream_events 并返回 (frames, 首个 agent 调用 inputs)。"""
    frames = [ev async for ev in svc.stream_events(**kwargs)]
    assert len(agent.calls) == 1
    return frames, agent.calls[0]["inputs"]


class TestStreamEventsSignature:
    """stream_events 签名锁定 project_id 参数（数据面断链修复）。"""

    def test_signature_contains_project_id(self) -> None:
        """签名含 project_id。"""
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        params = inspect.signature(ChatAgentService.stream_events).parameters
        assert "project_id" in params


class TestProjectContextInjection:
    """project_context_getter 增强系统消息（7 源同源注入）。"""

    @pytest.mark.asyncio
    async def test_system_message_contains_project_context(self) -> None:
        """getter 返回项目上下文段 → SystemMessage 内容被增强（base + 段）。"""

        async def _getter(prompt: str, project_id: str) -> str:
            return f"CALL:{prompt}:{project_id}"

        svc, agent = _make_svc(project_context_getter=_getter)
        _, inputs = await _drain(svc, agent, prompt="根据大纲生成第一章", project_id=PROJECT_ID)
        system = inputs["messages"][0]
        # 系统消息内容 = 基础提示词 + getter 返回段（getter 收到的 prompt/project_id）
        assert system.content == f"{BASE_PROMPT}\n\nCALL:根据大纲生成第一章:{PROJECT_ID}"

    @pytest.mark.asyncio
    async def test_getter_receives_prompt_and_project_id(self) -> None:
        """getter 接收 (prompt, project_id)。"""
        received: list[tuple[str, str]] = []

        async def _getter(prompt: str, project_id: str) -> str:
            received.append((prompt, project_id))
            return CONTEXT_SEGMENT

        svc, agent = _make_svc(project_context_getter=_getter)
        await _drain(svc, agent, prompt="找一下主角", project_id=PROJECT_ID)
        assert received == [("找一下主角", PROJECT_ID)]

    @pytest.mark.asyncio
    async def test_no_project_id_skips_context_injection(self) -> None:
        """project_id=None → 不调 getter，系统消息为纯基础提示词。"""
        called = False

        async def _getter(prompt: str, project_id: str) -> str:
            nonlocal called
            called = True
            return CONTEXT_SEGMENT

        svc, agent = _make_svc(project_context_getter=_getter)
        _, inputs = await _drain(svc, agent, prompt="继续写", project_id=None)
        assert inputs["messages"][0].content == BASE_PROMPT
        assert called is False

    @pytest.mark.asyncio
    async def test_getter_failure_falls_back_to_base_prompt(self) -> None:
        """getter 抛异常 → 系统消息回退基础提示词（失败隔离，不阻断流）。"""

        async def _getter(prompt: str, project_id: str) -> str:
            raise RuntimeError("context assemble failed")

        svc, agent = _make_svc(project_context_getter=_getter)
        frames, inputs = await _drain(svc, agent, prompt="你好", project_id=PROJECT_ID)
        assert inputs["messages"][0].content == BASE_PROMPT
        assert frames[-1].done is True

    @pytest.mark.asyncio
    async def test_no_getter_uses_base_prompt(self) -> None:
        """未注入 getter（None）→ 系统消息为纯基础提示词，流正常产出 done。"""
        svc, agent = _make_svc()
        frames, inputs = await _drain(svc, agent, prompt="你好", project_id=PROJECT_ID)
        assert inputs["messages"][0].content == BASE_PROMPT
        assert frames[-1].done is True


class TestStreamEventsBackwardCompat:
    """帧映射往兼容性守护——project_id 加入不破坏既有 delta/done 帧产出。"""

    @pytest.mark.asyncio
    async def test_delta_and_done_frames_still_produced(self) -> None:
        """project_id 传递下，on_chat_model_stream → delta 帧 + 终帧 done。"""
        svc, agent = _make_svc()
        frames, _ = await _drain(svc, agent, prompt="你好", project_id=PROJECT_ID)
        assert [ev.type for ev in frames] == ["delta", "done"]
        assert frames[0].delta == "好"

    @pytest.mark.asyncio
    async def test_chapter_context_appended_to_user_message(self) -> None:
        """chapter_context 非空 → HumanMessage content 追加章节上下文段落（不破坏既有行为）。"""
        svc, agent = _make_svc()
        _, inputs = await _drain(
            svc, agent, prompt="继续写", project_id=PROJECT_ID, chapter_context="第一章：初入宗门"
        )
        assert "继续写" in inputs["messages"][1].content
        assert "第一章：初入宗门" in inputs["messages"][1].content


class _RaisingToolAgent:
    """#697 fake agent — 先产 tool_call 事件，随后抛 RuntimeError（模拟工具异常）。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def astream_events(self, inputs, version="v2"):
        self.calls.append({"inputs": inputs, "version": version})
        yield {
            "event": "on_tool_start",
            "run_id": "tool_1",
            "name": "search_characters",
            "data": {"input": {}},
        }
        raise RuntimeError("工具执行失败: search_characters boom")


class TestStreamEventsToolExceptionTerminal:
    """#697 工具执行异常 → 保证产出 error 帧 + done 帧（不裸断流）。"""

    @pytest.mark.asyncio
    async def test_tool_exception_yields_error_and_done_frames(self) -> None:
        """astream_events 迭代中抛 RuntimeError → 仍产出 error 帧 + done 帧作为终帧。"""
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        agent = _RaisingToolAgent()
        svc = ChatAgentService(agent=agent, system_prompt=BASE_PROMPT)
        frames = [ev async for ev in svc.stream_events(prompt="查角色", project_id=PROJECT_ID)]
        # 终帧必须是 done（流不裸断）
        assert frames[-1].type == "done"
        assert frames[-1].done is True
        # 含恰好一个 error 帧，携带工具执行失败信息
        error_frames = [ev for ev in frames if ev.type == "error"]
        assert len(error_frames) == 1
        assert error_frames[0].done is True
        assert "工具执行失败" in error_frames[0].error

    @pytest.mark.asyncio
    async def test_tool_exception_without_tool_start_still_guarantees_terminal(self) -> None:
        """agent 直接抛异常（无 tool_call 事件）→ 仍产出 error + done 终帧。"""
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        class _BoomAgent:
            async def astream_events(self, inputs, version="v2"):
                raise RuntimeError("boom")
                yield  # unreachable

        svc = ChatAgentService(agent=_BoomAgent(), system_prompt=BASE_PROMPT)
        frames = [ev async for ev in svc.stream_events(prompt="你好", project_id=PROJECT_ID)]
        assert frames[-1].type == "done"
        assert frames[-1].done is True
        error_frames = [ev for ev in frames if ev.type == "error"]
        assert len(error_frames) == 1
