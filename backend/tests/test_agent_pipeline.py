"""Agent 管线领域模型 + 校验逻辑测试 (spec §2, §9.1)."""

import uuid

import pytest
from pydantic import ValidationError

from inkflow.domain.models import PipelineConfig, PipelineExecuteRequest, RoleOverride
from inkflow.domain.ports import AgentRole, PipelineError, PipelineStage, StageStatus


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
