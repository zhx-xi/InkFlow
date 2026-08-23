"""AgentService 设定注入契约（#366 G1，spec G1 设定注入）。

背景：builtin:write_auto / write_continue 管线执行时，后端自动从项目设定
（角色 characters / 世界观 world_settings / 大纲 outlines）组装摘要注入
variables["setting"]，前端不再手写设定注入 prompt。

设计假设（父侧定稿，GREEN 任务书一致）：
- AgentService.__init__ 新增可选参数 character_repo / world_repo /
  outline_repo: Any = None（默认 None 向后兼容，构造签名零改动）
- _run_pipeline 开头无条件 try/except 调用
  _assemble_setting_context(project_id, variables)——write_auto 与
  write_continue 均注入（G1 与 #318 前文摘要注入并存，见 C2 双键断言）
- _assemble_setting_context 语义：
  1. 三 repo 全为 None（未注入）→ 原样返回 variables
  2. project = project_repo.get(...)；project 不存在 → 原样返回
  3. 逐源读取（失败隔离）：character_repo.list / world_repo.list /
     outline_repo.list 任一抛异常 → WARNING + 跳过该源，其余源仍注入（C5）
  4. 空条目跳过：character 的 personality/background/goals 全空、
     world 的 content 空、outline 的 description 空 → 不进摘要（C6）
  5. 组装摘要注入 variables["setting"]（含各条目名称）；整体异常 →
     WARNING + 原样返回（管线执行永不因设定组装失败而失败）

RED 形态：C1/C2/C5/C6 FAILED（断言失败：setting 键缺失，AssertionError）；
C3/C4 守护用例 PASS（RED 阶段刻意通过，GREEN 后锁行为）。
C4 说明：execute 前置校验（项目不存在 → AgentServiceError）RED 阶段即生效，
守护锁「项目不存在 → 拒绝执行、无执行记录、管线不执行」。

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
from inkflow.domain.models.character import Character
from inkflow.domain.models.outline import Outline
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.agent_pipeline import (
    PipelineContext,
    PipelineResult,
    PipelineStage,
    StageResult,
    StageStatus,
)
from inkflow.domain.services.agent_service import AgentService, AgentServiceError

pytestmark = pytest.mark.asyncio

# ── 辅助工厂 ────────────────────────────────────────────────────


def _make_project(
    project_id: uuid.UUID | None = None, config: ProjectConfig | None = None
) -> Project:
    """构造测试用 Project 领域对象。"""
    return Project(
        id=project_id or uuid.uuid4(),
        name="测试项目",
        tags=["玄幻"],
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


def _make_character(
    project_id: uuid.UUID | None = None,
    name: str = "角色甲",
    personality: str = "性格描述",
    background: str = "背景设定",
    goals: str = "目标动机",
) -> Character:
    """构造测试用 Character 领域对象（personality/background/goals 内容字段）。"""
    return Character(
        id=uuid.uuid4(),
        project_id=project_id or uuid.uuid4(),
        name=name,
        personality=personality,
        background=background,
        goals=goals,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_world(
    project_id: uuid.UUID | None = None,
    name: str = "世界观条目",
    category: str = "设定",
    content: str = "条目内容",
) -> WorldSetting:
    """构造测试用 WorldSetting 领域对象（category/content 内容字段）。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=project_id or uuid.uuid4(),
        name=name,
        category=category,
        content=content,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_outline(
    project_id: uuid.UUID | None = None,
    name: str = "大纲条目",
    description: str = "大纲描述",
    level: str = "overall",
) -> Outline:
    """构造测试用 Outline 领域对象（description 内容字段）。"""
    return Outline(
        id=uuid.uuid4(),
        project_id=project_id or uuid.uuid4(),
        name=name,
        description=description,
        level=level,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
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
        relations: list | None = None,
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


class MockCharacterRepo:
    """角色仓储 Mock — list 返回预置 Character 列表；fail 非 None 时抛异常（C5 单源失败隔离）。"""

    def __init__(
        self,
        characters: list[Character] | None = None,
        fail: Exception | None = None,
    ) -> None:
        self.characters = characters or []
        self.fail = fail
        self.calls: list[tuple] = []

    async def list(
        self, project_id: int, *args: object, **kwargs: object
    ) -> tuple[list[Character], int]:
        self.calls.append((project_id, args, kwargs))
        if self.fail is not None:
            raise self.fail
        return self.characters, len(self.characters)


class MockWorldRepo:
    """世界观仓储 Mock — list 返回预置 WorldSetting 列表；fail 非 None 时抛异常。"""

    def __init__(
        self,
        settings: list[WorldSetting] | None = None,
        fail: Exception | None = None,
    ) -> None:
        self.settings = settings or []
        self.fail = fail
        self.calls: list[tuple] = []

    async def list(
        self, project_id: int, *args: object, **kwargs: object
    ) -> tuple[list[WorldSetting], int]:
        self.calls.append((project_id, args, kwargs))
        if self.fail is not None:
            raise self.fail
        return self.settings, len(self.settings)


class MockOutlineRepo:
    """大纲仓储 Mock — list 返回预置 Outline 列表；fail 非 None 时抛异常。"""

    def __init__(
        self,
        outlines: list[Outline] | None = None,
        fail: Exception | None = None,
    ) -> None:
        self.outlines = outlines or []
        self.fail = fail
        self.calls: list[tuple] = []

    async def list(
        self, project_id: int, *args: object, **kwargs: object
    ) -> tuple[list[Outline], int]:
        self.calls.append((project_id, args, kwargs))
        if self.fail is not None:
            raise self.fail
        return self.outlines, len(self.outlines)


def _build_service(
    project: Project | None = None,
    chapters: list[Chapter] | None = None,
) -> tuple[AgentService, MockPipeline, MockExecutionStore]:
    """装配 AgentService，全部依赖注入 Mock（不触碰真实 DB / LangGraph）。

    刻意不传 character_repo/world_repo/outline_repo（构造签名向后兼容——
    RED 阶段 __init__ 尚无这些参数）；测试内通过属性注入
    service._character_repo / service._world_repo / service._outline_repo = mock
    覆盖——RED 阶段即生效，GREEN 后 __init__ 设置同名属性被测试赋值覆盖。
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


class TestAgentSettingInjection:
    async def test_c1_write_auto_injects_setting(self):
        """write_auto + 预置角色/世界观/大纲 → 后台组装设定摘要注入 setting 变量。

        RED 预期：FAILED（setting 键缺失，AssertionError）。
        """
        project = _make_project()
        char = _make_character(project_id=project.id, name="林晚")
        world = _make_world(project_id=project.id, name="天玄大陆")
        outline = _make_outline(project_id=project.id, name="主线大纲")
        service, pipeline, _ = _build_service(project=project)
        service._character_repo = MockCharacterRepo([char])
        service._world_repo = MockWorldRepo([world])
        service._outline_repo = MockOutlineRepo([outline])
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_auto",
        )

        result = await service.execute(request)
        assert result["status"] == "pending"

        await asyncio.sleep(0.05)  # 等待后台任务完成
        ctx = pipeline.executed_context
        assert ctx is not None
        assert "setting" in ctx.variables
        assert "林晚" in ctx.variables["setting"]
        assert "天玄大陆" in ctx.variables["setting"]
        assert "主线大纲" in ctx.variables["setting"]

    async def test_c2_write_continue_injects_setting_and_context(self):
        """write_continue + 预置设定 → setting（G1）与 context（#318 前文摘要）双键注入。

        RED 预期：FAILED（setting 键缺失，AssertionError；context 键 #318 已 GREEN）。
        """
        project = _make_project()
        ch1 = _make_chapter(project_id=project.id, title="第一章", order_index=1.0)
        cur = _make_chapter(project_id=project.id, title="第二章", order_index=2.0)
        char = _make_character(project_id=project.id, name="林晚")
        world = _make_world(project_id=project.id, name="天玄大陆")
        outline = _make_outline(project_id=project.id, name="主线大纲")
        service, pipeline, _ = _build_service(project=project, chapters=[ch1, cur])
        summary_svc = MockSummaryService(summaries={ch1.id: "摘要A"})
        service._summary_service = summary_svc
        service._character_repo = MockCharacterRepo([char])
        service._world_repo = MockWorldRepo([world])
        service._outline_repo = MockOutlineRepo([outline])
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_continue",
            chapter_id=cur.id,
        )

        result = await service.execute(request)
        assert result["status"] == "pending"

        await asyncio.sleep(0.05)
        ctx = pipeline.executed_context
        assert ctx is not None
        assert "setting" in ctx.variables
        assert "context" in ctx.variables
        assert "林晚" in ctx.variables["setting"]
        assert "摘要A" in ctx.variables["context"]

    async def test_c3_no_repos_injected_skips(self):
        """三 repo 未注入（构造向后兼容）→ execute 正常、variables 无 setting、管线执行。

        守护用例：RED 阶段即 PASS（未实现注入时也不注入），GREEN 后锁行为。
        """
        project = _make_project()
        service, pipeline, _ = _build_service(project=project)
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_auto",
        )

        result = await service.execute(request)
        assert result["status"] == "pending"

        await asyncio.sleep(0.05)
        ctx = pipeline.executed_context
        assert ctx is not None
        assert "setting" not in ctx.variables
        assert pipeline.execute_called is True

    async def test_c4_project_not_found_guard(self):
        """项目不存在（MockProjectRepo(None)）→ execute 前置校验拒绝（AgentServiceError）。

        守护用例：RED 阶段即 PASS（既有 execute 项目校验），GREEN 后锁行为——
        _assemble_setting_context 对不存在项目也原样返回 variables，且不绕过
        execute 前置校验（无执行记录、管线不执行）。
        """
        project = _make_project()
        service, pipeline, store = _build_service(project=None)
        service._character_repo = MockCharacterRepo([_make_character(project_id=project.id)])
        service._world_repo = MockWorldRepo([_make_world(project_id=project.id)])
        service._outline_repo = MockOutlineRepo([_make_outline(project_id=project.id)])
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_auto",
        )

        with pytest.raises(AgentServiceError):
            await service.execute(request)

        assert pipeline.execute_called is False
        assert store.executions == {}

    async def test_c5_single_source_failure_isolated(self):
        """character_repo.list 抛异常 → 跳过该源，world/outline 仍注入 setting。

        RED 预期：FAILED（setting 键缺失，AssertionError）。
        """
        project = _make_project()
        world = _make_world(project_id=project.id, name="天玄大陆")
        outline = _make_outline(project_id=project.id, name="主线大纲")
        service, pipeline, _ = _build_service(project=project)
        service._character_repo = MockCharacterRepo(
            [_make_character(project_id=project.id, name="不应出现")],
            fail=RuntimeError("角色读取失败"),
        )
        service._world_repo = MockWorldRepo([world])
        service._outline_repo = MockOutlineRepo([outline])
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_auto",
        )

        result = await service.execute(request)
        assert result["status"] == "pending"

        await asyncio.sleep(0.05)
        ctx = pipeline.executed_context
        assert ctx is not None
        assert "setting" in ctx.variables
        assert "不应出现" not in ctx.variables["setting"]
        assert "天玄大陆" in ctx.variables["setting"]
        assert "主线大纲" in ctx.variables["setting"]

    async def test_c6_empty_entries_skipped(self):
        """条目内容字段为空（character personality/world content/outline description）→ 跳过。

        RED 预期：FAILED（setting 键缺失，AssertionError）。
        """
        project = _make_project()
        char_full = _make_character(project_id=project.id, name="林晚", personality="冷静")
        char_empty = _make_character(
            project_id=project.id, name="路人甲", personality="", background="", goals=""
        )
        world_full = _make_world(project_id=project.id, name="天玄大陆", content="灵气复苏")
        world_empty = _make_world(project_id=project.id, name="未分类条目", content="")
        outline_full = _make_outline(project_id=project.id, name="主线大纲", description="主角成长")
        outline_empty = _make_outline(project_id=project.id, name="空大纲", description="")
        service, pipeline, _ = _build_service(project=project)
        service._character_repo = MockCharacterRepo([char_full, char_empty])
        service._world_repo = MockWorldRepo([world_full, world_empty])
        service._outline_repo = MockOutlineRepo([outline_full, outline_empty])
        request = PipelineExecuteRequest(
            project_id=project.id,
            pipeline="builtin:write_auto",
        )

        result = await service.execute(request)
        assert result["status"] == "pending"

        await asyncio.sleep(0.05)
        ctx = pipeline.executed_context
        assert ctx is not None
        assert "setting" in ctx.variables
        assert "林晚" in ctx.variables["setting"]
        assert "天玄大陆" in ctx.variables["setting"]
        assert "主线大纲" in ctx.variables["setting"]
        assert "路人甲" not in ctx.variables["setting"]
        assert "未分类条目" not in ctx.variables["setting"]
        assert "空大纲" not in ctx.variables["setting"]
