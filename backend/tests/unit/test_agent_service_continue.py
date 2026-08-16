"""AgentService write_continue 前文摘要注入契约（#318，spec §5.6 + F6 §4.6）。

背景：write_continue 管线执行时后端自动生成「前文摘要」注入 context 变量，
前端不再传全文。摘要来源 = 前序章节（order_index < 当前），复用
SummaryService.ensure_summary（F6 summary_repo 缓存 + LLM 生成），最多 10 章。

设计假设（父侧定稿，GREEN 任务书一致）：
- AgentService.__init__ 新增可选参数 summary_service: Any = None（默认 None 向后兼容）
- execute() 在 pipeline=="builtin:write_continue" 且 chapter_id 非空时，
  create_task 传 continue_context=True 给 _run_pipeline
- _run_pipeline 新增 continue_context: bool = False 参数：True 时开头调用
  _assemble_continue_context(project_id, chapter_id, variables) 组装 context.variables
- _assemble_continue_context 语义：
  1. summary_service 为 None 或 chapter_id 为空 → 原样返回 variables
  2. project = project_repo.get(int)；project 不存在 → 原样返回
  3. model = project.config.model（摘要生成模型）
  4. current = chapter_repo.get_chapter(int)；不存在 → 原样返回
  5. chapters, _ = chapter_repo.list_chapters(project_id.int, limit=1000)
  6. 前序 = order_index < current.order_index，按 order_index 正序取最近 10 章
  7. 逐章 ensure_summary(ch.id, model)；单章失败 → WARNING + 跳过（F6 §4.6 不阻断）
  8. parts 非空 → variables["context"] = "\\n\\n".join(f"{ch.title}：{summary}")
  9. 整体异常 → WARNING + 原样返回（管线执行永不因摘要失败而失败）

RED 形态：C1/C2/C6/C7 FAILED（断言失败：context 键缺失 / ensure_summary 未被调用），
C3/C4/C5 守护用例 PASS（RED 阶段刻意通过，GREEN 后锁行为）。

asyncio 模式: pytest-asyncio mode=Mode.AUTO（pyproject asyncio_mode = "auto"）；
文件级 pytestmark = pytest.mark.asyncio 双保险。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

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

pytestmark = pytest.mark.asyncio

# ── 辅助工厂 ────────────────────────────────────────────────────


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
    chapter_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    title: str = "第一章",
    order_index: float = 1.0,
) -> Chapter:
    """构造测试用 Chapter 领域对象（order_index 用于前序判定）。"""
    return Chapter(
        id=chapter_id or uuid.uuid4(),
        project_id=project_id or uuid.uuid4(),
        title=title,
        content="正文内容",
        order_index=order_index,
    )


# ── Mock 依赖 ───────────────────────────────────────────────────


class MockPipeline:
    """记录调用并返回预设结果的管线 Mock（镜像 test_agent_service.py）。"""

    def __init__(self, result: PipelineResult | None = None, errors: list[str] | None = None):
        self.result = result or PipelineResult(
            stages=[
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
        matching.sort(key=lambda e: (e.created_at, e._seq), reverse=True)
        return matching[:limit], len(matching)


class MockProjectRepo:
    """固定返回预设 Project 或 None 的项目仓储 Mock。"""

    def __init__(self, project: Project | None = None):
        self.project = project

    async def get(self, project_id: int) -> Project | None:
        return self.project


class MockChapterRepo:
    """章节仓储 Mock — get_chapter + list_chapters（前序章节获取）。"""

    def __init__(self, chapters: list[Chapter] | None = None):
        self.chapters = chapters or []

    async def get_chapter(self, chapter_id: int) -> Chapter | None:
        for c in self.chapters:
            if c.id.int == chapter_id:
                return c
        return None

    async def list_chapters(
        self,
        project_id: int,
        volume_id: int | None = None,
        status: object | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Chapter], int]:
        matching = [c for c in self.chapters if c.project_id.int == project_id]
        return matching, len(matching)


class MockSummaryService:
    """摘要服务 Mock — ensure_summary 记录调用 + 预置摘要 / 按 id 抛异常。"""

    def __init__(
        self,
        summaries: dict[uuid.UUID, str] | None = None,
        fail_ids: set[uuid.UUID] | None = None,
    ) -> None:
        self.summaries = summaries or {}
        self.fail_ids = fail_ids or set()
        self.calls: list[tuple[uuid.UUID, str]] = []

    async def ensure_summary(self, chapter_id: uuid.UUID, model: str) -> str:
        self.calls.append((chapter_id, model))
        if chapter_id in self.fail_ids:
            raise RuntimeError("LLM 摘要生成失败")
        return self.summaries.get(chapter_id, f"摘要-{chapter_id}")


def _build_service(
    project: Project | None = None,
    chapters: list[Chapter] | None = None,
) -> tuple[AgentService, MockPipeline, MockExecutionStore]:
    """装配 AgentService，全部依赖注入 Mock（不触碰真实 DB / LangGraph）。

    刻意不传 summary_service（构造签名向后兼容）；测试内通过属性注入
    service._summary_service = mock 覆盖——RED 阶段即生效。
    """
    pipeline = MockPipeline()
    store = MockExecutionStore()
    project_repo = MockProjectRepo(project)
    chapter_repo = MockChapterRepo(chapters)
    service = AgentService(
        pipeline,
        db_session=None,
        store=store,
        project_repo=project_repo,
        chapter_repo=chapter_repo,
    )
    return service, pipeline, store


# ── 契约用例 ────────────────────────────────────────────────────


class TestWriteContinueContext:
    async def test_write_continue_injects_context(self):
        """write_continue + chapter_id → 后台组装前序章节摘要注入 context 变量。

        RED 预期：FAILED（context 键缺失，AssertionError）。
        """
        project = _make_project()
        ch1 = _make_chapter(project_id=project.id, title="第一章", order_index=1.0)
        ch2 = _make_chapter(project_id=project.id, title="第二章", order_index=2.0)
        cur = _make_chapter(project_id=project.id, title="第三章", order_index=3.0)
        service, pipeline, _ = _build_service(project=project, chapters=[ch1, ch2, cur])
        summary_svc = MockSummaryService(summaries={ch1.id: "摘要A", ch2.id: "摘要B"})
        service._summary_service = summary_svc
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_continue",
            chapter_id=cur.id,
        )

        result = await service.execute(request)
        assert result["status"] == "pending"

        await asyncio.sleep(0.05)  # 等待后台任务完成
        ctx = pipeline.executed_context
        assert ctx is not None
        assert "context" in ctx.variables
        assert "第一章" in ctx.variables["context"]
        assert "摘要A" in ctx.variables["context"]
        assert "第二章" in ctx.variables["context"]
        assert "摘要B" in ctx.variables["context"]

    async def test_ensure_summary_uses_project_model(self):
        """摘要生成使用 project.config.model（F6 summary_model 默认语义）。

        RED 预期：FAILED（ensure_summary 未被调用，AssertionError）。
        """
        project = _make_project(config=ProjectConfig(model="custom/model"))
        ch1 = _make_chapter(project_id=project.id, title="第一章", order_index=1.0)
        ch2 = _make_chapter(project_id=project.id, title="第二章", order_index=2.0)
        cur = _make_chapter(project_id=project.id, title="第三章", order_index=3.0)
        service, _, _ = _build_service(project=project, chapters=[ch1, ch2, cur])
        summary_svc = MockSummaryService(summaries={ch1.id: "摘要A", ch2.id: "摘要B"})
        service._summary_service = summary_svc
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_continue",
            chapter_id=cur.id,
        )

        await service.execute(request)
        await asyncio.sleep(0.05)

        assert summary_svc.calls == [
            (ch1.id, "custom/model"),
            (ch2.id, "custom/model"),
        ]

    async def test_no_prev_chapters_no_context(self):
        """当前章 = 项目第一章（无前序）→ 不注入 context、不调用摘要。

        守护用例：RED 阶段即 PASS（未实现注入逻辑时也不注入），GREEN 后锁行为。
        """
        project = _make_project()
        cur = _make_chapter(project_id=project.id, title="第一章", order_index=1.0)
        service, pipeline, _ = _build_service(project=project, chapters=[cur])
        summary_svc = MockSummaryService()
        service._summary_service = summary_svc
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_continue",
            chapter_id=cur.id,
        )

        await service.execute(request)
        await asyncio.sleep(0.05)

        ctx = pipeline.executed_context
        assert ctx is not None
        assert "context" not in ctx.variables
        assert summary_svc.calls == []

    async def test_summary_service_none_skips(self):
        """未注入 summary_service（向后兼容）→ execute 正常返回，不组装。

        守护用例：RED 阶段即 PASS（构造签名不变，execute 正常），GREEN 后锁行为。
        """
        project = _make_project()
        cur = _make_chapter(project_id=project.id, title="第一章", order_index=1.0)
        service, _, _ = _build_service(project=project, chapters=[cur])
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_continue",
            chapter_id=cur.id,
        )

        result = await service.execute(request)

        assert result["status"] == "pending"

    async def test_write_auto_does_not_inject(self):
        """write_auto（非 write_continue）→ 不注入 context、不调用摘要。

        守护用例：RED 阶段即 PASS（未实现注入逻辑时也不注入），GREEN 后锁行为。
        """
        project = _make_project()
        cur = _make_chapter(project_id=project.id, title="第一章", order_index=1.0)
        service, pipeline, _ = _build_service(project=project, chapters=[cur])
        summary_svc = MockSummaryService(summaries={cur.id: "不应使用"})
        service._summary_service = summary_svc
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_auto",
            chapter_id=cur.id,
        )

        await service.execute(request)
        await asyncio.sleep(0.05)

        ctx = pipeline.executed_context
        assert ctx is not None
        assert "context" not in ctx.variables
        assert summary_svc.calls == []

    async def test_summary_failure_skips_chapter(self):
        """单章摘要生成失败 → WARNING + 跳过该章，其余章正常注入（F6 §4.6）。

        RED 预期：FAILED（context 键缺失，AssertionError）。
        """
        project = _make_project()
        ch1 = _make_chapter(project_id=project.id, title="第一章", order_index=1.0)
        ch2 = _make_chapter(project_id=project.id, title="第二章", order_index=2.0)
        cur = _make_chapter(project_id=project.id, title="第三章", order_index=3.0)
        service, pipeline, _ = _build_service(project=project, chapters=[ch1, ch2, cur])
        summary_svc = MockSummaryService(summaries={ch1.id: "摘要A"}, fail_ids={ch2.id})
        service._summary_service = summary_svc
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_continue",
            chapter_id=cur.id,
        )

        await service.execute(request)
        await asyncio.sleep(0.05)

        ctx = pipeline.executed_context
        assert ctx is not None
        assert "context" in ctx.variables
        assert "摘要A" in ctx.variables["context"]
        assert "摘要B" not in ctx.variables["context"]

    async def test_only_recent_10_chapters(self):
        """前序超过 10 章 → 只取最近 10 章（F6 §4.5 summary_max_chapters=10）。

        RED 预期：FAILED（context 键缺失，AssertionError）。
        """
        project = _make_project()
        prev = [
            _make_chapter(project_id=project.id, title=f"第{i}章", order_index=float(i))
            for i in range(1, 13)
        ]
        cur = _make_chapter(project_id=project.id, title="第13章", order_index=13.0)
        service, pipeline, _ = _build_service(project=project, chapters=[*prev, cur])
        summary_svc = MockSummaryService(summaries={c.id: f"摘要{c.title}" for c in prev})
        service._summary_service = summary_svc
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_continue",
            chapter_id=cur.id,
        )

        await service.execute(request)
        await asyncio.sleep(0.05)

        ctx = pipeline.executed_context
        assert ctx is not None
        assert "context" in ctx.variables
        assert "第1章" not in ctx.variables["context"]
        assert "第2章" not in ctx.variables["context"]
        assert "第3章" in ctx.variables["context"]
        assert "第12章" in ctx.variables["context"]
