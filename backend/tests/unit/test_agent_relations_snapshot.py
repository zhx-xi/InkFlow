"""F46 #270 relations 快照回填契约（spec §5.4 数据面）— 独立文件。

背景：test_agent_service.py 超 900 行护栏（999 行，check_file_length CI 拦截）→
TestRelationsSnapshot 拆出为本文件（helper 复制不 import，镜像 test_agent_service.py
既有形态；MockPipeline/FakeExecution/MockExecutionStore 已含 F46 扩展）。

被测：AgentService._run_pipeline relations 快照回填 + get_status 透出 +
execute 装配链 conditional_edges 传递。

契约（spec §5.4 + §7 执行记录 relations 快照行）:
1. execute 装配链：static 模式 conditional_edges 随 stages 传递 → pipeline.execute
   收到 conditional_edges（§5.3.1 步骤 6）
2. _run_pipeline 完成后 → store.update_stages 收到 relations 快照（含 gate 判定）
3. get_status → status["relations"] 透出（F29 既有端点扩展 §5.4）
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest
from inkflow.domain.models.chapter import Chapter
from inkflow.domain.models.project import Genre, Project, ProjectConfig
from inkflow.domain.ports.agent_pipeline import (
    PipelineContext,
    PipelineResult,
    PipelineStage,
    StageResult,
    StageStatus,
)
from inkflow.domain.services.agent_service import AgentService


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


class MockPipeline:
    """记录调用并返回预设结果的管线 Mock（F46 扩展：conditional_edges）。"""

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
        self.executed_conditional_edges: list[tuple[str, str]] | None = None
        self.executed_stages: list[PipelineStage] = []
        self.executed_context: PipelineContext | None = None

    async def execute(
        self,
        stages: list[PipelineStage],
        context: PipelineContext,
        conditional_edges: list[tuple[str, str]] | None = None,
    ) -> PipelineResult:
        self.execute_called = True
        self.executed_stages = list(stages)
        self.executed_context = context
        self.executed_conditional_edges = conditional_edges
        return self.result

    def validate(self, stages: list[PipelineStage]) -> list[str]:
        return self.errors


class FakeExecution:
    """模拟 AgentExecutionORM 的轻量对象。"""

    _seq = 0

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
        self.relations: list[dict] | None = None
        self.created_at = datetime.now(UTC)


class MockExecutionStore:
    """内存版 ExecutionStore — dict 替代 SQLite（F46 扩展：update_stages relations）。"""

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
        relations: list[dict] | None = None,
    ) -> None:
        execution = self.executions.get(execution_id)
        if execution is None:
            return
        execution.stages = stages
        execution.status = status
        execution.final_output = final_output
        execution.error = error
        execution.total_duration_ms = total_duration_ms
        execution.relations = relations


class MockProjectRepo:
    """固定返回预设 Project 或 None 的项目仓储 Mock。"""

    def __init__(self, project: Project | None = None):
        self.project = project

    async def get(self, project_id: int) -> Project | None:
        return self.project


class MockChapterRepo:
    """固定返回预设 Chapter 或 None 的章节仓储 Mock。"""

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
    """装配 AgentService，全部依赖注入 Mock。"""
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


class TestRelationsSnapshot:
    """F46 #270 relations snapshot contract (spec §5.4)."""

    async def test_execute_passes_conditional_edges_to_pipeline(self):
        """static 模式：agent_relations 含 conditional 边 → pipeline.execute 收到
        conditional_edges=[("writer", "auditor")]（§5.3.1 步骤 6 传递链）。"""
        project = _make_project(
            config=ProjectConfig(
                # 仅启用 writer/auditor 且 order 含两者（避免 _apply_agent_order 缺启用角色回退）；
                # conditional writer→auditor 满足「auditor 是 writer 唯一后继」（§2.3）
                agent_writer="openai/gpt-4o",
                agent_auditor="openai/gpt-4o",
                agent_order=[["agent_writer"], ["agent_auditor"]],
                agent_relations=[
                    {"from": "agent_writer", "to": "agent_auditor", "type": "conditional"}
                ],
            )
        )
        service, pipeline, _, _, _ = _build_service(project=project)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")
        await service.execute(request)
        await asyncio.sleep(0.05)

        assert pipeline.executed_conditional_edges == [("writer", "auditor")]

    async def test_run_pipeline_records_relations_snapshot(self):
        """_run_pipeline 完成后 → store.update_stages 收到 relations 快照
        （含 conditional 边 gate 判定 passed/skipped，§5.4）。"""
        project = _make_project()
        service, _, store, _, _ = _build_service(project=project)
        execution = await store.create_execution(
            pipeline="builtin:write_chapter", project_id=str(project.id)
        )
        from inkflow.domain.models.project import AgentRelation

        relations_config = [
            AgentRelation(from_="agent_writer", to="agent_auditor", type="conditional")
        ]

        await service._run_pipeline(
            execution.id,
            [],
            PipelineContext(project_id=str(project.id)),
            agent_relations=relations_config,
        )

        record = store.executions[execution.id]
        assert record.relations is not None
        # 快照含 conditional 边（from/to 去 agent_ 前缀）+ gate 判定
        conditional_entry = next(r for r in record.relations if r.get("type") == "conditional")
        assert conditional_entry["from"] == "writer"
        assert conditional_entry["to"] == "auditor"
        assert conditional_entry["gate_result"] in ("passed", "skipped")

    async def test_get_status_exposes_relations(self):
        """get_status → status["relations"] 透出（F29 端点扩展 §5.4）。"""
        project = _make_project()
        service, _, _, _, _ = _build_service(project=project)
        request = PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")
        result = await service.execute(request)
        await asyncio.sleep(0.05)

        status = await service.get_status(result["execution_id"])

        assert status is not None
        # relations 键存在（缺省为 None；配置 relations 后为快照列表）
        assert "relations" in status
