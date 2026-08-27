"""#708 coverage 补测 — agent_service 未覆盖分支（纯函数 + 服务层直调）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.project import AgentRelation
from inkflow.domain.ports.agent_pipeline import (
    PipelineContext,
    PipelineResult,
    StageResult,
    StageStatus,
)
from inkflow.domain.services.agent_service import (
    AgentService,
    _apply_agent_relations,
    _build_relations_snapshot,
    _has_cycle,
    _transitive_upstream,
)
from inkflow.infrastructure.agent.pipeline_templates import get_template

PROJECT_ID = "6f5c1f9e-9a4e-4f2e-8f3a-1b2c3d4e5f6a"

F_ARCHITECT = "agent_architect"
ALL_ENABLED = {F_ARCHITECT, "agent_writer"}


def _rel(from_field: str, to_field: str, rel_type: str = "sequential") -> AgentRelation:
    """构造 AgentRelation（字段名形态）。"""
    return AgentRelation(from_=from_field, to=to_field, type=rel_type)


def _make_svc(**kw: object) -> AgentService:
    """最小构造 AgentService：pipeline/db_session 占位 + 全 mock repos。"""
    base = {
        "pipeline": AsyncMock(),
        "db_session": AsyncMock(),
        "store": AsyncMock(),
        "project_repo": AsyncMock(),
    }
    base.update(kw)
    return AgentService(**base)


class TestPureFunctions:
    """模块级纯函数缺口分支。"""

    def test_has_cycle_skips_edge_with_unknown_node(self) -> None:
        """边引用未知节点 → 跳过该边（185->184 False 分支）。"""
        assert _has_cycle({"a", "b"}, [("a", "ghost")]) is False

    def test_transitive_upstream_skips_missing_stage(self) -> None:
        """栈内 stage_id 不在 by_id → continue（211->205）。"""
        stages = [
            SimpleNamespace(id="a", input_from=[]),
            SimpleNamespace(id="b", input_from=["ghost", "a"]),
        ]
        result = _transitive_upstream("b", stages)
        assert result == {"a", "ghost"}

    def test_relations_snapshot_non_conditional(self) -> None:
        """非 conditional 关系 → 直接 append（358->365 False 分支）。"""
        snapshot = _build_relations_snapshot([_rel("agent_a", "agent_b")], [])
        assert snapshot == [{"from": "a", "to": "b", "type": "sequential"}]

    def test_apply_relations_to_disabled_role_falls_back(self) -> None:
        """rel.to 引用未启用角色 → warning + 原样返回（248->249 + 249-250 行）。"""
        stages = list(get_template("builtin:write_chapter").stages)
        result, conditional_edges = _apply_agent_relations(
            stages, [_rel(F_ARCHITECT, "agent_ghost")], ALL_ENABLED
        )
        assert result is stages
        assert conditional_edges == []


class TestSettingContextGaps:
    """_assemble_setting_context 项目层缺口。"""

    @pytest.mark.asyncio
    async def test_setting_project_missing_returns_vars(self) -> None:
        """项目不存在 → 原样返回 variables（737->738）。"""
        svc = _make_svc(
            character_repo=AsyncMock(),
            world_repo=AsyncMock(),
            outline_repo=AsyncMock(),
        )
        svc._project_repo.get = AsyncMock(return_value=None)
        variables = {"topic": "x"}

        result = await svc._assemble_setting_context(PROJECT_ID, variables)

        assert result is variables

    @pytest.mark.asyncio
    async def test_setting_project_lookup_failure_falls_back(self) -> None:
        """项目查询异常 → warning 回退请求变量（767-768 行）。"""
        svc = _make_svc(
            character_repo=AsyncMock(),
            world_repo=AsyncMock(),
            outline_repo=AsyncMock(),
        )
        svc._project_repo.get = AsyncMock(side_effect=RuntimeError("db down"))
        variables = {"topic": "x"}

        result = await svc._assemble_setting_context(PROJECT_ID, variables)

        assert result is variables


class TestRunPipelineTrace:
    """_run_pipeline trace 透传。"""

    @pytest.mark.asyncio
    async def test_run_pipeline_passes_trace(self) -> None:
        """结果含 trace → run_kwargs 透传 trace（700->701）。"""
        svc = _make_svc()
        pipeline = AsyncMock()
        result = PipelineResult(
            stages=[StageResult(stage_id="writer", status=StageStatus.COMPLETED, output="正文")],
            final_output="正文",
            status=StageStatus.COMPLETED,
            total_duration_ms=1,
            trace=[{"node": "writer"}],
        )
        pipeline.execute = AsyncMock(return_value=result)
        svc._pipeline = pipeline
        svc._inject_context = AsyncMock()

        await svc._run_pipeline("exec-1", [], PipelineContext(project_id="p"))

        update = svc._store.update_stages
        update.assert_awaited_once()
        assert update.await_args.kwargs["trace"] == [{"node": "writer"}]


class TestConfirmTrace:
    """confirm_execution trace 透传。"""

    @pytest.mark.asyncio
    async def test_confirm_resume_passes_trace(self) -> None:
        """resume 结果含 trace → confirm_kwargs 透传（544->545）。"""
        store = AsyncMock()
        store.get_execution = AsyncMock(
            return_value=SimpleNamespace(status="waiting_hitl", hitl_payload={})
        )
        supervisor = AsyncMock()
        result = PipelineResult(
            stages=[StageResult(stage_id="writer", status=StageStatus.COMPLETED, output="正文")],
            final_output="正文",
            status=StageStatus.COMPLETED,
            total_duration_ms=1,
            trace=[{"node": "writer"}],
        )
        supervisor.resume = AsyncMock(return_value=result)
        svc = _make_svc(store=store, supervisor_pipeline=supervisor)

        out = await svc.confirm_execution("exec-1", approved=True)

        assert out["status"] == "completed"
        store.update_stages.assert_awaited_once()
        assert store.update_stages.await_args.kwargs["trace"] == [{"node": "writer"}]
