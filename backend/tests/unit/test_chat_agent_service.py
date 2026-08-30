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


class _ModelEndAgent:
    """fake agent 产出 on_chat_model_end 事件（完整 AIMessage 雏形）。"""

    def __init__(self, *, output: object, stream_first: bool = False) -> None:
        self.output = output
        self.stream_first = stream_first

    async def astream_events(self, inputs, version="v2"):
        if self.stream_first:
            yield {
                "event": "on_chat_model_stream",
                "run_type": "llm",
                "data": {"chunk": SimpleNamespace(content="hello")},
            }
        yield {
            "event": "on_chat_model_end",
            "data": {"output": self.output},
        }


class _ToolFlowAgent:
    """fake agent 产出 tool_start → tool_end → tool_start → 未知事件。"""

    async def astream_events(self, inputs, version="v2"):
        yield {
            "event": "on_tool_start",
            "run_id": "tool_1",
            "name": "search_characters",
            "data": {"input": {}},
        }
        yield {
            "event": "on_tool_end",
            "run_id": "tool_1",
            "name": "search_characters",
            "data": {"output": "found"},
        }
        yield {
            "event": "on_tool_start",
            "run_id": "tool_2",
            "name": "read_chapter",
            "data": {"input": {}},
        }
        yield {"event": "on_chain_end", "data": {}}


class TestStreamEventsCoverageGaps:
    """#708 coverage-backend 分支缺口补测（只补测试，不改功能代码）。"""

    @pytest.mark.asyncio
    async def test_getter_returns_empty_string_keeps_base_prompt(self) -> None:
        """getter 返回空串/falsy → system_prompt 保持不变（88->92 False 分支）。"""

        async def _getter(prompt: str, project_id: str) -> str:
            return ""

        svc, agent = _make_svc(project_context_getter=_getter)
        _, inputs = await _drain(svc, agent, prompt="你好", project_id=PROJECT_ID)
        assert inputs["messages"][0].content == BASE_PROMPT

    @pytest.mark.asyncio
    async def test_model_end_after_stream_skips_chunk_stream(self) -> None:
        """已产出 stream delta 后 on_chat_model_end 有 content → 不再切块补发 delta。"""
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        output = SimpleNamespace(content="hello world", tool_calls=[], response_metadata={})
        agent = _ModelEndAgent(output=output, stream_first=True)
        svc = ChatAgentService(agent=agent, system_prompt=BASE_PROMPT)
        frames = [ev async for ev in svc.stream_events(prompt="你好", project_id=PROJECT_ID)]
        assert [ev.type for ev in frames] == ["delta", "done"]
        assert frames[0].delta == "hello"
        steps, final_content, _ = svc.consume_trace()
        assert len(steps) == 1
        assert steps[0].message_content == "hello world"
        assert final_content == "hello world"

    @pytest.mark.asyncio
    async def test_model_end_output_none_is_noop(self) -> None:
        """on_chat_model_end 的 output 为 None → _collect_model_end 直接返回。"""
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        svc = ChatAgentService(agent=_ModelEndAgent(output=None), system_prompt=BASE_PROMPT)
        frames = [ev async for ev in svc.stream_events(prompt="你好", project_id=PROJECT_ID)]
        assert [ev.type for ev in frames] == ["done"]
        steps, final_content, token_total = svc.consume_trace()
        assert steps == []
        assert final_content == ""
        assert token_total == 0

    @pytest.mark.asyncio
    async def test_empty_tool_call_id_not_indexed(self) -> None:
        """tool_call id 为空串 → 不加入 _tool_call_index，on_tool_end 不回填 result。"""
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        output = SimpleNamespace(
            content="",
            tool_calls=[{"id": "", "name": "search", "args": {"q": "x"}}],
            response_metadata={},
        )
        svc = ChatAgentService(agent=_FakeAgent(), system_prompt=BASE_PROMPT)
        svc._collect_model_end(output)
        svc._collect_tool_result("", "found")
        steps, _, _ = svc.consume_trace()
        assert len(steps) == 1
        assert len(steps[0].tool_calls) == 1
        assert steps[0].tool_calls[0].result == ""
        assert steps[0].tool_calls[0].is_error is False

    @pytest.mark.asyncio
    async def test_tool_start_then_end_loop_back_edge(self) -> None:
        """tool_start → tool_end → tool_start → 未知事件 → 覆盖循环回边与 fall-through 分支。"""
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        svc = ChatAgentService(agent=_ToolFlowAgent(), system_prompt=BASE_PROMPT)
        frames = [ev async for ev in svc.stream_events(prompt="查询角色", project_id=PROJECT_ID)]
        assert [ev.type for ev in frames] == ["tool_call", "tool_result", "tool_call", "done"]
        assert frames[1].result == "found"
        assert frames[2].id == "tool_2"


