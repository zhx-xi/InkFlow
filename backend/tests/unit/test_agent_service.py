"""AgentService 服务层测试 — 编排管线执行、状态查询、校验与模板 (spec §9.3)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.agent_pipeline import (
    PipelineConfig,
    PipelineExecuteRequest,
    RoleOverride,
)
from inkflow.domain.models.chapter import Chapter
from inkflow.domain.models.project import (
    AGENT_DEFAULT_SENTINEL,
    Genre,
    Project,
    ProjectConfig,
)
from inkflow.domain.ports.agent_pipeline import (
    PipelineContext,
    PipelineError,
    PipelineResult,
    PipelineStage,
    StageResult,
    StageStatus,
)
from inkflow.domain.services.agent_service import AgentService, AgentServiceError
from inkflow.infrastructure.agent.pipeline_templates import get_template


def _make_project(
    project_id: uuid.UUID | None = None, config: ProjectConfig | None = None
) -> Project:
    """构造测试用 Project 领域对象。"""
    return Project(
        id=project_id or uuid.uuid4(),
        name="测试项目",
        genre=Genre.XUANHUAN,
        language="zh-CN",
        target_words=100000,
        config=config or ProjectConfig(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_chapter(
    chapter_id: uuid.UUID | None = None, project_id: uuid.UUID | None = None
) -> Chapter:
    """构造测试用 Chapter 领域对象。"""
    return Chapter(
        id=chapter_id or uuid.uuid4(),
        project_id=project_id or uuid.uuid4(),
        title="第一章",
        content="",
    )


class MockPipeline:
    """记录调用并返回预设结果的管线 Mock。"""

    def __init__(self, result: PipelineResult | None = None, errors: list[str] | None = None):
        self.result = result or PipelineResult(
            stages=[
                StageResult(stage_id="architect", status=StageStatus.COMPLETED, output="大纲"),
                StageResult(stage_id="writer", status=StageStatus.COMPLETED, output="正文"),
            ],
            final_output="正文",
            status=StageStatus.COMPLETED,
            total_duration_ms=123,
        )
        self.errors = errors or []
        self.execute_called = False
        self.executed_stages: list[PipelineStage] = []
        self.executed_context: PipelineContext | None = None

    async def execute(
        self, stages: list[PipelineStage], context: PipelineContext
    ) -> PipelineResult:
        self.execute_called = True
        self.executed_stages = list(stages)
        self.executed_context = context
        return self.result

    def validate(self, stages: list[PipelineStage]) -> list[str]:
        return self.errors


class FakeExecution:
    """模拟 AgentExecutionORM 的轻量对象。"""

    _seq = 0  # 单调递增序号，模拟 created_at 的唯一性（Windows 时钟分辨率约 1ms）

    def __init__(self, pipeline: str, project_id: str, chapter_id: str | None = None):
        FakeExecution._seq += 1
        self._seq = FakeExecution._seq
        self.id = str(uuid.uuid4())
        self.pipeline = pipeline
        self.project_id = project_id
        self.chapter_id = chapter_id
        self.status = "pending"
        self.stages: list[dict] = []
        self.final_output = ""
        self.error = ""
        self.total_duration_ms = 0
        self.created_at = datetime.now(UTC)


class MockExecutionStore:
    """内存版 ExecutionStore — dict 替代 SQLite。"""

    def __init__(self):
        self.executions: dict[str, FakeExecution] = {}

    async def create_execution(
        self,
        pipeline: str,
        project_id: str,
        chapter_id: str | None = None,
    ) -> FakeExecution:
        execution = FakeExecution(pipeline, project_id, chapter_id)
        self.executions[execution.id] = execution
        return execution

    async def get_execution(self, execution_id: str) -> FakeExecution | None:
        return self.executions.get(execution_id)

    async def update_stages(
        self,
        execution_id: str,
        stages: list[dict],
        status: str,
        final_output: str = "",
        error: str = "",
        total_duration_ms: int = 0,
    ) -> None:
        execution = self.executions.get(execution_id)
        if execution is None:
            return
        execution.stages = stages
        execution.status = status
        execution.final_output = final_output
        execution.error = error
        execution.total_duration_ms = total_duration_ms

    async def list_executions(
        self, project_id: str, limit: int = 20
    ) -> tuple[list[FakeExecution], int]:
        matching = [e for e in self.executions.values() if e.project_id == project_id]
        # created_at 降序，同刻创建时按创建顺序倒序（对应真实 SQL 的 created_at desc）
        matching.sort(key=lambda e: (e.created_at, e._seq), reverse=True)
        return matching[:limit], len(matching)


class MockProjectRepo:
    """固定返回预设 Project 或 None 的项目仓储 Mock（对应 SQLiteProjectRepository.get）。"""

    def __init__(self, project: Project | None = None):
        self.project = project

    async def get(self, project_id: int) -> Project | None:
        return self.project


class MockChapterRepo:
    """固定返回预设 Chapter 或 None 的章节仓储 Mock（对应 SQLiteChapterRepository.get_chapter）。"""

    def __init__(self, chapter: Chapter | None = None):
        self.chapter = chapter

    async def get_chapter(self, chapter_id: int) -> Chapter | None:
        return self.chapter


def _build_service(
    pipeline: MockPipeline | None = None,
    project: Project | None = None,
    chapter: Chapter | None = None,
    store: MockExecutionStore | None = None,
) -> tuple[AgentService, MockPipeline, MockExecutionStore, MockProjectRepo, MockChapterRepo]:
    """装配 AgentService，全部依赖注入 Mock（不触碰真实 DB / LangGraph）。"""
    pipeline = pipeline or MockPipeline()
    store = store or MockExecutionStore()
    project_repo = MockProjectRepo(project)
    chapter_repo = MockChapterRepo(chapter)
    service = AgentService(
        pipeline,
        db_session=None,
        store=store,
        project_repo=project_repo,
        chapter_repo=chapter_repo,
    )
    return service, pipeline, store, project_repo, chapter_repo


class TestExecute:
    async def test_execute_creates_pending_record(self):
        """execute() → 创建 pending 记录，返回 execution_id；后台任务随后更新为 completed。"""
        project = _make_project()
        service, _, store, _, _ = _build_service(project=project)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")

        result = await service.execute(request)

        assert result["status"] == "pending"
        assert result["pipeline"] == "builtin:write_chapter"
        assert result["project_id"] == str(project.id)
        assert result["execution_id"]
        record = store.executions[result["execution_id"]]
        assert record.status == "pending"
        assert record.project_id == str(project.id)

        await asyncio.sleep(0.05)  # 等待后台任务完成
        status = await service.get_status(result["execution_id"])
        assert status["status"] == "completed"

    async def test_execute_project_not_found(self):
        """不存在项目 → 抛 AgentServiceError（含"项目不存在"）。"""
        service, _, _, _, _ = _build_service(project=None)
        request = PipelineExecuteRequest(project_id=uuid.uuid4(), pipeline="builtin:write_chapter")

        with pytest.raises(AgentServiceError, match="项目不存在"):
            await service.execute(request)

    async def test_execute_unknown_template(self):
        """未知管线模板 → 抛 AgentServiceError（含"未知管线模板"）。"""
        project = _make_project()
        service, _, _, _, _ = _build_service(project=project)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="unknown:xxx")

        with pytest.raises(AgentServiceError, match="未知管线模板"):
            await service.execute(request)

    async def test_execute_chapter_not_found(self):
        """chapter_id 提供但章节不存在 → 抛 AgentServiceError（含"章节不存在"）。"""
        project = _make_project()
        service, _, _, _, _ = _build_service(project=project, chapter=None)
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_chapter",
            chapter_id=uuid.uuid4(),
        )

        with pytest.raises(AgentServiceError, match="章节不存在"):
            await service.execute(request)

    async def test_execute_role_overrides_merged(self):
        """role_overrides 覆盖模板默认值；项目配置次之；未覆盖角色保持模板值。"""
        project = _make_project(
            config=ProjectConfig(agent_writer="project/writer-model", temperature=0.9)
        )
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_chapter",
            role_overrides={
                "writer": RoleOverride(
                    prompt="自定义写手提示词", model="override/model", temperature=1.5
                )
            },
        )

        await service.execute(request)
        await asyncio.sleep(0.05)

        stages = {s.id: s for s in pipeline.executed_stages}
        # role_overrides 最高优先级
        assert stages["writer"].agent.model == "override/model"
        assert stages["writer"].agent.temperature == 1.5
        assert stages["writer"].agent.system_prompt == "自定义写手提示词"
        # 项目配置覆盖模板默认温度（模板 architect=0.7 → 项目 0.9）
        assert stages["architect"].agent.temperature == 0.9
        # 未覆盖角色保持模板值
        assert stages["auditor"].agent.temperature == 0.5
        assert stages["reviser"].agent.model == "openai/gpt-4o"

    async def test_execute_runs_pipeline_async(self):
        """execute() 立即返回（fire-and-forget），后台任务调用 pipeline.execute()。"""
        project = _make_project()
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")

        result = await service.execute(request)

        # create_task 尚未调度执行 → execute() 返回时后台任务未运行
        assert pipeline.execute_called is False
        await asyncio.sleep(0.05)
        assert pipeline.execute_called is True
        assert pipeline.executed_context is not None
        assert pipeline.executed_context.project_id == str(project.id)
        assert [s.id for s in pipeline.executed_stages] == [
            "architect",
            "writer",
            "auditor",
            "reviser",
        ]
        assert result["execution_id"]


class TestStatus:
    async def test_get_status_returns_stages(self):
        """get_status() → status + stages 快照 + final_output + duration。"""
        project = _make_project()
        service, _, _, _, _ = _build_service(project=project)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")
        result = await service.execute(request)
        await asyncio.sleep(0.05)

        status = await service.get_status(result["execution_id"])

        assert status is not None
        assert status["status"] == "completed"
        assert status["pipeline"] == "builtin:write_chapter"
        assert [s["stage_id"] for s in status["stages"]] == ["architect", "writer"]
        assert status["final_output"] == "正文"
        assert status["total_duration_ms"] == 123

    async def test_get_status_nonexistent(self):
        """不存在的 execution_id → 返回 None。"""
        service, _, _, _, _ = _build_service()

        status = await service.get_status("no-such-execution")

        assert status is None

    async def test_list_executions_by_project(self):
        """list_executions() → 按 project_id 过滤 + 分页（created_at 降序）。"""
        project = _make_project()
        other = _make_project()
        service, _, _, _, _ = _build_service(project=project)
        ids = []
        for _ in range(3):
            result = await service.execute(
                PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")
            )
            ids.append(result["execution_id"])
        # 其他项目的执行记录不应被统计
        await service.execute(
            PipelineExecuteRequest(project_id=other.id, pipeline="builtin:write_chapter")
        )
        await asyncio.sleep(0.05)

        page = await service.list_executions(str(project.id), limit=2)

        assert page["total"] == 3
        assert len(page["items"]) == 2
        assert [i["execution_id"] for i in page["items"]] == ids[::-1][:2]
        assert all(i["status"] == "completed" for i in page["items"])


class TestValidateAndTemplates:
    def test_validate_proxies_protocol(self):
        """validate_pipeline() 转发 Protocol.validate 的结果。"""
        pipeline = MockPipeline(errors=["阶段 id 不能重复"])
        service, _, _, _, _ = _build_service(pipeline=pipeline)
        config = PipelineConfig(
            name="测试管线", stages=get_template("builtin:write_chapter").stages
        )

        result = service.validate_pipeline(config)

        assert result == {"valid": False, "errors": ["阶段 id 不能重复"]}

        # 无错误时 valid=True
        service2, _, _, _, _ = _build_service(pipeline=MockPipeline(errors=[]))
        assert service2.validate_pipeline(config) == {"valid": True, "errors": []}

    def test_list_templates_returns_builtin(self):
        """list_templates() 返回内置模板列表。"""
        service, _, _, _, _ = _build_service()

        result = service.list_templates()

        ids = [t["id"] for t in result["items"]]
        assert "builtin:write_chapter" in ids
        item = next(t for t in result["items"] if t["id"] == "builtin:write_chapter")
        assert item["stages"] == ["architect", "writer", "auditor", "reviser"]
        assert item["source"] == "builtin"


# ── Phase 3 覆盖率补齐（#104）──────────────────────────────────


class TestExecuteChapterExists:
    """execute 的章节存在校验分支。"""

    async def test_execute_chapter_exists_proceeds(self):
        """chapter_id 提供且章节存在 → 校验通过，创建执行记录并透传 chapter_id。"""
        project = _make_project()
        chapter = _make_chapter(project_id=project.id)
        service, _, store, _, _ = _build_service(project=project, chapter=chapter)
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_chapter",
            chapter_id=chapter.id,
        )

        result = await service.execute(request)

        assert result["status"] == "pending"
        record = store.executions[result["execution_id"]]
        assert record.chapter_id == str(chapter.id)
        await asyncio.sleep(0.05)  # 等待后台任务收尾，避免事件循环悬挂


class TestRoleOverridePartials:
    """role_overrides 部分字段覆盖（prompt/model/temperature 各自独立）。"""

    async def test_override_prompt_only_keeps_other_fields(self):
        """只给 prompt → model/temperature 保持模板值（温度不触发项目默认替换条件 0.7）。"""
        project = _make_project(config=ProjectConfig(temperature=0.9))
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        template_stages = {s.id: s for s in get_template("builtin:write_chapter").stages}
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_chapter",
            role_overrides={"writer": RoleOverride(prompt="只改提示词")},
        )

        await service.execute(request)
        await asyncio.sleep(0.05)

        writer = {s.id: s for s in pipeline.executed_stages}["writer"]
        assert writer.agent.system_prompt == "只改提示词"
        # model 未被覆盖；temperature 保持模板值（模板 writer=0.8，非 0.7 不触发项目替换）
        assert writer.agent.model == template_stages["writer"].agent.model
        assert writer.agent.temperature == template_stages["writer"].agent.temperature
        assert writer.agent.temperature != 0.9

    async def test_override_model_only_keeps_prompt(self):
        """只给 model → prompt 保持模板值、temperature 不被覆盖。"""
        project = _make_project()
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        template_stages = {s.id: s for s in get_template("builtin:write_chapter").stages}
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_chapter",
            role_overrides={"writer": RoleOverride(model="override/model")},
        )

        await service.execute(request)
        await asyncio.sleep(0.05)

        writer = {s.id: s for s in pipeline.executed_stages}["writer"]
        assert writer.agent.model == "override/model"
        assert writer.agent.system_prompt == template_stages["writer"].agent.system_prompt
        assert writer.agent.temperature == template_stages["writer"].agent.temperature


class TestRunPipelineFailures:
    """_run_pipeline 后台任务的异常落库路径。"""

    async def test_run_pipeline_pipeline_error_marks_failed(self):
        """pipeline.execute 抛 PipelineError → 记录 status=failed + error 消息。"""
        project = _make_project()
        pipeline = MockPipeline()
        pipeline.execute = AsyncMock(side_effect=PipelineError("管线爆炸"))
        service, _, store, _, _ = _build_service(project=project, pipeline=pipeline)
        execution = await store.create_execution(
            pipeline="builtin:write_chapter", project_id=str(project.id)
        )

        await service._run_pipeline(execution.id, [], PipelineContext(project_id=str(project.id)))

        record = store.executions[execution.id]
        assert record.status == "failed"
        assert record.error == "管线爆炸"
        assert record.stages == []

    async def test_run_pipeline_unexpected_error_marks_failed(self):
        """pipeline.execute 抛非 PipelineError → status=failed + 「执行异常: …」。"""
        project = _make_project()
        pipeline = MockPipeline()
        pipeline.execute = AsyncMock(side_effect=ValueError("boom"))
        service, _, store, _, _ = _build_service(project=project, pipeline=pipeline)
        execution = await store.create_execution(
            pipeline="builtin:write_chapter", project_id=str(project.id)
        )

        await service._run_pipeline(execution.id, [], PipelineContext(project_id=str(project.id)))

        record = store.executions[execution.id]
        assert record.status == "failed"
        assert record.error == "执行异常: boom"
        assert record.stages == []


class TestMergeRoleConfigsSentinel:
    """F42 #268 三态模型选择执行层（spec §5.1 + §13 M1）：

    - agent_* = AGENT_DEFAULT_SENTINEL（"__default__"）→ 不覆盖模板角色模型
      （v1.0 缺陷：非空即覆盖 → model="__default__" → parse_model_string ValueError）
    - agent_* = 裸模型名（无 /）→ warning + 回退跟随默认（不覆盖，不抛错）
    - agent_* = 合规 provider/model → 覆盖模板角色模型（既有语义保持）
    """

    async def test_sentinel_falls_back_to_project_model(self):
        """agent_writer="__default__" + model="deepseek/deepseek-v4-flash" → writer stage
        model 回退项目 model（#367：sentinel=跟随默认 → 跟随项目配置的 model，
        非模板 openai/gpt-4o；v1.0 缺陷：不覆盖 → 无 openai key → 重试耗尽）。"""
        project = _make_project(
            config=ProjectConfig(
                model="deepseek/deepseek-v4-flash",
                agent_writer=AGENT_DEFAULT_SENTINEL,
            )
        )
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")

        await service.execute(request)
        await asyncio.sleep(0.05)

        stages = {s.id: s for s in pipeline.executed_stages}
        assert stages["writer"].agent.model == "deepseek/deepseek-v4-flash"
        assert stages["writer"].agent.model != "openai/gpt-4o"

    async def test_bare_model_name_falls_back_to_template(self):
        """agent_writer="gpt-4o"（裸名，无 /）→ warning + 不覆盖（回退跟随默认，零迁移）。"""
        project = _make_project(config=ProjectConfig(agent_writer="gpt-4o"))
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")

        await service.execute(request)
        await asyncio.sleep(0.05)

        stages = {s.id: s for s in pipeline.executed_stages}
        # 裸名不覆盖 → 回退模板模型（Q3 兼容策略，§5.1）
        assert stages["writer"].agent.model == "openai/gpt-4o"

    async def test_qualified_model_overrides_template(self):
        """agent_writer="zhipu/glm-4.5"（合规 provider/model）→ 覆盖模板模型（既有语义保持）。"""
        project = _make_project(config=ProjectConfig(agent_writer="zhipu/glm-4.5"))
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")

        await service.execute(request)
        await asyncio.sleep(0.05)

        stages = {s.id: s for s in pipeline.executed_stages}
        assert stages["writer"].agent.model == "zhipu/glm-4.5"

    async def test_architect_sentinel_follows_project_model(self):
        """混合：architect=__default__（回退项目 model）+ reviser=zhipu/glm-4.5（覆盖）+ 其余模板。
        #367：sentinel 不再保持模板 openai/gpt-4o，而是跟随项目配置的 model。"""
        project = _make_project(
            config=ProjectConfig(
                model="deepseek/deepseek-v4-flash",
                agent_architect=AGENT_DEFAULT_SENTINEL,
                agent_reviser="zhipu/glm-4.5",
            )
        )
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")

        await service.execute(request)
        await asyncio.sleep(0.05)

        stages = {s.id: s for s in pipeline.executed_stages}
        # sentinel → 项目 model
        assert stages["architect"].agent.model == "deepseek/deepseek-v4-flash"
        assert stages["reviser"].agent.model == "zhipu/glm-4.5"  # 合规覆盖
        assert stages["writer"].agent.model == "openai/gpt-4o"  # 未配置 → 模板

    async def test_all_roles_sentinel_follow_project_model(self):
        """GUI 默认配置（#367 真实复现场景）：只配项目 model、四角色全 __default__
        → 四角色全部回退项目 model（非模板 openai/gpt-4o）。"""
        project = _make_project(
            config=ProjectConfig(
                model="deepseek/deepseek-v4-flash",
                agent_architect=AGENT_DEFAULT_SENTINEL,
                agent_writer=AGENT_DEFAULT_SENTINEL,
                agent_auditor=AGENT_DEFAULT_SENTINEL,
                agent_reviser=AGENT_DEFAULT_SENTINEL,
            )
        )
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_auto")

        await service.execute(request)
        await asyncio.sleep(0.05)

        stages = {s.id: s for s in pipeline.executed_stages}
        for stage in stages.values():
            assert (
                stage.agent.model == "deepseek/deepseek-v4-flash"
            ), f"sentinel 应回退项目 model，实际 {stage.id}={stage.agent.model}"


