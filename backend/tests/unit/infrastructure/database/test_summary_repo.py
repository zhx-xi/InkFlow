"""SummaryRepository 集成测试 — in-memory SQLite（Phase 2a RED→GREEN）.

覆盖 SQLiteSummaryRepository 的 get / upsert / list_recent：
- upsert 插入新记录（chapter_id 唯一约束，每章一条）
- upsert 更新已有记录（同一 chapter_id，不产生新行）
- get 对缺失章节返回 None
- list_recent 按 chapter_index 倒序返回，支持 limit 与 project_id 过滤
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.context import ChapterSummary
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.context import ChapterSummaryORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.summary_repo import SQLiteSummaryRepository


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project_and_chapters(db_session):
    """1 个项目 + 3 个章节（order_index 1.0 / 2.0 / 3.0）."""
    project = ProjectORM(name="测试项目")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    chapters = []
    for idx in (1.0, 2.0, 3.0):
        ch = ChapterORM(
            project_id=project.id,
            title=f"第 {int(idx)} 章",
            content="",
            status="draft",
            word_count=0,
            order_index=idx,
        )
        db_session.add(ch)
        await db_session.commit()
        await db_session.refresh(ch)
        chapters.append(ch)
    return project, chapters


@pytest.mark.integration
class TestSummaryRepository:
    """SQLiteSummaryRepository 集成测试."""

    async def test_upsert_creates_new_record(self, db_session, project_and_chapters):
        """upsert 对无摘要章节插入新记录."""
        _, chapters = project_and_chapters
        repo = SQLiteSummaryRepository(db_session)

        summary = await repo.upsert(chapters[0].id, "第一章摘要", "deepseek-v4-flash")

        assert isinstance(summary, ChapterSummary)
        assert summary.chapter_id == uuid.UUID(int=chapters[0].id)
        assert summary.summary == "第一章摘要"
        assert summary.model == "deepseek-v4-flash"
        assert isinstance(summary.id, uuid.UUID)
        assert isinstance(summary.created_at, str)
        assert isinstance(summary.updated_at, str)

        # 持久化验证：直接查表
        result = await db_session.execute(
            select(ChapterSummaryORM).where(ChapterSummaryORM.chapter_id == chapters[0].id)
        )
        orm = result.scalar_one()
        assert orm.summary == "第一章摘要"

    async def test_upsert_updates_existing_record(self, db_session, project_and_chapters):
        """upsert 对已有摘要章节更新 summary/model，不产生新行."""
        _, chapters = project_and_chapters
        repo = SQLiteSummaryRepository(db_session)

        first = await repo.upsert(chapters[0].id, "旧摘要", "model-a")
        second = await repo.upsert(chapters[0].id, "新摘要", "model-b")

        assert second.id == first.id
        assert second.chapter_id == first.chapter_id
        assert second.summary == "新摘要"
        assert second.model == "model-b"
        assert second.updated_at >= first.updated_at

        count = await db_session.execute(select(func.count()).select_from(ChapterSummaryORM))
        assert count.scalar_one() == 1

    async def test_get_returns_none_for_missing(self, db_session, project_and_chapters):
        """get 对无摘要章节返回 None."""
        _, chapters = project_and_chapters
        repo = SQLiteSummaryRepository(db_session)

        assert await repo.get(chapters[2].id) is None

    async def test_list_recent_orders_by_chapter_index_desc(self, db_session, project_and_chapters):
        """list_recent 按 chapter_index 倒序返回项目摘要."""
        project, chapters = project_and_chapters
        repo = SQLiteSummaryRepository(db_session)
        for ch in chapters:
            await repo.upsert(ch.id, f"摘要-{int(ch.order_index)}", "model")

        recent = await repo.list_recent(project.id, limit=10)

        assert [s.chapter_id for s in recent] == [
            uuid.UUID(int=chapters[2].id),
            uuid.UUID(int=chapters[1].id),
            uuid.UUID(int=chapters[0].id),
        ]
        assert [s.summary for s in recent] == ["摘要-3", "摘要-2", "摘要-1"]

    async def test_list_recent_filters_by_project_and_limit(self, db_session, project_and_chapters):
        """list_recent 支持 limit 截断与 project_id 过滤."""
        project, chapters = project_and_chapters
        repo = SQLiteSummaryRepository(db_session)
        for ch in chapters:
            await repo.upsert(ch.id, "摘要", "model")

        limited = await repo.list_recent(project.id, limit=2)
        assert len(limited) == 2
        assert limited[0].chapter_id == uuid.UUID(int=chapters[2].id)
        assert limited[1].chapter_id == uuid.UUID(int=chapters[1].id)

        # 其他项目没有摘要
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        assert await repo.list_recent(other.id) == []
