"""v1.5 #484 execute 装配 Agent 真源契约（spec §5.7.4 + §13 M9 ⑤⑦）。

拆分自 test_agent_service.py（900 行护栏，2026-08-19 #484）——本文件仅含 v1.5
新增契约；辅助 fixture/类（_make_project/_build_service/MockPipeline 等）从
test_agent_service 兄弟模块 import（pytest rootdir 收集时同目录可达）。

契约：AgentService 装配 Agent 真源（agent_repo 注入；默认 None → execute 时延迟
导入 SQLiteAgentRepository(db_session)），execute 将 agents（role_key 非空）构建
agent_source 映射（role_key → {name, system_prompt}）传给 _apply_agent_order：
- agent_worldview 非 null（启用）+ agent_order 含 agent_worldview →
  模板 stages 缺失角色从 AgentEntity 真源构造 stage（prompt/name 断言）
- 自定义 Agent（builtin=False，role_key 由服务层分配）经 agent_roles 启用 →
  stage 从 AgentEntity.system_prompt 真源构造（无模板 roles 也执行）
- agent_repo 为空/加载失败 → 防御：占位构造降级既有行为（template_roles 路径），不阻断
"""

from __future__ import annotations

import asyncio

from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest
from inkflow.domain.models.project import ProjectConfig
from tests.unit.test_agent_service import MockPipeline, _build_service, _make_project


class MockAgentRepo:
    """Agent 真源仓储 Mock（v1.5 execute 装配用；镜像 MockProjectRepo 形态）。"""

    def __init__(self, agents: list | None = None):
        self.agents = agents or []

    async def list(self):
        return list(self.agents)


class TestExecuteAgentSourceV15:
    """v1.5 #484 execute 装配 Agent 真源（spec §5.7.4 + §13 M9 ⑤⑦）。

    RED 形态：AgentService.__init__ 无 agent_repo 参数 → _build_service 传参 TypeError
    （签名未扩）；或注入后 execute 不加载 → worldview stage 缺失断言 FAIL。
    """

    async def test_execute_worldview_stage_from_agent_source(self):
        """agent_worldview 启用 + order 含 worldview → 执行层构造真源 stage。"""
        from inkflow.domain.models.agent import Agent

        config = ProjectConfig(
            agent_order=[
                ["agent_architect"],
                ["agent_writer"],
                ["agent_auditor"],
                ["agent_reviser"],
                ["agent_worldview"],
            ],
            agent_architect="openai/gpt-4o",
            agent_writer="openai/gpt-4o",
            agent_auditor="openai/gpt-4o",
            agent_reviser="openai/gpt-4o",
            agent_worldview="__default__",
        )
        project = _make_project(config=config)
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        service._agent_repo = MockAgentRepo(
            [
                Agent(
                    id=101,
                    name="世界观顾问",
                    builtin=True,
                    role_key="worldview",
                    system_prompt="你是世界观顾问，负责校验角色与伏笔的世界观一致性。",
                )
            ]
        )

        await service.execute(
            PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")
        )
        await asyncio.sleep(0.05)

        stages = {s.id: s for s in pipeline.executed_stages}
        assert "worldview" in stages
        assert stages["worldview"].agent.name == "世界观顾问"
        assert (
            stages["worldview"].agent.system_prompt
            == "你是世界观顾问，负责校验角色与伏笔的世界观一致性。"
        )
        # 终点：worldview 排最后 → 成品身份合法（不触发回退）
        assert pipeline.executed_stages[-1].id == "worldview"

    async def test_execute_custom_agent_from_entity_source(self):
        """自定义 Agent（Agent 管理创建，role_key 分配）经 agent_roles 启用 →
        stage 从 AgentEntity.system_prompt 真源构造（无模板 roles 也执行，§5.7.4）。"""
        from inkflow.domain.models.agent import Agent

        config = ProjectConfig(
            agent_order=[["agent_architect"], ["agent_writer"], ["agent_researcher"]],
            agent_architect="openai/gpt-4o",
            agent_writer="openai/gpt-4o",
            agent_roles={"agent_researcher": "zhipu/glm-4.5"},
        )
        project = _make_project(config=config)
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        service._agent_repo = MockAgentRepo(
            [
                Agent(
                    id=201,
                    name="研究员",
                    builtin=False,
                    role_key="researcher",
                    system_prompt="你是研究员，负责核查章节设定一致性。",
                )
            ]
        )

        await service.execute(
            PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")
        )
        await asyncio.sleep(0.05)

        stages = {s.id: s for s in pipeline.executed_stages}
        assert "researcher" in stages
        assert stages["researcher"].agent.system_prompt == "你是研究员，负责核查章节设定一致性。"
        assert stages["researcher"].agent.name == "研究员"
        # agent_roles 覆盖 model
        assert stages["researcher"].agent.model == "zhipu/glm-4.5"

    async def test_execute_worldview_null_not_enabled(self):
        """agent_worldview = null（关闭）→ worldview 不参与执行（Q2 真禁用，v1.5 同内置）。"""
        config = ProjectConfig(
            agent_order=[
                ["agent_architect"],
                ["agent_writer"],
                ["agent_auditor"],
                ["agent_reviser"],
            ],
            agent_architect="openai/gpt-4o",
            agent_writer="openai/gpt-4o",
            agent_auditor="openai/gpt-4o",
            agent_reviser="openai/gpt-4o",
            agent_worldview=None,
        )
        project = _make_project(config=config)
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)

        await service.execute(
            PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")
        )
        await asyncio.sleep(0.05)

        stages = {s.id: s for s in pipeline.executed_stages}
        assert "worldview" not in stages