class TestExecuteAgentOrder:
    """F42 #269 执行拓扑装配（spec §5.3.1 F3 定稿：启用集合 → _apply_agent_order →
    _merge_role_configs → _run_pipeline）：配置驱动模式下 pipeline 收到的 stages
    按 agent_order 重排；null 角色摘除。

    RED 形态（两阶段）：ProjectConfig.agent_order 字段不存在（extra='ignore' 静默
    丢弃）→ 首断言 `"agent_order" in config.model_dump()` AssertionError；
    GREEN 后字段存在 → 首断言过，后续顺序断言驱动 execute 接线。
    """

    async def test_execute_reorders_stages_by_config(self):
        """配置驱动模式：agent_order=[[writer],[architect],[auditor],[reviser]] →
        pipeline.executed_stages 顺序 = [writer, architect, auditor, reviser]（F3 装配顺序）。"""
        config = ProjectConfig(
            agent_order=[
                ["agent_writer"],
                ["agent_architect"],
                ["agent_auditor"],
                ["agent_reviser"],
            ],
            agent_architect="openai/gpt-4o",
            agent_writer="openai/gpt-4o",
            agent_auditor="openai/gpt-4o",
            agent_reviser="openai/gpt-4o",
        )
        # RED 阶段首断言：agent_order 字段不存在（extra ignore 静默丢弃）
        assert "agent_order" in config.model_dump()
        project = _make_project(config=config)
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")

        await service.execute(request)
        await asyncio.sleep(0.05)

        assert [s.id for s in pipeline.executed_stages] == [
            "writer",
            "architect",
            "auditor",
            "reviser",
        ]

    async def test_execute_parallel_layer(self):
        """并行层 [[architect],[writer,auditor],[reviser]] → 层序保持（层内顺序不承诺）。"""
        config = ProjectConfig(
            agent_order=[["agent_architect"], ["agent_writer", "agent_auditor"], ["agent_reviser"]],
            agent_architect="openai/gpt-4o",
            agent_writer="openai/gpt-4o",
            agent_auditor="openai/gpt-4o",
            agent_reviser="openai/gpt-4o",
        )
        assert "agent_order" in config.model_dump()
        project = _make_project(config=config)
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")

        await service.execute(request)
        await asyncio.sleep(0.05)

        ids = [s.id for s in pipeline.executed_stages]
        # architect 恒在 writer/auditor 前；reviser 恒在 writer/auditor 后
        assert ids.index("architect") < ids.index("writer")
        assert ids.index("architect") < ids.index("auditor")
        assert ids.index("reviser") > ids.index("writer")
        assert ids.index("reviser") > ids.index("auditor")

    async def test_execute_skips_disabled_role(self):
        """配置驱动模式：agent_writer=null（关闭）+ agent_order 含 writer →
        writer 从执行拓扑摘除（Q2 真禁用 + B1）。"""
        config = ProjectConfig(
            agent_order=[
                ["agent_architect"],
                ["agent_writer"],
                ["agent_auditor"],
                ["agent_reviser"],
            ],
            agent_architect="openai/gpt-4o",
            agent_writer=None,  # 关闭
            agent_auditor="openai/gpt-4o",
            agent_reviser="openai/gpt-4o",
        )
        assert "agent_order" in config.model_dump()
        project = _make_project(config=config)
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")

        await service.execute(request)
        await asyncio.sleep(0.05)

        assert [s.id for s in pipeline.executed_stages] == [
            "architect",
            "auditor",
            "reviser",
        ]

    async def test_execute_default_mode_ignores_null(self):
        """默认模板模式（agent_order 空）：agent_writer=null 不触发跳过（B1：null 不真禁用），
        四角色照常执行（v1.0 语义）。"""
        config = ProjectConfig(agent_writer=None)
        project = _make_project(config=config)
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")

        await service.execute(request)
        await asyncio.sleep(0.05)

        assert [s.id for s in pipeline.executed_stages] == [
            "architect",
            "writer",
            "auditor",
            "reviser",
        ]

    async def test_execute_invalid_order_falls_back_default(self):
        """agent_order 缺启用角色（writer 启用但不在 order）→ 执行层回退默认拓扑（M5）。"""
        config = ProjectConfig(
            agent_order=[["agent_architect"], ["agent_auditor"], ["agent_reviser"]],
            agent_architect="openai/gpt-4o",
            agent_writer="openai/gpt-4o",  # 启用但 order 缺失 → 非法
            agent_auditor="openai/gpt-4o",
            agent_reviser="openai/gpt-4o",
        )
        assert "agent_order" in config.model_dump()
        project = _make_project(config=config)
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")

        await service.execute(request)
        await asyncio.sleep(0.05)

        assert [s.id for s in pipeline.executed_stages] == [
            "architect",
            "writer",
            "auditor",
            "reviser",
        ]


