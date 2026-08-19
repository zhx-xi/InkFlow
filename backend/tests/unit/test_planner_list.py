"""#486 会话 UI：PlannerSession 列表契约（service + repo 层）。

访谈会话（#475 PlannerSession）需在会话页展示列表——新增
repo.list_planner_sessions + service.list（created_at DESC）。

══════════════════════════════════════════════════════════════════════════
设计假设（实现者以本文件为准）:
- repo（SQLiteBookRepository）新增:
  async def list_planner_sessions(
      project_id: uuid.UUID | None = None,
      status: str | None = None,
      offset: int = 0,
      limit: int = 50,
  ) -> tuple[list[PlannerSession], int]
  语义: created_at DESC；project_id/status 精确过滤；total=未分页过滤总数。
- service（PlannerService）新增:
  async def list(project_id: uuid.UUID | None = None, status: str | None = None,
                 offset: int = 0, limit: int = 50) -> tuple[list[PlannerSession], int]
  关键字透传 self._repo.list_planner_sessions(...)。
- domain/ports/book_repository.py 的 BookRepositoryProtocol 同步增加
  list_planner_sessions 方法（mypy 接线契约）。
══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.services.planner_service import PlannerService
from inkflow.infrastructure.repositories.book_repository import SQLiteBookRepository


def _now() -> datetime:
    """当前 UTC 时间（时区感知）。"""
    return datetime.now(UTC)


def _dt(day: int) -> datetime:
    """构造 2026-01-day 的 UTC 时间（测试固定时间戳）。"""
    return datetime(2026, 1, day, tzinfo=UTC)


def _session(**kw: object) -> PlannerSession:
    """构造 PlannerSession 领域对象（键值覆盖默认值）。"""
    return PlannerSession(
        id=kw.pop("id", uuid.uuid4()),  # type: ignore[misc]
        project_id=kw.pop("project_id", uuid.uuid4()),  # type: ignore[misc]
        status=kw.pop("status", "drafting"),  # type: ignore[misc]
        one_liner=kw.pop("one_liner", "测试一句话"),  # type: ignore[misc]
        round=kw.pop("round", 1),  # type: ignore[misc]
        asked_questions=kw.pop("asked_questions", []),  # type: ignore[misc]
        answers=kw.pop("answers", {}),  # type: ignore[misc]
        authorized=kw.pop("authorized", []),  # type: ignore[misc]
        confirmed_items=kw.pop("confirmed_items", []),  # type: ignore[misc]
        conflicts=kw.pop("conflicts", []),  # type: ignore[misc]
        confirming=kw.pop("confirming", False),  # type: ignore[misc]
        writing_plan_id=kw.pop("writing_plan_id", None),  # type: ignore[misc]
        created_at=kw.pop("created_at", _now()),  # type: ignore[misc]
        updated_at=kw.pop("updated_at", _now()),  # type: ignore[misc]
    )


class TestPlannerServiceList:
    """PlannerService.list 透传契约（#486）。"""

    @pytest.fixture
    def service(self):
        """PlannerService + mock repo（list_planner_sessions 默认空列表）。"""
        repo = MagicMock()
        repo.list_planner_sessions = AsyncMock(return_value=([], 0))
        return PlannerService(repo=repo), repo

    async def test_list_defaults(self, service) -> None:
        """无过滤参数 → repo.list_planner_sessions 默认参数（全量前 50）。"""
        svc, repo = service
        items, total = await svc.list()
        assert items == [] and total == 0
        repo.list_planner_sessions.assert_awaited_once_with(
            project_id=None, status=None, offset=0, limit=50
        )

    async def test_list_filters_passthrough(self, service) -> None:
        """project_id/status/offset/limit 关键字透传。"""
        svc, repo = service
        pid = uuid.uuid4()
        repo.list_planner_sessions = AsyncMock(return_value=([_session(project_id=pid)], 1))
        items, total = await svc.list(project_id=pid, status="completed", offset=10, limit=20)
        assert total == 1
        assert items[0].project_id == pid
        repo.list_planner_sessions.assert_awaited_once_with(
            project_id=pid, status="completed", offset=10, limit=20
        )


class TestBookRepositoryListPlannerSessions:
    """SQLiteBookRepository.list_planner_sessions 集成测试（in-memory SQLite）。"""

    @pytest.fixture
    async def db_session(self):
        """独立 in-memory SQLite — 每个测试一个全新数据库。"""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            yield session
        await engine.dispose()

    async def test_list_planner_sessions_all_sorted_desc(self, db_session) -> None:
        """全量列表：created_at DESC（最新在前）。"""
        repo = SQLiteBookRepository(db_session)
        a = await repo.add_planner_session(_session(created_at=_dt(1)))
        b = await repo.add_planner_session(_session(created_at=_dt(2)))
        c = await repo.add_planner_session(_session(created_at=_dt(3)))

        items, total = await repo.list_planner_sessions()
        assert total == 3
        assert [s.id for s in items] == [c.id, b.id, a.id]

    async def test_list_planner_sessions_filters(self, db_session) -> None:
        """project_id/status 精确过滤。"""
        repo = SQLiteBookRepository(db_session)
        pid = uuid.uuid4()
        await repo.add_planner_session(
            _session(project_id=pid, status="drafting", created_at=_dt(2))
        )
        await repo.add_planner_session(
            _session(project_id=pid, status="completed", created_at=_dt(1))
        )
        await repo.add_planner_session(
            _session(project_id=uuid.uuid4(), status="completed", created_at=_dt(3))
        )

        items, total = await repo.list_planner_sessions(project_id=pid, status="completed")
        assert total == 1
        assert items[0].status == "completed"

        _items2, total2 = await repo.list_planner_sessions(project_id=pid)
        assert total2 == 2

    async def test_list_planner_sessions_pagination(self, db_session) -> None:
        """分页：offset/limit + total=未分页总数。"""
        repo = SQLiteBookRepository(db_session)
        for day in range(1, 4):
            await repo.add_planner_session(_session(created_at=_dt(day)))

        items, total = await repo.list_planner_sessions(offset=0, limit=2)
        assert total == 3
        assert len(items) == 2
        assert items[0].created_at > items[1].created_at
