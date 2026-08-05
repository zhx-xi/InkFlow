"""SQLiteChapterRepository 单元测试 — in-memory SQLite（Issue #104 Phase 3 覆盖率补齐）。

覆盖 chapter_repo.py 未达分支（行 94/105/169/172→181/204-207/209/237-240）:
- update_volume 落库后读回（scalar_one 路径）
- delete_volume 不存在 → False
- update_chapter 不存在 → ValueError；状态变更追加 history；同状态不追加
- delete_chapter 存在 → True / 不存在 → False
- get_volume_word_count 空项目 → 0（SUM NULL 回退）

Volume/Chapter 基础 CRUD 往返由 tests/integration/test_chapter_repository.py 覆盖，
本文件只补缺口分支（fixture 模式镜像 test_character_repo.py）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.chapter import Chapter, ChapterStatus, Volume
from inkflow.infrastructure.database.models.chapter import VolumeORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.chapter_repo import (
    SQLiteChapterRepository,
)


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（启用 FK 级联）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project(db_session):
    """一个基础项目（卷/章节的 FK 依赖）。"""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _now() -> datetime:
    return datetime.now(UTC)


def _volume(project: ProjectORM, title: str, order_index: float = 0.0) -> Volume:
    """构造待持久化的卷领域对象（id 为随机 UUID，落库后由 DB 自增分配）。"""
    return Volume(
        id=uuid.uuid4(),
        project_id=uuid.UUID(int=project.id),
        title=title,
        order_index=order_index,
    )


def _chapter(project: ProjectORM, title: str, content: str = "测试内容") -> Chapter:
    """构造待持久化的章节领域对象。"""
    return Chapter(
        id=uuid.uuid4(),
        project_id=uuid.UUID(int=project.id),
        title=title,
        content=content,
        created_at=_now(),
        updated_at=_now(),
    )


class TestChapterRepositoryGaps:
    """chapter_repo 缺口分支测试（Issue #104 Phase 3）。"""

    async def test_update_volume_persists_and_reads_back(self, db_session, project):
        """update_volume → commit 后 scalar_one 读回，title/order_index 已更新。"""
        repo = SQLiteChapterRepository(db_session)
        created = await repo.add_volume(_volume(project, "第一卷", 1.0))

        updated = await repo.update_volume(
            Volume(
                id=created.id,
                project_id=created.project_id,
                title="第一卷·修订",
                order_index=2.5,
            )
        )

        assert updated.id == created.id
        assert updated.title == "第一卷·修订"
        assert updated.order_index == 2.5
        # 落库持久化验证：从 DB 直接读回
        orm = (
            await db_session.execute(select(VolumeORM).where(VolumeORM.id == created.id.int))
        ).scalar_one()
        assert orm.title == "第一卷·修订"
        assert orm.order_index == 2.5

    async def test_delete_volume_missing_returns_false(self, db_session, project):
        """delete_volume 不存在的卷 → False（不抛异常）。"""
        repo = SQLiteChapterRepository(db_session)
        assert await repo.delete_volume(999999) is False

    async def test_update_chapter_missing_raises_value_error(self, db_session, project):
        """update_chapter 不存在的章节 → ValueError（Chapter not found）。"""
        repo = SQLiteChapterRepository(db_session)
        ghost = _chapter(project, "幽灵章")
        ghost.id = uuid.UUID(int=999999)  # 仓储层 int id：不存在但落在 SQLite 64 位范围内
        with pytest.raises(ValueError, match="not found"):
            await repo.update_chapter(ghost)

    async def test_update_chapter_same_status_keeps_history_empty(self, db_session, project):
        """update_chapter 状态未变 → 不追加 status_history（172→181 分支）。"""
        repo = SQLiteChapterRepository(db_session)
        created = await repo.add_chapter(_chapter(project, "第一章"))

        updated = await repo.update_chapter(
            Chapter(
                id=created.id,
                project_id=created.project_id,
                title="第一章",
                content="新内容更长了",
                status=ChapterStatus.DRAFT,  # 与落库状态相同
                order_index=created.order_index,
            )
        )

        assert updated.status is ChapterStatus.DRAFT
        assert updated.status_history == []

    async def test_update_chapter_status_change_appends_history(self, db_session, project):
        """update_chapter 状态变更 → status_history 追加 from→to 记录。"""
        repo = SQLiteChapterRepository(db_session)
        created = await repo.add_chapter(_chapter(project, "第一章"))

        updated = await repo.update_chapter(
            Chapter(
                id=created.id,
                project_id=created.project_id,
                title="第一章",
                content="新内容更长了",
                status=ChapterStatus.WRITING,
                order_index=created.order_index,
            )
        )

        assert updated.status is ChapterStatus.WRITING
        assert len(updated.status_history) == 1
        entry = updated.status_history[0]
        assert entry.from_status is ChapterStatus.DRAFT
        assert entry.to_status is ChapterStatus.WRITING
        assert entry.at is not None

    async def test_delete_chapter_existing_then_missing(self, db_session, project):
        """delete_chapter 存在 → True；再删 → False（204→207 分支）。"""
        repo = SQLiteChapterRepository(db_session)
        created = await repo.add_chapter(_chapter(project, "第一章"))

        assert await repo.delete_chapter(created.id.int) is True
        # 物理删除后读回 None
        assert await repo.get_chapter(created.id.int) is None
        assert await repo.delete_chapter(created.id.int) is False

    async def test_get_volume_word_count_empty_returns_zero(self, db_session, project):
        """get_volume_word_count 无章节 → 0（SUM NULL 回退）。"""
        repo = SQLiteChapterRepository(db_session)
        vol = await repo.add_volume(_volume(project, "空卷"))
        assert await repo.get_volume_word_count(vol.id.int) == 0

    async def test_get_volume_word_count_sums_chapters(self, db_session, project):
        """get_volume_word_count 汇总卷内章节 word_count。"""
        repo = SQLiteChapterRepository(db_session)
        vol = await repo.add_volume(_volume(project, "第一卷"))
        ch1 = await repo.add_chapter(
            Chapter(
                id=uuid.UUID(int=1001),
                project_id=uuid.UUID(int=project.id),
                volume_id=vol.id,
                title="第一章",
                content="你好世界 hello world 测试内容",
            )
        )
        ch2 = await repo.add_chapter(
            Chapter(
                id=uuid.UUID(int=1002),
                project_id=uuid.UUID(int=project.id),
                volume_id=vol.id,
                title="第二章",
                content="短内容",
            )
        )

        assert await repo.get_volume_word_count(vol.id.int) == ch1.word_count + ch2.word_count
        # 无卷章节不计入
        await repo.add_chapter(_chapter(project, "无卷章"))
        assert await repo.get_volume_word_count(vol.id.int) == ch1.word_count + ch2.word_count