class _WriteToolFlowAgent:
    """#718 fake agent - 产 save_draft 工具调用 + {ok:True} 结果，验证写工具流终止于 done."""

    async def astream_events(self, inputs, version="v2"):
        yield {
            "event": "on_tool_start",
            "run_id": "tool_1",
            "name": "save_draft",
            "data": {"input": {"content": "正文"}},
        }
        yield {
            "event": "on_tool_end",
            "run_id": "tool_1",
            "name": "save_draft",
            "data": {"output": '{"ok": true, "draft_id": "draft-1"}'},
        }
        yield {
            "event": "on_chat_model_end",
            "data": {"output": SimpleNamespace(
                content="草稿已保存", tool_calls=[], response_metadata={}
            )},
        }


class TestStreamEventsWriteToolTerminal:
    """#718 写工具流必须终止于 done 帧（不无限 running），并回显工具结果."""

    @pytest.mark.asyncio
    async def test_save_draft_stream_reaches_done_and_echoes_result(self) -> None:
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        svc = ChatAgentService(agent=_WriteToolFlowAgent(), system_prompt=BASE_PROMPT)
        frames = [ev async for ev in svc.stream_events(prompt="保存草稿", project_id=PROJECT_ID)]
        # 终帧必须是 done（流不裸断 / 不无限运行）
        assert frames[-1].type == "done"
        assert frames[-1].done is True
        # 写工具结果（{ok:True} 信封）被回吐到 tool_result 帧
        tool_results = [ev for ev in frames if ev.type == "tool_result"]
        assert len(tool_results) == 1
        assert tool_results[0].name == "save_draft"
        assert '"ok": true' in tool_results[0].result
        assert "draft-1" in tool_results[0].result


# ── #727 reasoning 帧 ──


class _ReasoningAgent:
    """fake agent 只产 on_chat_model_end，output 可含 additional_kwargs.reasoning_content。"""

    def __init__(self, output: object) -> None:
        self.output = output

    async def astream_events(self, inputs, version="v2"):
        yield {"event": "on_chat_model_end", "data": {"output": self.output}}


class TestStreamEventsReasoningFrame:
    """#727 思考过程：on_chat_model_end 消息含思考字段（reasoning_content）→ emit reasoning 帧。"""

    @pytest.mark.asyncio
    async def test_model_end_with_reasoning_content_emits_reasoning_frame(self) -> None:
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        output = SimpleNamespace(
            content="最终答案",
            tool_calls=[],
            response_metadata={},
            additional_kwargs={"reasoning_content": "让我想想…"},
        )
        svc = ChatAgentService(agent=_ReasoningAgent(output), system_prompt=BASE_PROMPT)
        frames = [ev async for ev in svc.stream_events(prompt="你好", project_id=PROJECT_ID)]
        reasoning_frames = [ev for ev in frames if ev.type == "reasoning"]
        assert len(reasoning_frames) == 1
        assert reasoning_frames[0].delta == "让我想想…"
        # 思考帧序列后仍应正常收尾（done 终帧，不裸断）
        assert frames[-1].done is True
        assert frames[-1].type == "done"

    @pytest.mark.asyncio
    async def test_model_end_without_reasoning_yields_no_reasoning_frame(self) -> None:
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        # output 无 additional_kwargs（常见模型不返回思考）→ 不 emit reasoning 帧
        output = SimpleNamespace(content="无思考回复", tool_calls=[], response_metadata={})
        svc = ChatAgentService(agent=_ReasoningAgent(output), system_prompt=BASE_PROMPT)
        frames = [ev async for ev in svc.stream_events(prompt="你好", project_id=PROJECT_ID)]
        assert not any(ev.type == "reasoning" for ev in frames)

    @pytest.mark.asyncio
    async def test_model_end_reasoning_persisted_into_step(self) -> None:
        """#740 思考持久化：reasoning_content → 步带 reasoning。

        RED：当前 AgentStep 无 reasoning 字段 → 访问 steps[0].reasoning 抛 AttributeError。
        """
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        output = SimpleNamespace(
            content="最终答案",
            tool_calls=[],
            response_metadata={},
            additional_kwargs={"reasoning_content": "让我想想…"},
        )
        svc = ChatAgentService(agent=_ReasoningAgent(output), system_prompt=BASE_PROMPT)
        _ = [ev async for ev in svc.stream_events(prompt="你好", project_id=PROJECT_ID)]
        steps, _, _ = svc.consume_trace()
        assert len(steps) == 1
        assert steps[0].reasoning == "让我想想…"


