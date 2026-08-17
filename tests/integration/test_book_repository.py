"""F44 阶段1 书级仓储集成测试（TDD RED 阶段）。

权威来源：specs/f44-long-task-orchestrator/spec.md §2.1（WritingPlan）、
§2.2（PlannerSession）、§8.1（infrastructure/database/models/writing_plan.py +
planner_session.py + infrastructure/repositories/book_repository.py）、
§13.1 M3（WritingPlan/PlannerSession 落库）。
本文件为仓储层（ORM + repo 实现）定义集成契约，in-memory SQLite 真实落库。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【ORM 契约】
   - `inkflow.infrastructure.database.models.writing_plan.WritingPlanORM`
     （`writing_plans` 表）：字段 id(uuid str 主键)/project_id/title/status/
     root_outline_id(可空)/character_ids(LenientJSON)/limits(LenientJSON)/
     progress(LenientJSON)/execution_refs(LenientJSON)/thread_id(可空)/
     created_at/updated_at——字符 JSON 列形态镜像 AgentORM.tool_ids 先例
   - `inkflow.infrastructure.database.models.planner_session.PlannerSessionORM`
     （`planner_sessions` 表）：id/project_id/status/one_liner/round/
     asked_questions(LenientJSON)/answers(LenientJSON)/authorized(LenientJSON)/
     writing_plan_id(可空)/created_at/updated_at
   - 两表须在 `infrastructure/database/models/__init__.py` 注册
     （import 触发 Base.metadata.create_all 自动建表）

2. 【repo 契约】`inkflow.infrastructure.repositories.book_repository`
   暴露 `SQLiteBookRepository(db_session)`，实现 domain/ports/book_repository.py
   的 BookRepositoryProtocol：
   - add_writing_plan(plan) -> WritingPlan（落库后回填时间戳）
   - get_writing_plan(plan_id) -> WritingPlan | None（uuid4 字符串查询）
   - update_writing_plan(plan) -> None（全字段覆盖写回）
   - add_planner_session(session) -> PlannerSession
   - get_planner_session(session_id) -> PlannerSession | None
   - update_planner_session(session) -> None
   ORM ↔ 领域转换（_orm_to_domain/_domain_to_orm）放 repositories 层
   （F9 教训：防 ruff F821/UP037）。

3. 【端口契约】`inkflow.domain.ports.book_repository` 暴露
   `BookRepositoryProtocol(Protocol)`，方法签名与上方 repo 契约一致
   （鸭子类型，供 domain service 依赖注入）。

4. 【RED 预期形态】ORM/repo 模块不存在 → 本文件收集期 ImportError
   （ModuleNotFoundError）。

5. 【fixture】用 tests/conftest.py 的 `db_session`（function-scoped in-memory
   SQLite，Base.metadata.create_all 自动建表）。
"""

import uuid
from datetime import UTC, datetime

import pytest

from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.models.writing_plan import WritingPlan
from inkflow.domain.ports.book_repository import BookRepositoryProtocol
from inkflow.infrastructure.repositories.book_repository import SQLiteBookRepository


def _utcnow() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def repo(db_session):
    return SQLiteBookRepository(db_session)


# ── WritingPlan 落库 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_get_writing_plan(repo):
    """add → get 回读（§13.1 M3：WritingPlan 落库）。"""
    plan = WritingPlan(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="测试计划",
        status="ready",
        root_outline_id=uuid.uuid4(),
        character_ids=[uuid.uuid4()],
        limits={"max_chapters": 1, "max_agent_calls": 1},
        progress={"c1": "done"},
        execution_refs={"c1": "exec-1"},
        thread_id="thread-1",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )

    saved = await repo.add_writing_plan(plan)

    assert saved.id == plan.id
    got = await repo.get_writing_plan(plan.id)
    assert got is not None
    assert got.title == "测试计划"
    assert got.status == "ready"
    assert got.root_outline_id == plan.root_outline_id
    assert got.character_ids == plan.character_ids
    assert got.limits == {"max_chapters": 1, "max_agent_calls": 1}
    assert got.progress == {"c1": "done"}
    assert got.execution_refs == {"c1": "exec-1"}
    assert got.thread_id == "thread-1"


