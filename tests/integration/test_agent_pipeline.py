"""Agent 管线领域模型 + 校验逻辑测试 (spec §2, §9.1)."""

import uuid

import pytest
from pydantic import ValidationError

from inkflow.domain.models import PipelineConfig, PipelineExecuteRequest, RoleOverride
from inkflow.domain.ports import AgentRole, PipelineError, PipelineStage, StageStatus

pytestmark = pytest.mark.asyncio  # 集成测试在 tests/ 下需显式 asyncio mark


def _make_role(role_id: str = "architect", **kwargs) -> AgentRole:
    """构造一个合法的 AgentRole（默认值 + 覆盖项）。"""
    role = {"id": role_id, "name": "架构师", "system_prompt": "你是一位资深小说架构师"}
    role.update(kwargs)
    return AgentRole(**role)


def _make_stage(stage_id: str = "outline", **kwargs) -> PipelineStage:
    """构造一个合法的 PipelineStage（默认值 + 覆盖项）。"""
    stage = {"id": stage_id, "name": "大纲", "agent": _make_role()}
    stage.update(kwargs)
    return PipelineStage(**stage)


# ── AgentRole (§2.2) ──────────────────────────────────────────────────


def test_agent_role_defaults():
    """AgentRole 默认值: model='openai/gpt-4o', temperature=0.7, max_tokens=None."""
    role = _make_role()
    assert role.model == "openai/gpt-4o"
    assert role.temperature == 0.7
    assert role.max_tokens is None


def test_agent_role_temperature_range():
    """temperature 超出 [0, 2] → ValidationError."""
    with pytest.raises(ValidationError):
        _make_role(temperature=2.5)
    with pytest.raises(ValidationError):
        _make_role(temperature=-0.1)


# ── PipelineStage (§2.3) ──────────────────────────────────────────────


def test_pipeline_stage_defaults():
    """PipelineStage 默认值: input_from/output_to=[], max_retries=3, required=True."""
    stage = _make_stage()
    assert stage.input_from == []
    assert stage.output_to == []
    assert stage.max_retries == 3
    assert stage.required is True


# ── PipelineConfig (§2.7) ─────────────────────────────────────────────


def test_pipeline_config_empty_stages():
    """stages=[] → ValidationError."""
    with pytest.raises(ValidationError):
        PipelineConfig(name="write_chapter", stages=[])


def test_pipeline_config_stage_id_duplicate():
    """重复 stage id → ValidationError."""
    with pytest.raises(ValidationError):
        PipelineConfig(
            name="write_chapter",
            stages=[_make_stage("outline"), _make_stage("outline")],
        )


def test_pipeline_config_source_field():
    """source 只能是 'builtin' 或 'yaml'."""
    config = PipelineConfig(name="write_chapter", stages=[_make_stage()])
    assert config.source == "builtin"
    yaml_config = PipelineConfig(name="my-dag", stages=[_make_stage()], source="yaml")
    assert yaml_config.source == "yaml"
    with pytest.raises(ValidationError):
        PipelineConfig(name="bad", stages=[_make_stage()], source="xml")


# ── StageStatus 枚举 (§2.1) ───────────────────────────────────────────


def test_stage_result_status_enum():
    """StageStatus 枚举值完整 (pending/running/completed/failed/skipped)."""
    assert {s.value for s in StageStatus} == {
        "pending",
        "running",
        "completed",
        "failed",
        "skipped",
    }


# ── PipelineError (§2.8) ──────────────────────────────────────────────


def test_pipeline_error_can_be_raised():
    """PipelineError 可正常 raise/catch."""
    with pytest.raises(PipelineError):
        raise PipelineError("管线执行失败")


# ── PipelineExecuteRequest (§3.2) ─────────────────────────────────────


def test_pipeline_execute_request_defaults():
    """默认值: pipeline='builtin:write_chapter', chapter_id=None,
    variables={}, role_overrides=None.
    """
    req = PipelineExecuteRequest(project_id=uuid.uuid4())
    assert req.pipeline == "builtin:write_chapter"
    assert req.chapter_id is None
    assert req.variables == {}
    assert req.role_overrides is None


def test_role_override_all_fields_optional():
    """RoleOverride 三个字段全可省略."""
    override = RoleOverride()
    assert override.prompt is None
    assert override.model is None
    assert override.temperature is None


# ── ORM + ExecutionStore ─────────────────────────────────────────────


class TestAgentExecutionORM:
    async def test_create_execution_record(self, db_session):
        """创建 AgentExecutionORM 记录并持久化。"""
        from inkflow.infrastructure.database.models.agent import AgentExecutionORM

        execution = AgentExecutionORM(
            pipeline="builtin:write_chapter",
            project_id=str(uuid.uuid4()),
            chapter_id=str(uuid.uuid4()),
        )
        db_session.add(execution)
        await db_session.commit()
        await db_session.refresh(execution)

        assert execution.id is not None
        assert execution.pipeline == "builtin:write_chapter"
        assert execution.project_id is not None
        assert execution.chapter_id is not None
        assert execution.created_at is not None

    async def test_execution_fields_default(self, db_session):
        """默认字段: status=pending, final_output='', error=''。"""
        from inkflow.infrastructure.database.models.agent import AgentExecutionORM

        execution = AgentExecutionORM(
            pipeline="builtin:write_chapter",
            project_id=str(uuid.uuid4()),
        )
        db_session.add(execution)
        await db_session.commit()
        await db_session.refresh(execution)

        assert execution.status == "pending"
        assert execution.final_output == ""
        assert execution.error == ""
        assert execution.stages == []
        assert execution.total_duration_ms == 0

    async def test_execution_stages_json(self, db_session):
        """stages 字段为 JSON 列表，存储各阶段快照。"""
        from inkflow.infrastructure.database.models.agent import AgentExecutionORM

        stages = [
            {
                "stage_id": "outline",
                "status": "completed",
                "output": "大纲内容",
                "duration_ms": 120,
            },
            {
                "stage_id": "chapter_write",
                "status": "pending",
                "output": "",
                "duration_ms": 0,
            },
        ]
        execution = AgentExecutionORM(
            pipeline="builtin:write_chapter",
            project_id=str(uuid.uuid4()),
            stages=stages,
        )
        db_session.add(execution)
        await db_session.commit()
        await db_session.refresh(execution)

        assert isinstance(execution.stages, list)
        assert execution.stages == stages


