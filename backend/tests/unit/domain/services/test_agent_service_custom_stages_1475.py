"""#1475 自定义 stage 管线 —— RED 契约（spec f42 §5.8 / §4.1 / §13 M10-M11，v1.6）。

问题（#1475 根因，spec §1.1 ⑫）：`agent run --pipeline` 只认内置 4 条模板 id
（`pipeline_templates._BUILDERS`）——内置 6 Agent 中世界观顾问（`worldview`）/
润色师（`polisher`）**无任何管线可执行**；且 `AgentTemplate` 只覆盖角色模型/温度，
**不改变阶段拓扑**（6 角色模板挂项目后 stages 仍 4 个）。

契约（本文件锁定，实现者以本文件为准）：

1. `_build_custom_stages(role_keys, agents_by_role) -> list[PipelineStage]`
   - role_key 序列 → **顺序单链**：第 i 个 `input_from=[第 i-1 个 id]`、
     `output_to=[第 i+1 个 id]`；首 stage `input_from=[]`、末 stage `output_to=[]`。
   - `stage.id = role_key`；`stage.name` / `stage.agent.system_prompt` 取 **Agent 真源**。
   - 未知 role_key（真源无该 role_key）→ `ValueError("未知 stage 角色: <key>")`。
2. `PipelineExecuteRequest` 增 `stages: list[str] | None` 与
   `pipeline_config: PipelineConfig | None`（互斥；仅 `mode="static"`；`stages` 非空）。
3. `_build_pipeline_context` 自定义分派：跳过内置模板查找 → 拓扑构造 → 真实引擎
   `validate` 同步校验（非空 errors → `AgentServiceError("自定义管线配置无效: …")`）
   → `_merge_role_configs` → `_attach_agent_skills`；**旁路** `_apply_agent_order` /
   `agent_relations`（显式拓扑优先）。
4. **零回归**：内置 4 条管线 stage 序列逐条不变（当前 PASS，必须守住）。

RED 形态（实现前实测）：`_build_custom_stages` 不存在 → AttributeError；
`PipelineExecuteRequest(stages=...)` 字段被忽略 → AttributeError。
"""

from __future__ import annotations

import importlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from inkflow.domain.models.agent_pipeline import (
    PipelineConfig,
    PipelineExecuteRequest,
)
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.ports.agent_pipeline import AgentRole, PipelineStage
from inkflow.domain.services import agent_service as agent_service_module
from inkflow.domain.services.agent_service import AgentService, AgentServiceError

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")

# 自定义 stage 用到的两个「无内置管线」角色（#1475 需求 1）
CUSTOM_ROLE_KEYS = ["worldview", "polisher"]


# ── 测试替身 ────────────────────────────────────────────────


