"""#821: deepagents 装配 thread_id 回归 RED 契约测试.

#806 给 harness.build_deep_agent 加 InMemorySaver(checkpointer)。langgraph 在
invoke / astream_events 无 config={"configurable": {"thread_id": ...}} 时抛
"Checkpointer requires thread_id"（#822）。chat/agentic 主 invoke 未传 config →
工具循环失败。

本文件锁定契约（决策已拍板 ①②③ 都做）:
1. ChatAgentService.stream_events 调 agent.astream_events 必须传
   config={"configurable": {"thread_id": <thread_id>}}。
2. AgenticWriterService._invoke_agent 调 agent.invoke 必须传 config（含 thread_id）。
3. DeepAgentInvokeAdapter.invoke 未显式传 config 时须自动补 thread_id（兜底）。

当前实现对照:
- ChatAgentService.stream_events 调 astream_events({"messages": ...}, version="v2")
  无 config（chat_agent_service.py L150）→ 契约 1 FAIL。
- AgenticWriterService._invoke_agent(agent, messages) 无 thread_id 参数、调
  agent.invoke(messages) 无 config（agentic_writer_service.py L239）→ 契约 2 FAIL。
- DeepAgentInvokeAdapter.invoke(messages, config=None) config=None 透传给 inner
  （agentic_writer.py L86-88）→ 契约 3 FAIL。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

THREAD_ID = "thread-abc-123"


class _FakeAgent:
    """fake chat agent — astream_events 记录 inputs/version/config."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def astream_events(self, inputs, version="v2", config=None):
        self.calls.append({"inputs": inputs, "version": version, "config": config})
        yield {"event": "on_chain_end", "data": {}}


def _chat_svc():
    from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

    agent = _FakeAgent()
    svc = ChatAgentService(agent=agent, system_prompt="你是 InkFlow 系统 Agent")
    return svc, agent


class TestChatAgentServiceThreadId:
    """契约 1: stream_events 必须传 config.thread_id（#806 checkpointer 硬依赖）。"""

    @pytest.mark.asyncio
    async def test_stream_events_passes_thread_id_config(self) -> None:
        """装配期赋值的 _thread_id 必须注入 astream_events 的 config。"""
        svc, agent = _chat_svc()
        svc._thread_id = THREAD_ID  # 装配期已赋值（当前实现恒 "")
        frames = [ev async for ev in svc.stream_events(prompt="帮我写一章", project_id=None)]
        assert any(ev.type == "done" for ev in frames)
        assert len(agent.calls) == 1
        cfg = agent.calls[0]["config"]
        # #839：config 含 configurable.thread_id + recursion_limit 护栏（非精确 dict 匹配）
        assert cfg["configurable"] == {"thread_id": THREAD_ID}
        assert cfg.get("recursion_limit", 25) > 25

    @pytest.mark.asyncio
    async def test_missing_thread_id_exception_is_surfaced(self) -> None:
        """config 缺失 → InMemorySaver 抛 Checkpointer requires thread_id，错误须被
        传播为 error 帧（不被静默吞掉）。"""
        from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

        class _RaisingAgent:
            def __init__(self) -> None:
                self.calls = 0

            async def astream_events(self, inputs, version="v2", config=None):
                self.calls += 1
                raise ValueError("Checkpointer requires thread_id")
                yield  # stdlib: 含 yield 才是 async generator（首段 raise 在迭代时传播）

        agent = _RaisingAgent()
        svc = ChatAgentService(agent=agent, system_prompt="你是 InkFlow 系统 Agent")
        frames = [ev async for ev in svc.stream_events(prompt="hi", project_id=None)]
        err = [f for f in frames if f.type == "error"]
        assert err, "missing thread_id must surface an error frame, not be swallowed"
        assert "thread_id" in err[0].error or "Checkpointer" in err[0].error


class TestAgenticWriterServiceThreadId:
    """契约 2: agentic 主流程 _invoke_agent 必须传 config.thread_id（run_id 派生）。"""

    @pytest.mark.asyncio
    async def test_invoke_agent_passes_thread_id_config(self) -> None:
        from inkflow.domain.services.agentic_writer_service import AgenticWriterService

        agent = AsyncMock()
        agent.invoke.return_value = {"messages": []}
        svc = AgenticWriterService(
            agent_factory=lambda req: agent,
            draft_service=AsyncMock(),
            audit_service=AsyncMock(),
            run_repo=AsyncMock(),
        )
        await svc._invoke_agent(agent, [{"type": "user", "content": "hi"}], thread_id=THREAD_ID)
        args, kwargs = agent.invoke.call_args
        cfg = kwargs.get("config") or (args[1] if len(args) > 1 else None)
        assert cfg == {"configurable": {"thread_id": THREAD_ID}}


class TestDeepAgentInvokeAdapterThreadIdFallback:
    """契约 3: DeepAgentInvokeAdapter.invoke 未显式传 config → 自动补 thread_id。"""

    @pytest.mark.asyncio
    async def test_invoke_without_config_auto_fills_thread_id(self) -> None:
        from inkflow.infrastructure.agent.agentic_writer import DeepAgentInvokeAdapter

        inner = MagicMock()
        inner.invoke.return_value = {"messages": []}
        adapter = DeepAgentInvokeAdapter(inner)
        result = await adapter.invoke([{"type": "user", "content": "hi"}])
        assert isinstance(result, dict)
        args, kwargs = inner.invoke.call_args
        cfg = kwargs.get("config") or (args[1] if len(args) > 1 else None)
        assert cfg is not None, "config missing from inner.invoke"
        assert cfg["configurable"]["thread_id"], "thread_id must be auto-filled"

    @pytest.mark.asyncio
    async def test_invoke_with_explicit_config_preserved(self) -> None:
        """显式传 config 时原样透传（不覆盖调用方 thread_id）。"""
        from inkflow.infrastructure.agent.agentic_writer import DeepAgentInvokeAdapter

        inner = MagicMock()
        inner.invoke.return_value = {"messages": []}
        adapter = DeepAgentInvokeAdapter(inner)
        explicit = {"configurable": {"thread_id": "explicit-1"}}
        await adapter.invoke([{"type": "user", "content": "hi"}], config=explicit)
        args, kwargs = inner.invoke.call_args
        cfg = kwargs.get("config") or (args[1] if len(args) > 1 else None)
        assert cfg == explicit
