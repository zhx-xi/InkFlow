"""#1098 RED 契约测试 — 记忆提取覆盖 agentic 会话（session 域 → memory 事件源扩展）.

依据: specs/f28-memory-learning/spec.md §5.7.1「agentic 会话事件源（#1098 扩展，
2026-09-11）」；真实 in-memory SQLite 轨，镜像 tests/unit/infrastructure/database/
test_memory_event_repo.py + test_session_repo.py 的 fixture 形态（真实 repo + 真实 DB）。

缺陷根因（父侧已实证，本文件勿重新推导）
----------------------------------------
`memory_events` 的**唯一写入方**是 draft 域（DraftService.update/confirm/reject）。
只有 agentic/planner/执行会话、零写作草稿编辑的项目 → memory_events 恒 0 行 →
`stats.agentic.chapters == 0` 且 `summarize` 锚点为空 → GUI「提取记忆」恒 toast
「暂无可提取的记忆内容」（即使项目里已有大量会话产出）。

已拍板契约（spec §5.7.1，GREEN 按此实现；本文件只断言不设计）
------------------------------------------------------------
1. `MemoryEventType` 新增 `SESSION_COMPLETED = "session_completed"`，复用既有
   memory_events 列（不新增 ORM 列）——`draft_id` 承载 session id 字符串、
   `chapter_id` 可空、`before_content=None`、`after_content` 承载可提取文本；
2. 捕获点 = `SessionService.complete`（正常完成）与 `SessionService.fail`
   （error 非空才落）；
3. 捕获条件 = `memory_learning=true` 且会话 `project_id` 非 None（全局会话零行为）；
4. `stats.agentic.chapters = draft_confirmed + draft_rejected + session_completed`；
5. 锚点扩展 = `session_completed` 事件的 `after_content` 参与 summarize 项目级
   可提取锚点集（「仅有会话、零写作编辑」的项目 summarized 不再恒 False）。

测试侧钉死的装配形态（不锁 GREEN 的内部实现细节）
------------------------------------------------
- 会话侧：经 `inkflow.api.deps.get_session_service(db)`（**既有 DI 工厂**，签名不变）
  装配 SessionService → create/add_log/complete（或 fail）驱动会话完成路径。
  这样断言「会话完成后事件落库」而不锁 SessionService 新增依赖的参数名
  （工厂内部怎么把 memory 侧塞进 SessionService 由 GREEN 决定）。
- 记忆侧：`MemoryService` 真实构造（preference/event/project/summary 四 repo 全部
  真实 SQLite 实现），仅 `summarizer` 用 fake（隔离 LLM），`learner` 用
  FakeLearner（anchor_hash 指纹宽松——锚点对象有 .value 用 .value，否则 str()；
  不锁 GREEN 造出的会话锚点类型）。
- fake summarizer 复刻真实管线关键语义：**锚点为空 → 不调 LLM，直接 (None, 0)**
  （这正是 #1098 根因链上「暂无可提取的记忆内容」的判据），返回产物为真实
  `SemanticSummary` 领域对象以喂真实 summary repo 的 upsert。

RED 预期（当前实现下）
----------------------
FAILED（RED，本次要的）:
- N1  `test_stats_counts_agentic_task_session_completion` —— 会话完成无接线 → chapters 0；
- N1d `test_stats_counts_writing_session_completion` —— 同上（writing 会话范围）；
- N1b `test_stats_counts_session_completed_event` —— `MemoryEventType.SESSION_COMPLETED`
       缺失 → 用例体 AttributeError；
- N1c `test_session_fail_also_captured_as_event` —— 同上（fail 路径无接线）；
- N2  `test_summarize_anchors_include_session_conclusion` —— 锚点空 → fake 未真调
       （llm_calls == 0）→ summarized=False；
- N2b `test_summarize_anchors_include_session_completed_event` —— 枚举缺失。
PASS（护栏，当前即绿，GREEN 后必须保持绿）:
- N3  draft 域口径不回归；N3b 写作偏好锚点路径不回归；N4 空项目可读提示保留；
  N4b 全局会话零行为；N5 memory_learning=false 零行为。

asyncio 模式: pyproject asyncio_mode = "auto"；文件级 pytest.mark.asyncio 双保险。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.api.deps import get_session_service
from inkflow.core.database import Base
from inkflow.domain.models.memory_event import MemoryEventType
from inkflow.domain.models.preference import PreferenceCategory
from inkflow.domain.models.semantic_summary import SemanticSummary, SummaryScope
from inkflow.domain.models.session import (
    SessionComplete,
    SessionCreate,
    SessionFail,
    SessionLogCreate,
    SessionType,
)
from inkflow.domain.services.memory_service import MemoryService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# 会话结论文本（可提取锚点素材；同时写入 result 与日志，免锁 GREEN 的提取来源）
CONCLUSION_TEXT = "会话结论：称呼主角统一使用全名而不是代词。"


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库.

    ORM 惰性导入必须在 create_all 之前——`inkflow.infrastructure.database.models`
    包 import 注册大部分表；preference（memory_events/project_preferences）与
    semantic_summary 不在包内，需显式导入（否则 create_all 不建表）。
    """

    import inkflow.infrastructure.database.models  # noqa: F401  # 注册全部 ORM（create_all 需要）
    from inkflow.infrastructure.database.models.preference import (  # noqa: F401  # 注册 memory_events/project_preferences 表
        MemoryEventORM,
        ProjectPreferenceORM,
    )
    from inkflow.infrastructure.database.models.semantic_summary import (  # noqa: F401  # 注册 semantic_summaries 表
        SemanticSummaryORM,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _uuid(int_id: int) -> uuid.UUID:
    """小整数构造领域 UUID（禁 uuid4().int 落库——SQLite INTEGER 64 位溢出）。"""
    return uuid.UUID(int=int_id)


async def _make_project(db_session: AsyncSession, *, learning: bool = True) -> uuid.UUID:
    """落一个项目行（真实 projects 表），返回其领域 UUID（= ORM 自增 int）."""
    from inkflow.infrastructure.database.models.project import ProjectORM

    orm = ProjectORM(
        name="会话记忆覆盖项目",
        config={"extra": {"memory_learning": learning}},
    )
    db_session.add(orm)
    await db_session.commit()
    await db_session.refresh(orm)
    return _uuid(orm.id)


async def _create_event(
    db_session: AsyncSession,
    *,
    project_id: uuid.UUID,
    event_type: MemoryEventType,
    draft_id: str | None = None,
    before: str | None = None,
    after: str | None = None,
):
    """经真实 event repo 落一条事件（diff_chars 由 repo 内部计算）."""
    from inkflow.infrastructure.database.repositories.memory_event_repo import (
        SQLiteMemoryEventRepository,
    )

    return await SQLiteMemoryEventRepository(db_session).create(
        project_id=project_id,
        draft_id=draft_id,
        chapter_id=None,
        agent_run_id=None,
        event_type=event_type,
        before_content=before,
        after_content=after,
    )


async def _event_count(db_session: AsyncSession, project_id: uuid.UUID) -> int:
    """直查 memory_events 行数（护栏用例用；不依赖被测服务）."""
    from inkflow.infrastructure.database.models.preference import MemoryEventORM

    result = await db_session.execute(
        select(func.count())
        .select_from(MemoryEventORM)
        .where(MemoryEventORM.project_id == str(project_id))
    )
    return int(result.scalar_one())


async def _complete_task_session(
    db_session: AsyncSession,
    project_id: uuid.UUID,
    *,
    title: str = "第三章 agentic 写作任务",
) -> uuid.UUID:
    """经 **既有 DI 工厂** 装配 SessionService 完成一个 task 会话，返回 session 领域 UUID."""
    svc = get_session_service(db_session)
    view = await svc.create(
        SessionCreate(session_type=SessionType.TASK, project_id=project_id, title=title)
    )
    await svc.add_log(
        view.session.id,
        SessionLogCreate(message="已产出第三章初稿。" + CONCLUSION_TEXT),
    )
    await svc.complete(
        view.session.id,
        SessionComplete(result={"summary": CONCLUSION_TEXT}),
    )
    return view.session.id


class FakeLearner:
    """anchor_hash 指纹（宽松：锚点有 .value 用 .value，否则 str()）——不锁锚点类型."""

    def __init__(self) -> None:
        self.hash_inputs: list[list[Any]] = []

    def anchor_hash(self, anchors: Any) -> str:
        items = list(anchors or [])
        self.hash_inputs.append(items)
        keys = sorted(getattr(a, "value", str(a)) for a in items)
        return hashlib.sha256("\n".join(keys).encode()).hexdigest()

    def aggregate_candidates(self, events: Any) -> list:
        """summarize 路径不调用（record_draft_edit 才用）；提供以满足鸭子契约."""
        return []

    def confidence_for(self, count: int) -> float:
        return 1 - 1 / (count + 1)


class FakeSummarizer:
    """summarizer 鸭子：async summarize(anchors, *, scope, project_id, anchor_hash, model).

    复刻真实管线关键语义: **锚点为空 → 不调 LLM，直接 (None, 0)**（#1098 根因链上的
    「暂无可提取的记忆内容」判据）；锚点非空 → 产出真实 SemanticSummary 领域对象。
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.llm_calls = 0
        self.empty_calls = 0

    async def summarize(
        self,
        anchors: Any,
        *,
        scope: SummaryScope,
        project_id: uuid.UUID | None,
        anchor_hash: str,
        model: str | None,
    ) -> tuple[SemanticSummary | None, int]:
        items = list(anchors or [])
        self.calls.append({"anchors": items, "scope": scope, "project_id": project_id})
        if not items:
            self.empty_calls += 1
            return (None, 0)
        self.llm_calls += 1
        now = datetime.now(UTC)
        return (
            SemanticSummary(
                id=str(uuid.uuid4()),
                scope=SummaryScope(scope),
                project_id=project_id,
                content="叙述偏好：称呼主角统一使用全名。",
                anchor_hash=anchor_hash,
                anchor_count=len(items),
                model=model or "test-model",
                created_at=now,
                updated_at=now,
            ),
            0,
        )


def _memory_service(
    db_session: AsyncSession,
    summarizer: FakeSummarizer,
    learner: FakeLearner | None = None,
) -> MemoryService:
    """真实 repo + 真实 DB 装配 MemoryService（仅 summarizer/learner 为 fake）."""
    from inkflow.infrastructure.database.repositories.memory_event_repo import (
        SQLiteMemoryEventRepository,
    )
    from inkflow.infrastructure.database.repositories.preference_repo import (
        SQLitePreferenceRepository,
    )
    from inkflow.infrastructure.database.repositories.project_repo import (
        SQLiteProjectRepository,
    )
    from inkflow.infrastructure.database.repositories.semantic_summary_repo import (
        SQLiteSemanticSummaryRepository,
    )

    return MemoryService(
        preference_repo=SQLitePreferenceRepository(db_session),
        event_repo=SQLiteMemoryEventRepository(db_session),
        project_repo=SQLiteProjectRepository(db_session),
        learner=learner if learner is not None else FakeLearner(),
        summary_repo=SQLiteSemanticSummaryRepository(db_session),
        summarizer=summarizer,
        llm_default_model="test-model",
    )


# ── N1/N1b/N1c: agentic 会话 → 事件源 → stats 口径（RED）──


async def test_stats_counts_agentic_task_session_completion(db_session) -> None:
    """N1（RED）: 仅有 agentic 会话（session_type=task）的项目，会话完成后
    `stats.agentic.chapters > 0`（口径 = confirmed + rejected + session_completed）."""
    pid = await _make_project(db_session)
    await _complete_task_session(db_session, pid)

    stats = await _memory_service(db_session, FakeSummarizer()).stats(pid)

    assert stats["project_id"] == str(pid)
    assert stats["agentic"]["chapters"] > 0


async def test_stats_counts_writing_session_completion(db_session) -> None:
    """N1d（RED）: 会话范围 = {writing, task} 全路径统一（spec §5.7.1「避免按类型分叉」）——
    writing 会话完成同样计入 agentic.chapters."""
    pid = await _make_project(db_session)
    svc = get_session_service(db_session)
    view = await svc.create(
        SessionCreate(session_type=SessionType.WRITING, project_id=pid, title="第二章写作会话")
    )
    await svc.add_log(
        view.session.id, SessionLogCreate(message="写作会话日志。" + CONCLUSION_TEXT)
    )
    await svc.complete(view.session.id, SessionComplete(result={"summary": CONCLUSION_TEXT}))

    stats = await _memory_service(db_session, FakeSummarizer()).stats(pid)

    assert stats["agentic"]["chapters"] > 0


async def test_stats_counts_session_completed_event(db_session) -> None:
    """N1b（RED）: `session_completed` 事件本身计入 agentic.chapters（读路径口径）."""
    pid = await _make_project(db_session)
    await _create_event(
        db_session,
        project_id=pid,
        event_type=MemoryEventType.SESSION_COMPLETED,
        draft_id="session-1",
        after=CONCLUSION_TEXT,
    )

    stats = await _memory_service(db_session, FakeSummarizer()).stats(pid)

    assert stats["agentic"]["chapters"] == 1
    assert stats["agentic"]["direct_confirms"] == 0
    assert stats["agentic"]["regenerate_rate"] == 0.0


async def test_session_fail_also_captured_as_event(db_session) -> None:
    """N1c（RED）: 会话失败（error 非空）同样落事件 → chapters > 0（spec §5.7.1 表第 2 行）."""
    pid = await _make_project(db_session)
    svc = get_session_service(db_session)
    view = await svc.create(
        SessionCreate(session_type=SessionType.TASK, project_id=pid, title="第四章 agentic 执行")
    )
    await svc.fail(view.session.id, SessionFail(error="LLM 超时"))

    assert await _event_count(db_session, pid) > 0
    stats = await _memory_service(db_session, FakeSummarizer()).stats(pid)
    assert stats["agentic"]["chapters"] > 0


# ── N2/N2b: 锚点扩展 → summarize 不再空锚点（RED）──


async def test_summarize_anchors_include_session_conclusion(db_session) -> None:
    """N2（RED）: 仅有 agentic 会话（零写作编辑）的项目 summarize 锚点非空 ——
    fake summarizer 真被调用（llm_calls >= 1、无空锚点调用）+ summarized=True
    + project 层非 None."""
    pid = await _make_project(db_session)
    await _complete_task_session(db_session, pid)

    summarizer = FakeSummarizer()
    result = await _memory_service(db_session, summarizer).summarize(pid)

    assert summarizer.llm_calls >= 1
    assert summarizer.empty_calls == 0
    assert result["summarized"] is True
    assert result["project"] is not None


async def test_summarize_anchors_include_session_completed_event(db_session) -> None:
    """N2b（RED）: 直接落一条 session_completed 事件（after_content 承载结论）→
    summarize 项目级锚点非空（读路径隔离——不依赖 N1/N2 的接线猜测）."""
    pid = await _make_project(db_session)
    await _create_event(
        db_session,
        project_id=pid,
        event_type=MemoryEventType.SESSION_COMPLETED,
        draft_id="session-2",
        after=CONCLUSION_TEXT,
    )

    summarizer = FakeSummarizer()
    result = await _memory_service(db_session, summarizer).summarize(pid)

    assert summarizer.llm_calls >= 1
    assert result["summarized"] is True
    assert result["project"] is not None


# ── N3/N3b: draft 域既有语义不回归（护栏，当前即绿）──


async def test_stats_draft_path_no_regression(db_session) -> None:
    """N3（护栏）: draft 口径不回归 —— chapters = confirmed + rejected（edited 不计入），
    edited 只贡献 avg_diff_chars."""
    pid = await _make_project(db_session)
    before, after = "他说道。", "他低声说道。"
    await _create_event(
        db_session,
        project_id=pid,
        event_type=MemoryEventType.DRAFT_EDITED,
        draft_id="draft-1",
        before=before,
        after=after,
    )
    await _create_event(
        db_session,
        project_id=pid,
        event_type=MemoryEventType.DRAFT_CONFIRMED,
        draft_id="draft-2",
    )
    await _create_event(
        db_session,
        project_id=pid,
        event_type=MemoryEventType.DRAFT_REJECTED,
        draft_id="draft-3",
    )

    stats = await _memory_service(db_session, FakeSummarizer()).stats(pid)

    assert stats["agentic"]["chapters"] == 2
    assert stats["agentic"]["direct_confirms"] == 1
    assert stats["agentic"]["modify_rate"] == pytest.approx(0.5)
    assert stats["agentic"]["regenerate_rate"] == pytest.approx(0.5)
    assert stats["agentic"]["avg_diff_chars"] == len(after) - len(before)


async def test_summarize_preference_anchor_path_no_regression(db_session) -> None:
    """N3b（护栏）: 写作编辑路径（project_preferences 有锚点）→ summarize 正常产出."""
    from inkflow.infrastructure.database.repositories.preference_repo import (
        SQLitePreferenceRepository,
    )

    pid = await _make_project(db_session)
    await SQLitePreferenceRepository(db_session).create(
        project_id=pid,
        category=PreferenceCategory.STYLE_WORD,
        pattern="说",
        value="低声道",
        confidence=0.67,
        count=2,
        source_events=["evt-1"],
    )

    summarizer = FakeSummarizer()
    result = await _memory_service(db_session, summarizer).summarize(pid)

    assert summarizer.llm_calls == 1
    assert summarizer.calls[0]["anchors"]  # 锚点非空（偏好来源）
    assert result["summarized"] is True
    assert result["project"] is not None


# ── N4/N4b/N5: 零行为与可读提示保留（护栏，当前即绿）──


async def test_empty_project_zero_and_readable_hint(db_session) -> None:
    """N4（护栏）: 空项目（无会话、无事件）→ chapters == 0 且 summarize 保留可读提示
    （summarized=False / project=None / user=None；GUI 文案「暂无可提取的记忆内容」不动）."""
    pid = await _make_project(db_session)
    summarizer = FakeSummarizer()
    svc = _memory_service(db_session, summarizer)

    stats = await svc.stats(pid)
    result = await svc.summarize(pid)

    assert stats["agentic"]["chapters"] == 0
    assert result["summarized"] is False
    assert result["project"] is None
    assert result["user"] is None
    assert summarizer.llm_calls == 0


async def test_global_session_without_project_writes_no_event(db_session) -> None:
    """N4b（护栏）: 全局会话（project_id=None）完成 → 零事件（捕获条件：项目非 None）."""
    from inkflow.infrastructure.database.models.preference import MemoryEventORM

    svc = get_session_service(db_session)
    view = await svc.create(SessionCreate(session_type=SessionType.TASK, title="全局任务会话"))
    await svc.complete(
        view.session.id, SessionComplete(result={"summary": CONCLUSION_TEXT})
    )

    total = (
        await db_session.execute(select(func.count()).select_from(MemoryEventORM))
    ).scalar_one()
    assert int(total) == 0


async def test_learning_disabled_session_completion_writes_no_event(db_session) -> None:
    """N5（护栏）: memory_learning=false → 会话完成零行为（不落事件、chapters 仍 0）."""
    pid = await _make_project(db_session, learning=False)
    await _complete_task_session(db_session, pid)

    assert await _event_count(db_session, pid) == 0
    stats = await _memory_service(db_session, FakeSummarizer()).stats(pid)
    assert stats["agentic"]["chapters"] == 0
