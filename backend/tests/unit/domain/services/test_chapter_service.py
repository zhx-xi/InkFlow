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
from inkflow.domain.services.chapter_service import (
    ChapterService,
    VolumeMoveError,
    VolumeNotEmptyError,
)
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


class TestDeleteVolume:
    """卷删除 — #648 delete_volume 全分支覆盖（overflow/not-found/empty/cascade/move/raise）。"""

    @pytest.mark.asyncio
    async def test_delete_volume_overflow_vid_returns_false(self, svc) -> None:
        """vid > 2**63-1 → 守卫直接返回 False，不查库。"""
        assert await svc.delete_volume(2**63) is False

    @pytest.mark.asyncio
    async def test_delete_volume_not_found_returns_false(self, svc) -> None:
        """卷不存在 → 返回 False。"""
        assert await svc.delete_volume(999999) is False

    @pytest.mark.asyncio
    async def test_delete_volume_empty_volume_true(self, svc, project) -> None:
        """空卷 → 删除成功且卷已消失。"""
        vol = await svc.create_volume(uuid.UUID(int=project.id), "空卷")
        assert await svc.delete_volume(vol.id) is True
        assert await svc.get_volume(vol.id) is None

    @pytest.mark.asyncio
    async def test_delete_volume_cascade_deletes_chapters(self, svc, project) -> None:
        """级联删除：卷下 2 章全部删除，卷一并删除。"""
        pid = uuid.UUID(int=project.id)
        vol = await svc.create_volume(pid, "级联卷")
        ch1 = await svc.create_chapter(pid, "章一", volume_id=vol.id)
        ch2 = await svc.create_chapter(pid, "章二", volume_id=vol.id)
        assert await svc.delete_volume(vol.id, delete_chapters=True) is True
        assert await svc.get_volume(vol.id) is None
        assert await svc.get_chapter(ch1.id) is None
        assert await svc.get_chapter(ch2.id) is None

    @pytest.mark.asyncio
    async def test_delete_volume_move_to_target(self, svc, project) -> None:
        """移动到目标卷：章节改挂 v2，源卷删除。"""
        pid = uuid.UUID(int=project.id)
        v1 = await svc.create_volume(pid, "源卷")
        v2 = await svc.create_volume(pid, "目标卷")
        ch1 = await svc.create_chapter(pid, "章一", volume_id=v1.id)
        ch2 = await svc.create_chapter(pid, "章二", volume_id=v1.id)
        assert await svc.delete_volume(v1.id, move_to=v2.id) is True
        assert await svc.get_volume(v1.id) is None
        moved1 = await svc.get_chapter(ch1.id)
        moved2 = await svc.get_chapter(ch2.id)
        assert moved1 is not None and moved1.volume_id == v2.id
        assert moved2 is not None and moved2.volume_id == v2.id

    @pytest.mark.asyncio
    async def test_delete_volume_move_to_self_raises(self, svc, project) -> None:
        """move_to 指向自身 → VolumeMoveError。"""
        pid = uuid.UUID(int=project.id)
        vol = await svc.create_volume(pid, "自身卷")
        await svc.create_chapter(pid, "章一", volume_id=vol.id)
        with pytest.raises(VolumeMoveError):
            await svc.delete_volume(vol.id, move_to=vol.id)

    @pytest.mark.asyncio
    async def test_delete_volume_move_to_overflow_raises(self, svc, project) -> None:
        """move_to > 2**63-1 → VolumeMoveError（目标卷不存在守卫）。"""
        pid = uuid.UUID(int=project.id)
        vol = await svc.create_volume(pid, "溢出目标卷")
        await svc.create_chapter(pid, "章一", volume_id=vol.id)
        with pytest.raises(VolumeMoveError):
            await svc.delete_volume(vol.id, move_to=2**63)

    @pytest.mark.asyncio
    async def test_delete_volume_chapters_no_params_raises(self, svc, project) -> None:
        """卷下有章节且未指定处理方式 → VolumeNotEmptyError，卷与章均保留。"""
        pid = uuid.UUID(int=project.id)
        vol = await svc.create_volume(pid, "非空卷")
        ch = await svc.create_chapter(pid, "章一", volume_id=vol.id)
        with pytest.raises(VolumeNotEmptyError):
            await svc.delete_volume(vol.id)
        assert await svc.get_volume(vol.id) is not None
        assert await svc.get_chapter(ch.id) is not None

    @pytest.mark.asyncio
    async def test_delete_volume_move_to_nonexistent_raises(self, svc, project) -> None:
        """move_to 指向不存在的 64-bit 卷 id → VolumeMoveError。"""
        pid = uuid.UUID(int=project.id)
        vol = await svc.create_volume(pid, "目标不存在卷")
        await svc.create_chapter(pid, "章一", volume_id=vol.id)
        with pytest.raises(VolumeMoveError):
            await svc.delete_volume(vol.id, move_to=987654321)