class TestListTemplatesNewBuiltin:
    """F42 #297：list_templates() 暴露 write_auto / write_continue（M6）。"""

    def test_list_templates_includes_new_templates(self) -> None:
        """list_templates() 返回含 write_auto / write_continue（CLI agent template
        pipelines 自动暴露）。"""
        service, _, _, _, _ = _build_service()

        result = service.list_templates()

        ids = [t["id"] for t in result["items"]]
        assert "builtin:write_auto" in ids
        assert "builtin:write_continue" in ids
        auto = next(t for t in result["items"] if t["id"] == "builtin:write_auto")
        assert auto["stages"] == ["architect", "writer", "auditor", "reviser"]
        cont = next(t for t in result["items"] if t["id"] == "builtin:write_continue")
        assert cont["stages"] == ["writer", "auditor", "reviser"]


class TestExecuteNewBuiltinTemplates:
    """F42 #297：execute 双模板默认模板模式（agent_order 空，null 不跳过，M5）。"""

    async def test_execute_write_auto_default_mode(self) -> None:
        """execute(builtin:write_auto) 默认模板模式：4 角色照常（null 不跳过）。"""
        config = ProjectConfig(agent_writer=None)  # null 不触发跳过（默认模板模式）
        project = _make_project(config=config)
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_auto")

        await service.execute(request)
        await asyncio.sleep(0.05)

        assert [s.id for s in pipeline.executed_stages] == [
            "architect",
            "writer",
            "auditor",
            "reviser",
        ]

    async def test_execute_write_continue_default_mode(self) -> None:
        """execute(builtin:write_continue) 默认模板模式：3 角色（无 architect）。"""
        config = ProjectConfig(agent_writer=None)
        project = _make_project(config=config)
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_continue")

        await service.execute(request)
        await asyncio.sleep(0.05)

        assert [s.id for s in pipeline.executed_stages] == ["writer", "auditor", "reviser"]