def _make_project(config: ProjectConfig | None = None) -> Project:
    return Project(
        id=PROJECT_ID,
        name="测试项目",
        tags=["玄幻"],
        language="zh-CN",
        target_words=100000,
        config=config or ProjectConfig(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_agent(role_key: str, skill_ids: list[str] | None = None) -> SimpleNamespace:
    """Agent 真源替身（镜像 AgentRepository.list() 领域对象）。"""
    return SimpleNamespace(
        role_key=role_key,
        name=f"{role_key}-显示名",
        system_prompt=f"base::{role_key}",
        skill_ids=list(skill_ids or []),
    )


class _StubPipeline:
    """管线引擎替身：记录 validate 收到的拓扑 + 可配置返回的 errors。"""

    def __init__(self, errors: list[str] | None = None) -> None:
        self._errors = list(errors or [])
        self.validated: list[list[PipelineStage]] = []

    def validate(self, stages) -> list[str]:
        self.validated.append(list(stages))
        return list(self._errors)


class _MockProjectRepo:
    def __init__(self, project: Project | None) -> None:
        self._project = project

    async def get(self, project_id) -> Project | None:
        return self._project


def _build_svc(
    pipeline=None,
    agent_repo=None,
    project: Project | None = None,
) -> AgentService:
    return AgentService(
        pipeline=pipeline if pipeline is not None else _StubPipeline(),
        db_session=None,
        store=MagicMock(),
        project_repo=_MockProjectRepo(project or _make_project()),
        chapter_repo=MagicMock(),
        agent_repo=agent_repo,
    )


def _agent_repo(agents: list[SimpleNamespace]) -> MagicMock:
    repo = MagicMock()
    repo.list = AsyncMock(return_value=list(agents))
    return repo


def _custom_stage(role_key: str, upstream: str | None = None, downstream: str | None = None):
    """构造 pipeline_config 用的 PipelineStage（用户显式给定 prompt）。"""
    return PipelineStage(
        id=role_key,
        name=f"{role_key} 阶段",
        agent=AgentRole(
            id=role_key,
            name=f"{role_key} 阶段",
            system_prompt=f"yaml-prompt::{role_key}",
        ),
        input_from=[upstream] if upstream else [],
        output_to=[downstream] if downstream else [],
    )


def _patch_skills_root(monkeypatch, tmp_path) -> None:
    cfg_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(cfg_mod.config, "data_dir", tmp_path)


# ── 1. `_build_custom_stages` 纯函数契约 ─────────────────────


class TestBuildCustomStages:
    """`_build_custom_stages`：role_key 序列 → 顺序单链（spec §5.8.2.1）。"""

    def test_sequential_chain_edges(self) -> None:
        """三元素链：首 stage 无上游、末 stage 无下游，中间 i↔i-1/i+1。"""
        build = agent_service_module._build_custom_stages
        agents = {key: _make_agent(key) for key in ["worldview", "writer", "polisher"]}

        stages = build(["worldview", "writer", "polisher"], agents)

        assert [s.id for s in stages] == ["worldview", "writer", "polisher"]
        assert stages[0].input_from == []
        assert stages[0].output_to == ["writer"]
        assert stages[1].input_from == ["worldview"]
        assert stages[1].output_to == ["polisher"]
        assert stages[2].input_from == ["writer"]
        assert stages[2].output_to == []

    def test_single_role_is_both_entry_and_terminal(self) -> None:
        """单角色链：input_from/output_to 均为空（既是入口也是终点）。"""
        build = agent_service_module._build_custom_stages
        stages = build(["polisher"], {"polisher": _make_agent("polisher")})

        assert len(stages) == 1
        assert stages[0].input_from == []
        assert stages[0].output_to == []

    def test_name_and_prompt_from_agent_source(self) -> None:
        """stage.name / agent.system_prompt 取 Agent 真源（不在函数内硬编码）。"""
        build = agent_service_module._build_custom_stages
        stages = build(CUSTOM_ROLE_KEYS, {key: _make_agent(key) for key in CUSTOM_ROLE_KEYS})

        assert stages[0].name == "worldview-显示名"
        assert stages[0].agent.system_prompt == "base::worldview"
        assert stages[0].agent.temperature is None  # 温度由装配链决定，不在本函数硬编码

    def test_unknown_role_key_raises_value_error(self) -> None:
        """未知 role_key → ValueError（显式通道不静默跳过）。"""
        build = agent_service_module._build_custom_stages
        with pytest.raises(ValueError, match="未知 stage 角色: ghost"):
            build(["ghost"], {"worldview": _make_agent("worldview")})

    def test_name_falls_back_to_role_key_when_agent_name_blank(self) -> None:
        """Agent 真源 name 为空 → stage/agent 显示名回退 role_key。"""
        build = agent_service_module._build_custom_stages
        agents = {"polisher": SimpleNamespace(role_key="polisher", name="", system_prompt="p")}

        stages = build(["polisher"], agents)

        assert stages[0].name == "polisher"
        assert stages[0].agent.name == "polisher"

    def test_built_chain_passes_real_engine_validate(self) -> None:
        """顺序单链交给真实引擎 validate → 无错误（入口/终点/引用/环全通过）。"""
        from inkflow.infrastructure.agent.langgraph_pipeline import LangGraphAgentPipeline

        build = agent_service_module._build_custom_stages
        stages = build(CUSTOM_ROLE_KEYS, {key: _make_agent(key) for key in CUSTOM_ROLE_KEYS})

        engine = LangGraphAgentPipeline(llm_client=MagicMock())
        assert engine.validate(stages) == []


# ── 2. `PipelineExecuteRequest` 契约（spec §5.8.1） ──────────


class TestCustomPipelineRequestContract:
    """DTO 两字段 + 三条约束（互斥 / static-only / 非空）。"""

    def test_stages_field_accepted(self) -> None:
        req = PipelineExecuteRequest(
            project_id=PROJECT_ID, pipeline="worldview,polisher", stages=list(CUSTOM_ROLE_KEYS)
        )

        assert req.stages == CUSTOM_ROLE_KEYS
        assert req.pipeline_config is None

    def test_pipeline_config_field_accepted(self) -> None:
        config = PipelineConfig(
            name="世界观润色链",
            stages=[
                _custom_stage("worldview", downstream="polisher"),
                _custom_stage("polisher", upstream="worldview"),
            ],
            source="yaml",
        )
        req = PipelineExecuteRequest(
            project_id=PROJECT_ID, pipeline="chain.yaml", pipeline_config=config
        )

        assert req.pipeline_config is not None
        assert req.pipeline_config.name == "世界观润色链"
        assert req.stages is None

    def test_builtin_request_leaves_both_none(self) -> None:
        """内置路径零变化：两字段均缺省 None。"""
        req = PipelineExecuteRequest(project_id=PROJECT_ID, pipeline="builtin:write_chapter")

        assert req.stages is None
        assert req.pipeline_config is None

    def test_mutually_exclusive_422_shape(self) -> None:
        config = PipelineConfig(name="c", stages=[_custom_stage("writer")], source="yaml")
        with pytest.raises(ValidationError, match="stages 与 pipeline_config 互斥"):
            PipelineExecuteRequest(
                project_id=PROJECT_ID,
                pipeline="mixed",
                stages=["writer"],
                pipeline_config=config,
            )

    def test_supervisor_mode_rejected(self) -> None:
        with pytest.raises(ValidationError, match="自定义 stage 仅支持 static 模式"):
            PipelineExecuteRequest(
                project_id=PROJECT_ID,
                pipeline="worldview,polisher",
                stages=list(CUSTOM_ROLE_KEYS),
                mode="supervisor",
            )

    def test_empty_stages_rejected(self) -> None:
        with pytest.raises(ValidationError, match="stages 不能为空"):
            PipelineExecuteRequest(project_id=PROJECT_ID, pipeline=",", stages=[])

    def test_blank_stage_element_rejected(self) -> None:
        """元素为空白串 → 同「stages 不能为空」（不静默丢弃）。"""
        with pytest.raises(ValidationError, match="stages 不能为空"):
            PipelineExecuteRequest(project_id=PROJECT_ID, pipeline="x", stages=["writer", "   "])


# ── 3. `_build_pipeline_context` 自定义分派（spec §5.8.2/5.8.3） ──


class TestCustomPipelineContext:
    """自定义通道：模板查找跳过 + 拓扑构造 + 校验 + 旁路 agent_order。"""

    async def test_stages_form_builds_custom_topology(self, monkeypatch, tmp_path) -> None:
        """`stages` 形态：pipeline 非内置 id 也成立（不查内置模板表）。

        skills_root 隔离到空目录：`_attach_agent_skills` 会把「未被任何 Agent 挂载」
        的 skill 当通用注入，本机真实 data dir 会污染 prompt 精确断言（CI 无此目录，
        本地会假红）——断言意图 = 「Agent 真源 prompt 被原样采用」。
        """
        _patch_skills_root(monkeypatch, tmp_path)
        svc = _build_svc(agent_repo=_agent_repo([_make_agent(k) for k in CUSTOM_ROLE_KEYS]))
        request = PipelineExecuteRequest(
            project_id=PROJECT_ID, pipeline="worldview,polisher", stages=list(CUSTOM_ROLE_KEYS)
        )

        stages, *_ = await svc._build_pipeline_context(request)

        assert [s.id for s in stages] == CUSTOM_ROLE_KEYS
        assert [s.agent.system_prompt for s in stages] == ["base::worldview", "base::polisher"]

    async def test_stages_form_bypasses_project_agent_order(self) -> None:
        """项目配置驱动模式（agent_order 非空）下，显式拓扑仍原样执行（旁路）。"""
        project = _make_project(
            ProjectConfig(agent_order=[["agent_writer"]], agent_writer="zhipu/glm-4.5")
        )
        svc = _build_svc(
            project=project, agent_repo=_agent_repo([_make_agent(k) for k in CUSTOM_ROLE_KEYS])
        )
        request = PipelineExecuteRequest(
            project_id=PROJECT_ID, pipeline="worldview,polisher", stages=list(CUSTOM_ROLE_KEYS)
        )

        stages, *_ = await svc._build_pipeline_context(request)

        assert [s.id for s in stages] == CUSTOM_ROLE_KEYS  # 未被 agent_order 摘除/重排

    async def test_stages_form_unknown_role_raises_service_error(self) -> None:
        """未知 role_key → AgentServiceError「未知 stage 角色: xxx」（API 映射 422）。"""
        svc = _build_svc(agent_repo=_agent_repo([_make_agent("writer")]))
        request = PipelineExecuteRequest(project_id=PROJECT_ID, pipeline="ghost", stages=["ghost"])

        with pytest.raises(AgentServiceError, match="未知 stage 角色: ghost"):
            await svc._build_pipeline_context(request)

    async def test_pipeline_config_form_used_verbatim(self) -> None:
        """`pipeline_config` 形态：用户显式 stage/agent 原样采用（含 prompt）。"""
        config = PipelineConfig(
            name="YAML 链",
            stages=[
                _custom_stage("worldview", downstream="polisher"),
                _custom_stage("polisher", upstream="worldview"),
            ],
            source="yaml",
        )
        svc = _build_svc(agent_repo=_agent_repo([]))
        request = PipelineExecuteRequest(
            project_id=PROJECT_ID, pipeline="chain.yaml", pipeline_config=config
        )

        stages, *_ = await svc._build_pipeline_context(request)

        assert [s.id for s in stages] == CUSTOM_ROLE_KEYS
        assert stages[0].agent.system_prompt == "yaml-prompt::worldview"
        assert stages[0].output_to == ["polisher"]

    async def test_invalid_custom_topology_rejected_before_execution(self) -> None:
        """拓扑非法（引擎 validate 报错）→ AgentServiceError（同步拒绝，不落失败记录）。"""
        pipeline = _StubPipeline(errors=["阶段 'a' 引用了不存在的上游阶段 'b'"])
        config = PipelineConfig(
            name="坏链",
            stages=[_custom_stage("worldview")],
            source="yaml",
        )
        svc = _build_svc(pipeline=pipeline, agent_repo=_agent_repo([]))
        request = PipelineExecuteRequest(
            project_id=PROJECT_ID, pipeline="bad.yaml", pipeline_config=config
        )

        with pytest.raises(AgentServiceError, match="自定义管线配置无效"):
            await svc._build_pipeline_context(request)
        # 校验对象 = 自定义拓扑本身
        assert [s.id for s in pipeline.validated[0]] == ["worldview"]

    async def test_custom_stage_carries_agent_skill(self, monkeypatch, tmp_path) -> None:
        """自定义 stage 的 Agent 携带其 skill_ids 命中的 skill（对齐 #1472/#1473）。"""
        root = tmp_path / "skills"
        (root / "worldview-methodology").mkdir(parents=True)
        (root / "worldview-methodology" / "SKILL.md").write_text(
            "# w\n\n世界观方法论特征词ZULU\n", encoding="utf-8"
        )
        (root / "polishing-methodology").mkdir(parents=True)
        (root / "polishing-methodology" / "SKILL.md").write_text(
            "# p\n\n润色方法论特征词YANKEE\n", encoding="utf-8"
        )
        _patch_skills_root(monkeypatch, tmp_path)

        agents = [
            _make_agent("worldview", ["worldview-methodology"]),
            _make_agent("polisher", []),
        ]
        svc = _build_svc(agent_repo=_agent_repo(agents))
        request = PipelineExecuteRequest(
            project_id=PROJECT_ID, pipeline="worldview,polisher", stages=list(CUSTOM_ROLE_KEYS)
        )

        stages, *_ = await svc._build_pipeline_context(request)
        by_id = {s.id: s for s in stages}

        assert "世界观方法论特征词ZULU" in by_id["worldview"].agent.system_prompt


# ── 4. 内置 4 条管线零回归（当前 PASS，必须守住） ─────────────


BUILTIN_EXPECTED_STAGES: dict[str, list[str]] = {
    "builtin:write_chapter": ["architect", "writer", "auditor", "reviser"],
    "builtin:write_auto": ["architect", "writer", "auditor", "reviser"],
    "builtin:write_continue": ["writer", "auditor", "reviser"],
    "builtin:chat": ["chat"],
}


class TestBuiltinPipelinesRegression:
    """内置 4 条管线的 stage 序列与模板真源一致（逐条断言）。"""

    @pytest.mark.parametrize("template_id", sorted(BUILTIN_EXPECTED_STAGES))
    async def test_builtin_stage_sequence_unchanged(self, template_id: str) -> None:
        svc = _build_svc(agent_repo=_agent_repo([]))
        request = PipelineExecuteRequest(project_id=PROJECT_ID, pipeline=template_id)

        stages, *_ = await svc._build_pipeline_context(request)

        assert [s.id for s in stages] == BUILTIN_EXPECTED_STAGES[template_id]

    @pytest.mark.parametrize("template_id", sorted(BUILTIN_EXPECTED_STAGES))
    def test_template_source_matches_expected(self, template_id: str) -> None:
        """模板真源与上表一致（双保险：执行链与模板数据同时被锁）。"""
        from inkflow.infrastructure.agent.pipeline_templates import get_template

        template = get_template(template_id)
        assert template is not None
        assert [s.id for s in template.stages] == BUILTIN_EXPECTED_STAGES[template_id]
