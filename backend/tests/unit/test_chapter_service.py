"""ChapterService 单元测试 — in-memory SQLite（Phase 3 覆盖率补齐）。

镜像 test_chapter_repo.py 的 fixture 模式：真实 SQLiteChapterRepository +
独立 in-memory 引擎（ChapterService.__init__ 硬编码实例化仓储，故走真实仓储）。
覆盖 chapter_service.py 未达行/分支：
- create_volume / create_chapter 缺省 order_index → get_next_*_order 编排
- create_chapter 显式 order_index → 跳过 next_position 编排
- update_volume / update_chapter 不存在 → None
- get_project_word_count / get_volume_word_count 空项目 → 0、有内容 → 字数
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.chapter import ChapterUpdate, VolumeUpdate
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.infrastructure.database.models.project import ProjectORM


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


@pytest.fixture
async def svc(db_session) -> ChapterService:
    return ChapterService(db_session)


class TestVolumeOps:
    """卷 — 自动排序号 / 部分更新 / 不存在。"""

    async def test_create_volume_auto_order(self, svc, project) -> None:
        """order_index=None → get_next_volume_order 编排（空项目 → 0.0 + 1.0）。"""
        pid = uuid.UUID(int=project.id)
        vol = await svc.create_volume(pid, "第一卷", order_index=None)
        assert vol.project_id == pid
        assert vol.title == "第一卷"
        assert vol.order_index == 1.0

    async def test_create_volume_explicit_order_skips_next(self, svc, project) -> None:
        """显式 order_index → 原样落库，不查询 next_order。"""
        vol = await svc.create_volume(uuid.UUID(int=project.id), "第二卷", order_index=5.0)
        assert vol.order_index == 5.0

    async def test_update_volume_merges_fields(self, svc, project) -> None:
        """部分更新：只改 title，order_index 保持不变。"""
        vol = await svc.create_volume(uuid.UUID(int=project.id), "旧标题")
        updated = await svc.update_volume(vol.id, VolumeUpdate(title="新标题"))
        assert updated is not None
        assert updated.title == "新标题"
        assert updated.order_index == vol.order_index

    async def test_update_volume_missing_returns_none(self, svc) -> None:
        """更新不存在的卷 → None（router 层转 404）。"""
        assert await svc.update_volume(999999, VolumeUpdate(title="x")) is None


class TestChapterOps:
    """章节 — 自动/显式排序号、部分更新、字数统计。"""

    async def test_create_chapter_auto_order(self, svc, project) -> None:
        """order_index=None → get_next_chapter_order 编排（空项目 → 1.0）。"""
        ch = await svc.create_chapter(uuid.UUID(int=project.id), "第一章", order_index=None)
        assert ch.title == "第一章"
        assert ch.order_index == 1.0

    async def test_create_chapter_explicit_order_skips_next(self, svc, project) -> None:
        """显式 order_index → 原样落库。"""
        ch = await svc.create_chapter(uuid.UUID(int=project.id), "第一章", order_index=5.0)
        assert ch.order_index == 5.0

    async def test_create_chapter_with_volume_auto_order(self, svc, project) -> None:
        """挂卷创建章节：volume_id 透传，排序号按卷内追加。"""
        vol = await svc.create_volume(uuid.UUID(int=project.id), "第一卷")
        ch = await svc.create_chapter(uuid.UUID(int=project.id), "第一章", volume_id=vol.id)
        assert ch.volume_id == vol.id
        assert ch.order_index == 1.0

    async def test_update_chapter_merges_fields(self, svc, project) -> None:
        """部分更新：只改 content，title 保持不变。"""
        ch = await svc.create_chapter(uuid.UUID(int=project.id), "第一章", content="旧内容")
        updated = await svc.update_chapter(ch.id, ChapterUpdate(content="新内容"))
        assert updated is not None
        assert updated.content == "新内容"
        assert updated.title == "第一章"

    async def test_update_chapter_missing_returns_none(self, svc) -> None:
        """更新不存在的章节 → None（router 层转 404）。"""
        assert await svc.update_chapter(999999, ChapterUpdate(content="x")) is None


class TestWordCount:
    """项目/卷级字数统计（SUM 聚合）。"""

    async def test_get_project_word_count_empty_is_zero(self, svc, project) -> None:
        assert await svc.get_project_word_count(uuid.UUID(int=project.id).int) == 0

    async def test_get_project_word_count_sums_chapters(self, svc, project) -> None:
        ch = await svc.create_chapter(uuid.UUID(int=project.id), "第一章", content="第一章内容")
        # ⚠️ 补强（#524）：手算值而非 ch.word_count 自引用 —— count_words("第一章内容") = 5
        # （5 个中文字符，无 markdown/英文）
        assert await svc.get_project_word_count(uuid.UUID(int=project.id).int) == 5
        assert ch.word_count > 0

    async def test_get_volume_word_count(self, svc, project) -> None:
        vol = await svc.create_volume(uuid.UUID(int=project.id), "第一卷")
        ch = await svc.create_chapter(
            uuid.UUID(int=project.id), "第一章", volume_id=vol.id, content="测试内容"
        )
        assert await svc.get_volume_word_count(vol.id.int) == ch.word_count
        assert ch.word_count > 0