class FakeTemplateRepo:
    """自定义角色装配用模板仓储 Mock（get 返回预设 AgentTemplate 或 None）。"""

    def __init__(self, template=None):
        self.template = template

    async def get(self, template_id):
        return self.template


class TestExecuteCustomRole:
    """F42 #295 execute 自定义角色装配（spec §5.3.4 数据面集成 + §13 M6）。

    契约：agent_roles（自定义角色三态）+ agent_order 引用自定义角色 + template_id
    模板 roles 定义自定义角色 prompt → execute 装配后 pipeline.executed_stages
    含自定义角色 stage（system_prompt/name/model 装配正确，层序正确）。

    RED 形态（多阶段）：首断言 `"agent_roles" in config.model_dump()` AssertionError
    （字段不存在，extra ignore 静默丢弃）；GREEN 后字段存在 → 后续装配断言驱动。
    """

    async def test_execute_custom_role_via_template_roles(self):
        """agent_roles + agent_order + template_id 模板 roles → 自定义角色经装配执行。"""
        from inkflow.domain.models.agent_template import AgentTemplate, RoleTemplate

        template = AgentTemplate(
            id=1,
            name="自定义模板",
            roles={"researcher": RoleTemplate(prompt="你是研究员，检查章节设定", name="研究员")},
        )
        config = ProjectConfig(
            template_id="1",
            agent_order=[["agent_architect"], ["agent_writer"], ["agent_researcher"]],
            agent_architect="openai/gpt-4o",
            agent_writer="openai/gpt-4o",
            agent_roles={"agent_researcher": "zhipu/glm-4.5"},
        )
        assert "agent_roles" in config.model_dump()  # RED 首断言
        project = _make_project(config=config)
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)
        service._template_repo = FakeTemplateRepo(template)

        await service.execute(
            PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")
        )
        await asyncio.sleep(0.05)

        stages = {s.id: s for s in pipeline.executed_stages}
        assert "researcher" in stages
        assert stages["researcher"].agent.system_prompt == "你是研究员，检查章节设定"
        assert stages["researcher"].agent.name == "研究员"
        # agent_roles 覆盖 model（三态 provider/model）
        assert stages["researcher"].agent.model == "zhipu/glm-4.5"
        # 层序：researcher（层 2）在 writer（层 1）后
        ids = [s.id for s in pipeline.executed_stages]
        assert ids.index("researcher") > ids.index("writer")
        # 配置驱动模式：auditor/reviser 为 null → 跳过（不参与执行）
        assert "auditor" not in stages
        assert "reviser" not in stages

    async def test_execute_custom_role_model_none_follows_default(self):
        """agent_roles 自定义角色 value=None（关闭）→ 不参与执行（null 摘除）。"""
        config = ProjectConfig(
            agent_order=[["agent_architect"], ["agent_writer"]],
            agent_architect="openai/gpt-4o",
            agent_writer="openai/gpt-4o",
            agent_roles={"agent_researcher": None},  # 关闭
        )
        project = _make_project(config=config)
        pipeline = MockPipeline()
        service, pipeline, _, _, _ = _build_service(project=project, pipeline=pipeline)

        await service.execute(
            PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")
        )
        await asyncio.sleep(0.05)

        stages = {s.id: s for s in pipeline.executed_stages}
        assert "researcher" not in stages  # null 关闭 → 未构造/未执行