@pytest.mark.asyncio
async def test_get_missing_writing_plan(repo):
    """get 不存在 → None。"""
    assert await repo.get_writing_plan(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_update_writing_plan(repo):
    """update 全字段覆盖写回（进度/执行引用随执行漂移）。"""
    plan = WritingPlan(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="初始",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    await repo.add_writing_plan(plan)

    plan.status = "running"
    plan.progress["c1"] = "in_progress"
    plan.execution_refs["c1"] = "exec-9"
    plan.updated_at = _utcnow()
    await repo.update_writing_plan(plan)

    got = await repo.get_writing_plan(plan.id)
    assert got is not None
    assert got.status == "running"
    assert got.progress == {"c1": "in_progress"}
    assert got.execution_refs == {"c1": "exec-9"}


# ── PlannerSession 落库 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_get_planner_session(repo):
    """add → get 回读（§13.1 M3：PlannerSession 落库）。"""
    session = PlannerSession(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status="drafting",
        one_liner="写一本关于时间旅者的悬疑小说",
        round=1,
        asked_questions=[{"id": "q1", "text": "题材？", "template": "___"}],
        answers={"q1": "悬疑"},
        authorized=["配角自定"],
        writing_plan_id=None,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )

    saved = await repo.add_planner_session(session)

    assert saved.id == session.id
    got = await repo.get_planner_session(session.id)
    assert got is not None
    assert got.status == "drafting"
    assert got.one_liner == "写一本关于时间旅者的悬疑小说"
    assert got.round == 1
    assert got.asked_questions == [{"id": "q1", "text": "题材？", "template": "___"}]
    assert got.answers == {"q1": "悬疑"}
    assert got.authorized == ["配角自定"]
    assert got.writing_plan_id is None


@pytest.mark.asyncio
async def test_get_missing_planner_session(repo):
    """get 不存在 → None。"""
    assert await repo.get_planner_session(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_update_planner_session(repo):
    """update 覆盖写回（轮次/回答/授权/关联计划漂移）。"""
    session = PlannerSession(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        one_liner="一句话",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    await repo.add_planner_session(session)

    session.status = "completed"
    session.round = 2
    session.answers = {"q1": "悬疑"}
    session.authorized = ["配角自定"]
    session.writing_plan_id = uuid.uuid4()
    session.updated_at = _utcnow()
    await repo.update_planner_session(session)

    got = await repo.get_planner_session(session.id)
    assert got is not None
    assert got.status == "completed"
    assert got.round == 2
    assert got.answers == {"q1": "悬疑"}
    assert got.authorized == ["配角自定"]
    assert got.writing_plan_id == session.writing_plan_id


# ── 端口契约存在性 ────────────────────────────────────────────────


def test_book_repository_protocol_exists():
    """BookRepositoryProtocol 可被 service 依赖注入（鸭子类型契约）。"""
    assert callable(BookRepositoryProtocol.add_writing_plan)
    assert callable(BookRepositoryProtocol.get_writing_plan)
    assert callable(BookRepositoryProtocol.update_writing_plan)
    assert callable(BookRepositoryProtocol.add_planner_session)
    assert callable(BookRepositoryProtocol.get_planner_session)
    assert callable(BookRepositoryProtocol.update_planner_session)


# ── Coverage-Gap 补测（2026-08-17 CI coverage-backend 98.39% 缺口）──


@pytest.mark.asyncio
async def test_update_writing_plan_missing_noop(repo):
    """update 不存在计划 → no-op 不炸（repo 查无分支）。"""
    plan = WritingPlan(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="不存在",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    await repo.update_writing_plan(plan)  # 不抛即通过


@pytest.mark.asyncio
async def test_update_planner_session_missing_noop(repo):
    """update 不存在会话 → no-op 不炸（repo 查无分支）。"""
    session = PlannerSession(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        one_liner="不存在",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    await repo.update_planner_session(session)  # 不抛即通过


@pytest.mark.asyncio
async def test_orm_default_utcnow(db_session):
    """ORM 未显式传 created_at → default=_utcnow 生效（模型默认分支）。

    SQLAlchemy Python 端 default 在 flush 时调用——先 add+flush 再断言。
    """
    from inkflow.infrastructure.database.models.planner_session import PlannerSessionORM
    from inkflow.infrastructure.database.models.writing_plan import WritingPlanORM

    wp = WritingPlanORM(
        id=str(uuid.uuid4()), project_id=str(uuid.uuid4()), title="默认时间"
    )
    ps = PlannerSessionORM(
        id=str(uuid.uuid4()), project_id=str(uuid.uuid4()), one_liner="默认时间"
    )
    db_session.add_all([wp, ps])
    await db_session.flush()

    assert wp.created_at is not None
    assert wp.updated_at is not None
    assert ps.created_at is not None
    assert ps.updated_at is not None

    # __repr__ 分支（LenientJSON/时间戳不影响）
    assert "WritingPlanORM" in repr(wp)
    assert "PlannerSessionORM" in repr(ps)