class TestChatAgentMemoryInjection:
    """#748 会话记忆注入 — history_getter 加载历史 messages 进消息链（多轮对话有记忆）。

    契约（D5=A 三合一之「会话记忆」）:
    1. ChatAgentService(..., history_getter=None) 构造可注入 history_getter。
    2. history_getter(project_id) -> list[history message]（role=user/ai）。
    3. stream_events 组装消息链：[System, 历史 user/ai..., 当前 Human]。
    4. getter 抛异常 → 历史注入失败隔离，回退 [System, 当前 Human]（不阻断流）。
    5. project_id=None → 不调 history_getter。
    """

    @pytest.mark.asyncio
    async def test_history_messages_injected_between_system_and_current_user(self) -> None:
        """history_getter 返回历史 → 消息链 = [System, 历史user, 历史ai, 当前Human]。"""
        from langchain_core.messages import AIMessage, HumanMessage

        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        async def _getter(project_id: str) -> list:
            return [
                SimpleNamespace(role="user", content="第一轮：我的主角是林晚"),
                SimpleNamespace(role="ai", content="好的，林晚作为主角加入主线"),
            ]

        agent = _FakeAgent()
        svc = ChatAgentService(
            agent=agent, system_prompt=BASE_PROMPT, history_getter=_getter
        )
        _, inputs = await _drain(svc, agent, prompt="第二轮：写他的背景", project_id=PROJECT_ID)
        messages = inputs["messages"]
        # 位置与角色映射：user→HumanMessage，ai→AIMessage
        assert [m.content for m in messages] == [
            BASE_PROMPT,
            "第一轮：我的主角是林晚",
            "好的，林晚作为主角加入主线",
            "第二轮：写他的背景",
        ]
        assert isinstance(messages[1], HumanMessage)
        assert isinstance(messages[2], AIMessage)

    @pytest.mark.asyncio
    async def test_history_getter_receives_project_id(self) -> None:
        """history_getter 接收 project_id。"""
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        received: list[str] = []

        async def _getter(project_id: str) -> list:
            received.append(project_id)
            return []

        agent = _FakeAgent()
        svc = ChatAgentService(
            agent=agent, system_prompt=BASE_PROMPT, history_getter=_getter
        )
        await _drain(svc, agent, prompt="你好", project_id=PROJECT_ID)
        assert received == [PROJECT_ID]

    @pytest.mark.asyncio
    async def test_history_getter_failure_falls_back_to_no_history(self) -> None:
        """getter 抛异常 → 历史注入失败隔离，消息链回退 [System, 当前Human]。"""
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        async def _getter(project_id: str) -> list:
            raise RuntimeError("history load failed")

        agent = _FakeAgent()
        svc = ChatAgentService(
            agent=agent, system_prompt=BASE_PROMPT, history_getter=_getter
        )
        frames, inputs = await _drain(svc, agent, prompt="你好", project_id=PROJECT_ID)
        assert [m.content for m in inputs["messages"]] == [BASE_PROMPT, "你好"]
        assert frames[-1].done is True

    @pytest.mark.asyncio
    async def test_single_turn_when_history_getter_absent(self) -> None:
        """未注入 history_getter（None）→ 消息链仍是 [System, 当前Human]（向后兼容）。"""
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        agent = _FakeAgent()
        svc = ChatAgentService(agent=agent, system_prompt=BASE_PROMPT)
        _, inputs = await _drain(svc, agent, prompt="你好", project_id=PROJECT_ID)
        assert [m.content for m in inputs["messages"]] == [BASE_PROMPT, "你好"]

    @pytest.mark.asyncio
    async def test_history_getter_skipped_when_project_id_none(self) -> None:
        """project_id=None → 不调 history_getter（无可追溯项目）。"""
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        called = False

        async def _getter(project_id: str) -> list:
            nonlocal called
            called = True
            return []

        agent = _FakeAgent()
        svc = ChatAgentService(
            agent=agent, system_prompt=BASE_PROMPT, history_getter=_getter
        )
        await _drain(svc, agent, prompt="你好", project_id=None)
        assert called is False
        assert [m.content for m in agent.calls[0]["inputs"]["messages"]] == [
            BASE_PROMPT,
            "你好",
        ]


class TestResume:
    """#766 阶段③ HITL resume 续跑——agent.ainvoke 收到 Command(resume=...) + thread_id config。"""

    @pytest.mark.asyncio
    async def test_resume_invokes_agent_with_command(self) -> None:
        """resume → ainvoke 收 Command(resume={"approved": True})，config 透传 thread_id。"""
        from unittest.mock import AsyncMock

        from langgraph.types import Command

        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        agent = AsyncMock()
        svc = ChatAgentService(agent=agent, system_prompt=BASE_PROMPT)
        # 装配期 thread_id（deps 注入或默认空；本用例白盒设值断言 config 透传）
        svc._thread_id = "thread-766"
        result = await svc.resume(conversation_id="conv-1", approved=True)

        assert result == {"ok": True}
        agent.ainvoke.assert_awaited_once()
        call = agent.ainvoke.await_args
        command = call.args[0]
        assert isinstance(command, Command)
        assert command.resume == {"approved": True}
        assert call.kwargs["config"] == {"configurable": {"thread_id": "thread-766"}}
