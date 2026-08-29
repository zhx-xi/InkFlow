"""#766 阶段③ agent 链工具 RED 契约测试 — build_agent_chain_tools 注册 + 执行信封.

依据 specs/f26-agent-tools/spec.md §7.1-§7.2 + ADR-043 D5（agent 链改删不给 AI，
只给「执行/调用」）。镜像 test_writing_tools 形态。锁定契约:
1. build_agent_chain_tools(deps) 返回 [agent_run, agent_call]（顺序固定）。
2. agent_run: 包装 agent_service.execute(PipelineExecuteRequest)——成功
   {"ok": True, "execution_id": "<id>", "status": "pending"}；
   service 抛异常 → {"ok": False, "error": "..."}。
3. project_id 由 deps.expected_project_id 绑定（schema 不含 project_id）——
   execute 收到的 request.project_id == 绑定值（LLM 不自报，防编造孤儿执行）。
4. agent_call: 包装 agent_entity_service.get(agent_id) 读配置 + deps.run_agent
   （单 agent 执行钩子，Q1=A 拍板）——成功 {"ok": True, "result": "<输出文本>"}；
   get 抛异常 → {"ok": False, "error": "..."}。
5. agent 链配置修改/删除工具（roles/order/relations CRUD）不注册（D5）。

RED 形态: agent_chain_tools.py 不存在 → 收集期 ModuleNotFoundError。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.infrastructure.agent.tools.agent_chain_tools import (
    AgentChainToolDeps,
    build_agent_chain_tools,
)

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")


def _make_deps() -> AgentChainToolDeps:
    """构造 agent 链工具依赖：agent_service/agent_entity_service 用 MagicMock。"""
    return AgentChainToolDeps(
        agent_service=MagicMock(),
        agent_entity_service=MagicMock(),
        run_agent=AsyncMock(return_value=""),
        expected_project_id=PROJECT_ID,
    )


class TestBuildAgentChainTools:
    """build_agent_chain_tools 注册 2 个 agent 链工具（顺序固定）。"""

    def test_registers_two_tools(self) -> None:
        tools = build_agent_chain_tools(_make_deps())
        assert [t.spec.name for t in tools] == ["agent_run", "agent_call"]

    def test_tool_specs_have_input_schema(self) -> None:
        for t in build_agent_chain_tools(_make_deps()):
            assert isinstance(t.spec.input_schema, dict)
            assert "type" in t.spec.input_schema

    def test_schema_excludes_project_id(self) -> None:
        """project_id 由装配期绑定（deps.expected_project_id），不出现在 schema。"""
        for t in build_agent_chain_tools(_make_deps()):
            assert "project_id" not in t.spec.input_schema.get("properties", {})

    def test_no_config_mutation_tools(self) -> None:
        """D5：agent 链配置修改/删除工具不给 AI——不注册任何 CRUD 工具。"""
        tools = build_agent_chain_tools(_make_deps())
        names = [t.spec.name for t in tools]
        assert names == ["agent_run", "agent_call"]


class TestAgentRun:
    """agent_run：启动一次 agent 链管线执行。"""

    @pytest.mark.asyncio
    async def test_success_envelope(self) -> None:
        deps = _make_deps()
        deps.agent_service.execute = AsyncMock(
            return_value={
                "execution_id": "run-1",
                "pipeline": "builtin:write_chapter",
                "project_id": str(PROJECT_ID),
                "status": "pending",
                "created_at": "2026-08-30T00:00:00Z",
                "mode": "static",
            }
        )
        tools = {t.spec.name: t for t in build_agent_chain_tools(deps)}
        result = json.loads(await tools["agent_run"].func(pipeline="builtin:write_chapter"))
        assert result["ok"] is True
        assert result["execution_id"] == "run-1"
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_binds_project_id(self) -> None:
        """agent_run 恒用绑定 project_id（LLM 不自报）。"""
        deps = _make_deps()
        deps.agent_service.execute = AsyncMock(
            return_value={"execution_id": "r", "status": "pending"}
        )
        tools = {t.spec.name: t for t in build_agent_chain_tools(deps)}
        await tools["agent_run"].func()
        deps.agent_service.execute.assert_awaited_once()
        request = deps.agent_service.execute.await_args.args[0]
        assert str(request.project_id) == str(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_failure_envelope(self) -> None:
        deps = _make_deps()
        deps.agent_service.execute = AsyncMock(side_effect=ValueError("管线不存在"))
        tools = {t.spec.name: t for t in build_agent_chain_tools(deps)}
        result = json.loads(await tools["agent_run"].func())
        assert result["ok"] is False
        assert "管线不存在" in result["error"]


class TestAgentCall:
    """agent_call：读 agent 配置 + 单 agent 执行（Q1=A）。"""

    @pytest.mark.asyncio
    async def test_success_envelope(self) -> None:
        deps = _make_deps()
        deps.agent_entity_service.get = AsyncMock(return_value=SimpleNamespace(id=1, name="编辑"))
        deps.run_agent = AsyncMock(return_value="润色完成")
        tools = {t.spec.name: t for t in build_agent_chain_tools(deps)}
        result = json.loads(await tools["agent_call"].func(agent_id="1", input="润色这段"))
        assert result["ok"] is True
        assert result["result"] == "润色完成"

    @pytest.mark.asyncio
    async def test_get_then_run_agent(self) -> None:
        """执行流：get(agent_id) 读配置 → run_agent(agent, input) 单 agent 执行。"""
        deps = _make_deps()
        agent = SimpleNamespace(id=1, name="编辑")
        deps.agent_entity_service.get = AsyncMock(return_value=agent)
        deps.run_agent = AsyncMock(return_value="完成")
        tools = {t.spec.name: t for t in build_agent_chain_tools(deps)}
        await tools["agent_call"].func(agent_id="1", input="润色这段")
        deps.agent_entity_service.get.assert_awaited_once()
        assert str(deps.agent_entity_service.get.await_args.args[0]) == "1"
        deps.run_agent.assert_awaited_once()
        assert deps.run_agent.await_args.args[0] is agent
        assert deps.run_agent.await_args.args[1] == "润色这段"

    @pytest.mark.asyncio
    async def test_failure_envelope(self) -> None:
        deps = _make_deps()
        deps.agent_entity_service.get = AsyncMock(side_effect=ValueError("agent 不存在"))
        tools = {t.spec.name: t for t in build_agent_chain_tools(deps)}
        result = json.loads(await tools["agent_call"].func(agent_id="999", input="x"))
        assert result["ok"] is False
        assert "agent 不存在" in result["error"]