class TestAgentStageResultORM:
    async def test_create_stage_result(self, db_session):
        """创建 AgentStageResultORM 记录。"""
        from inkflow.infrastructure.database.models.agent import (
            AgentExecutionORM,
            AgentStageResultORM,
        )

        execution = AgentExecutionORM(
            pipeline="builtin:write_chapter",
            project_id=str(uuid.uuid4()),
        )
        db_session.add(execution)
        await db_session.commit()
        await db_session.refresh(execution)

        stage_result = AgentStageResultORM(
            execution_id=execution.id,
            stage_id="outline",
            status="completed",
            output="大纲内容",
            duration_ms=120,
        )
        db_session.add(stage_result)
        await db_session.commit()
        await db_session.refresh(stage_result)

        assert stage_result.id is not None
        assert stage_result.execution_id == execution.id
        assert stage_result.stage_id == "outline"
        assert stage_result.status == "completed"
        assert stage_result.output == "大纲内容"
        assert stage_result.retry_count == 0
        assert stage_result.duration_ms == 120

    async def test_stage_result_fk_to_execution(self, db_session):
        """stage result 的 execution_id 外键关联到 execution。"""
        from sqlalchemy import select

        from inkflow.infrastructure.database.models.agent import (
            AgentExecutionORM,
            AgentStageResultORM,
        )

        execution = AgentExecutionORM(
            pipeline="builtin:write_chapter",
            project_id=str(uuid.uuid4()),
        )
        db_session.add(execution)
        await db_session.commit()
        await db_session.refresh(execution)

        stage_result = AgentStageResultORM(
            execution_id=execution.id,
            stage_id="style_review",
            status="running",
        )
        db_session.add(stage_result)
        await db_session.commit()

        result = await db_session.execute(
            select(AgentStageResultORM).where(
                AgentStageResultORM.execution_id == execution.id
            )
        )
        loaded = result.scalar_one()
        assert loaded.id == stage_result.id
        assert loaded.execution_id == execution.id
        assert loaded.stage_id == "style_review"
        assert loaded.status == "running"


class TestExecutionStore:
    async def test_create_and_get_execution(self, db_session):
        """create_execution → get_execution 可查询。"""
        from inkflow.infrastructure.agent import ExecutionStore

        store = ExecutionStore(db_session)
        chapter_id = str(uuid.uuid4())
        execution = await store.create_execution(
            pipeline="builtin:write_chapter",
            project_id=str(uuid.uuid4()),
            chapter_id=chapter_id,
        )

        loaded = await store.get_execution(execution.id)
        assert loaded is not None
        assert loaded.id == execution.id
        assert loaded.pipeline == "builtin:write_chapter"
        assert loaded.chapter_id == chapter_id
        assert loaded.status == "pending"

    async def test_update_stage_snapshot(self, db_session):
        """update_stage 更新 stages JSON 字段。"""
        from inkflow.infrastructure.agent import ExecutionStore

        store = ExecutionStore(db_session)
        execution = await store.create_execution(
            pipeline="builtin:write_chapter",
            project_id=str(uuid.uuid4()),
        )

        stages = [
            {
                "stage_id": "outline",
                "status": "completed",
                "output": "大纲",
                "duration_ms": 100,
            }
        ]
        await store.update_stages(
            execution_id=execution.id,
            stages=stages,
            status="completed",
            final_output="章节正文",
            total_duration_ms=100,
        )

        loaded = await store.get_execution(execution.id)
        assert loaded is not None
        assert loaded.stages == stages
        assert loaded.status == "completed"
        assert loaded.final_output == "章节正文"
        assert loaded.total_duration_ms == 100

    async def test_list_executions_by_project(self, db_session):
        """按 project_id 过滤 + 分页。"""
        from inkflow.infrastructure.agent import ExecutionStore

        store = ExecutionStore(db_session)
        project_id = str(uuid.uuid4())
        other_project_id = str(uuid.uuid4())
        for _ in range(3):
            await store.create_execution(
                pipeline="builtin:write_chapter", project_id=project_id
            )
        await store.create_execution(
            pipeline="builtin:write_chapter", project_id=other_project_id
        )

        executions, total = await store.list_executions(project_id=project_id, limit=2)

        assert total == 3
        assert len(executions) == 2
        assert all(e.project_id == project_id for e in executions)

    async def test_get_nonexistent_returns_none(self, db_session):
        """查询不存在的 execution → None。"""
        from inkflow.infrastructure.agent import ExecutionStore

        store = ExecutionStore(db_session)
        loaded = await store.get_execution(str(uuid.uuid4()))
        assert loaded is None
