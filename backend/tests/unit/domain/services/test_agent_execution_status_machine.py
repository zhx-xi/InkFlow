"""Agent 执行状态机契约测试 — bug #861：agent run 四角色管线 status=pending 恒不转 running。

契约（RED 判据）：
- execute() 初始返回 pending（语义锁定，既有行为不变）；
- 后台执行期间执行记录必须经过 running 中间态（#861 root cause：
  _run_pipeline 正常路径从不调用 store.update_status(execution_id, "running")，
  只在一开始 create 为 pending、最末尾 update_stages 写终态）；
- 终态：成功 → completed + 四角色 stage 快照；管线错误 → failed + error。

本文件自包含：仅引生产模块 + stdlib，mock 均本地定义（不读取其它测试文件）。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.ports.agent_pipeline import (
    PipelineError,
    PipelineResult,
    StageResult,
    StageStatus,
)
from inkflow.domain.services.agent_service import AgentService

FOUR_ROLE_IDS = ["architect", "writer", "auditor", "reviser"]


def _make_project() -> Project:
    """构造测试用 Project 领域对象（镜像既有测试惯例）。"""
    return Project(
        id=uuid.uuid4(),
        name="测试项目",
        tags=["玄幻"],
        language="zh-CN",
        target_words=100000,
        config=ProjectConfig(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _completed_result() -> PipelineResult:
    """四角色全 completed 且输出非空的管线结果。"""
    outputs = {
        "architect": "大纲：三章起承转合",
        "writer": "正文：第一章……",
        "auditor": "审查：前后一致，无时间线冲突",
        "reviser": "润色：文风统一",
    }
    return PipelineResult(
        stages=[
            StageResult(stage_id=role, status=StageStatus.COMPLETED, output=outputs[role])
            for role in FOUR_ROLE_IDS
        ],
        final_output=outputs["reviser"],
        status=StageStatus.COMPLETED,
        total_duration_ms=456,
    )


class ExecutionRecord:
    """模拟 AgentExecutionORM 的轻量执行记录（记录状态机可观测字段）。"""

    def __init__(self, pipeline: str, project_id: str, chapter_id: str | None = None):
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


class RecordingStore:
    """内存 ExecutionStore — 记录每次状态写入，暴露状态机迁移序列。

    statuses 是状态机观察口（刻意记录内部转态，见契约 1）：
    update_status/update_stages 每次被调用都把目标 status append 进 statuses。
    """

    def __init__(self):
        self.executions: dict[str, ExecutionRecord] = {}
        self.statuses: list[str] = []

    async def create_execution(
        self,
        pipeline: str,
        project_id: str,
        chapter_id: str | None = None,
    ) -> ExecutionRecord:
        execution = ExecutionRecord(pipeline, project_id, chapter_id)
        self.executions[execution.id] = execution
        return execution

    async def get_execution(self, execution_id: str) -> ExecutionRecord | None:
        return self.executions.get(execution_id)

    async def update_status(
        self, execution_id: str, status: str, hitl_payload=None
    ) -> None:
        execution = self.executions.get(execution_id)
        if execution is None:
            return
        execution.status = status
        if hitl_payload is not None:
            execution.hitl_payload = hitl_payload
        self.statuses.append(status)

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
        self.statuses.append(status)


class MockPipeline:
    """管线 Mock — 返回预设结果或抛出预设异常，镜像既有测试形态。"""

    def __init__(
        self,
        result: PipelineResult | None = None,
        exc: Exception | None = None,
    ):
        self.result = result or _completed_result()
        self.exc = exc
        self.execute_called = False
        self.executed_stages: list = []

    async def execute(
        self,
        stages: list,
        context,
        conditional_edges: list | None = None,
    ) -> PipelineResult:
        self.execute_called = True
        self.executed_stages = list(stages)
        if self.exc is not None:
            raise self.exc
        return self.result

    def validate(self, stages: list) -> list[str]:
        return []


class MockProjectRepo:
    """固定返回预设 Project 的项目仓储 Mock。"""

    def __init__(self, project: Project | None = None):
        self.project = project

    async def get(self, project_id) -> Project | None:
        return self.project


class MockChapterRepo:
    """固定返回 None 的章节仓储 Mock（无 chapter_id 场景）。"""

    async def get_chapter(self, chapter_id) -> None:
        return None


def _build_service(
    pipeline: MockPipeline | None = None,
    store: RecordingStore | None = None,
) -> tuple[AgentService, MockPipeline, RecordingStore, Project]:
    """装配 AgentService，全部依赖注入 Mock（不触碰真实 DB / LangGraph）。"""
    pipeline = pipeline or MockPipeline()
    store = store or RecordingStore()
    project = _make_project()
    project_repo = MockProjectRepo(project)
    chapter_repo = MockChapterRepo()
    service = AgentService(
        pipeline,
        db_session=None,
        store=store,
        project_repo=project_repo,
        chapter_repo=chapter_repo,
    )
    return service, pipeline, store, project


def _run_request(project: Project) -> PipelineExecuteRequest:
    """builtin:write_chapter 静态管线执行请求（四角色 DAG）。"""
    return PipelineExecuteRequest(project_id=project.id, pipeline="builtin:write_chapter")


class TestExecutionStatusMachine:
    """执行记录状态机契约：pending → running → completed/failed（bug #861）。"""

    async def test_execute_transitions_through_running(self):
        """RED 判据：后台任务执行期间必须把执行记录转为 running。

        当前未修复实现（#861）：_run_pipeline 正常路径从不调用
        store.update_status(execution_id, "running")，只在最末尾
        update_stages 写终态 → store.statuses 只有 ["completed"]，
        "running" 不在其中 → 本断言 FAIL（RED）。
        """
        service, _, store, project = _build_service()
        await service.execute(_run_request(project))

        await asyncio.sleep(0.05)  # 等待后台任务跑完

        # 期望状态机迁移：pending(create) → running(update_status) → completed(update_stages)
        assert "running" in store.statuses, (
            f"执行记录从未转入 running 中间态（bug #861）：状态写入序列={store.statuses}"
        )
        assert store.statuses[-1] == "completed"

    async def test_terminal_completed_with_all_four_roles_done(self):
        """终态契约：成功路径 → completed，四角色 stage 快照齐全且全 completed。"""
        service, _, _, project = _build_service()
        result = await service.execute(_run_request(project))
        execution_id = result["execution_id"]

        await asyncio.sleep(0.05)

        status = await service.get_status(execution_id)
        assert status is not None
        assert status["status"] == "completed"
        assert len(status["stages"]) == 4
        assert [s["stage_id"] for s in status["stages"]] == FOUR_ROLE_IDS
        assert all(s["status"] == "completed" for s in status["stages"])
        assert all(s["output"] for s in status["stages"])

    async def test_terminal_failed_on_pipeline_error(self):
        """终态契约：管线抛 PipelineError → failed + error 透传阶段信息。"""
        exc = PipelineError("管线执行失败: 阶段 'architect' 重试耗尽")
        service, pipeline, _, project = _build_service(pipeline=MockPipeline(exc=exc))
        result = await service.execute(_run_request(project))
        execution_id = result["execution_id"]

        await asyncio.sleep(0.05)

        assert pipeline.execute_called is True
        status = await service.get_status(execution_id)
        assert status is not None
        assert status["status"] == "failed"
        assert "architect" in status["error"]

    async def test_execute_response_is_pending_initial(self):
        """execute() 返回语义锁定：立即返回 pending（fire-and-forget），记录初始 pending。"""
        service, pipeline, store, project = _build_service()
        result = await service.execute(_run_request(project))

        # execute 返回时后台任务尚未跑完 → 初始 pending 语义不被破坏
        assert result["status"] == "pending"
        assert result["execution_id"]
        record = store.executions[result["execution_id"]]
        assert record.status == "pending"

        await asyncio.sleep(0.05)
        assert pipeline.execute_called is True
        final = await service.get_status(result["execution_id"])
        assert final is not None
        assert final["status"] == "completed"
