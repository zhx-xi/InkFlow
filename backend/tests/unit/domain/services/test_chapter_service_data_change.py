"""ChapterService 数据面变更事件测试 — chapter + volume 两域（#1090 批次 B）。

契约来源：W3C 设计裁定表 §2.1（父侧单一真相源；spec §15.3.2/§15.3.3/§15.6.4）。
- volume：create/update/delete 成功后各发一条；update 返回 None / delete 返回 False → 不发；
  delete_volume 的级联删章与移章分支**不另发 chapter 事件**（前端 writing 页同订
  chapter+volume，volume 事件已触发树失效）。
- chapter：create/update/move（op="update"）/delete 成功后各发一条；
  **delete_chapter 为薄透传** → project_id=None + logger.warning（spec §15.3.2 已知例外）。
- normalize_all_titles：批量完成后发**两条**域级事件（chapter + outline，resource_id=
  str(project_id)）；两计数全 0（幂等无变化）→ 不发。

ChapterService.__init__ 硬编码实例化 SQLite 仓储 → 走真实 in-memory SQLite
（镜像 test_chapter_service.py 的 fixture 形态）。
RED 阶段预期：正例断言 FAIL，负例可能已 PASS。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.chapter import (
    ChapterUpdate,
    VolumeUpdate,
    normalize_chapter_title,
)
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.infrastructure.database.models.project import ProjectORM

LOGGER_NAME = "inkflow.domain.services.chapter_service"
RAW_TITLE = "第一章 开端"
TARGET_FMT = "arabic"


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
async def pid(project) -> uuid.UUID:
    """项目领域 UUID（服务层入参形态）。"""
    return uuid.UUID(int=project.id)


@pytest.fixture
async def svc(db_session) -> ChapterService:
    """被测服务实例（真实 SQLite 仓储）。"""
    return ChapterService(db_session)


class TestVolumeDataChange:
    """volume 域写路径发布事件。"""

    async def test_create_volume_publishes_create(self, svc, pid, recorded_events) -> None:
        """create_volume 成功 → volume/create，project_id 取返回实体。"""
        vol = await svc.create_volume(pid, "第一卷")

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("volume", "create")
        assert event.resource_id == str(vol.id)
        assert event.project_id == str(vol.project_id)

    async def test_update_volume_publishes_update(self, svc, pid, recorded_events) -> None:
        """update_volume 成功 → volume/update，project_id 从已加载实体解析。"""
        vol = await svc.create_volume(pid, "第一卷")
        recorded_events.clear()

        updated = await svc.update_volume(vol.id, VolumeUpdate(title="第一卷（改）"))

        assert updated is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("volume", "update")
        assert event.resource_id == str(updated.id)
        assert event.project_id == str(pid)

    async def test_update_volume_missing_publishes_nothing(self, svc, recorded_events) -> None:
        """反例：卷不存在（返回 None）→ 零发布。"""
        assert await svc.update_volume(999999, VolumeUpdate(title="x")) is None
        assert recorded_events == []

    async def test_delete_volume_publishes_delete(self, svc, pid, recorded_events) -> None:
        """delete_volume 空卷成功 → volume/delete。"""
        vol = await svc.create_volume(pid, "第一卷")
        recorded_events.clear()

        assert await svc.delete_volume(vol.id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("volume", "delete")
        assert event.resource_id == str(vol.id)
        assert event.project_id == str(pid)

    async def test_delete_volume_missing_publishes_nothing(self, svc, recorded_events) -> None:
        """反例：卷不存在（返回 False）→ 零发布。"""
        assert await svc.delete_volume(999999) is False
        assert recorded_events == []

    async def test_delete_volume_cascade_publishes_single_volume_event(
        self, svc, pid, recorded_events
    ) -> None:
        """级联删章分支：只发一条 volume/delete，**不另发** chapter 事件（§2.1）。"""
        vol = await svc.create_volume(pid, "第一卷")
        await svc.create_chapter(pid, "第一章", volume_id=vol.id)
        recorded_events.clear()

        assert await svc.delete_volume(vol.id, delete_chapters=True) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("volume", "delete")
        assert event.resource_id == str(vol.id)
        assert event.project_id == str(pid)


class TestChapterDataChange:
    """chapter 域写路径发布事件。"""

    async def test_create_chapter_publishes_create(self, svc, pid, recorded_events) -> None:
        """create_chapter 成功 → chapter/create。"""
        ch = await svc.create_chapter(pid, "第一章")

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("chapter", "create")
        assert event.resource_id == str(ch.id)
        assert event.project_id == str(pid)

    async def test_update_chapter_publishes_update(self, svc, pid, recorded_events) -> None:
        """update_chapter 成功 → chapter/update，project_id 从落库实体解析。"""
        ch = await svc.create_chapter(pid, "第一章")
        recorded_events.clear()

        saved = await svc.update_chapter(ch.id, ChapterUpdate(content="新正文"))

        assert saved is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("chapter", "update")
        assert event.resource_id == str(saved.id)
        assert event.project_id == str(pid)

    async def test_update_chapter_missing_publishes_nothing(self, svc, recorded_events) -> None:
        """反例：章节不存在（返回 None）→ 零发布。"""
        assert await svc.update_chapter(999999, ChapterUpdate(content="x")) is None
        assert recorded_events == []

    async def test_delete_chapter_publishes_none_project_id_with_warning(
        self, svc, pid, recorded_events, caplog
    ) -> None:
        """delete_chapter 薄透传（未加载实体）→ None + warning（§15.3.2 已知例外）。"""
        ch = await svc.create_chapter(pid, "第一章")
        recorded_events.clear()
        caplog.set_level("WARNING", logger=LOGGER_NAME)

        assert await svc.delete_chapter(ch.id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("chapter", "delete")
        assert event.resource_id == str(ch.id)
        assert event.project_id is None
        assert any("project_id" in record.getMessage() for record in caplog.records)

    async def test_delete_chapter_missing_publishes_nothing(self, svc, recorded_events) -> None:
        """反例：章节不存在（返回 False）→ 零发布。"""
        assert await svc.delete_chapter(uuid.UUID(int=999999)) is False
        assert recorded_events == []

    async def test_move_chapter_publishes_update(self, svc, pid, recorded_events) -> None:
        """move_chapter 成功 → chapter/update（§15.6.4 语义化操作映射 update）。"""
        ch = await svc.create_chapter(pid, "第一章")
        recorded_events.clear()

        result = await svc.move_chapter(ch.id, None)

        assert result is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("chapter", "update")
        assert event.resource_id == str(result.id)
        assert event.project_id == str(pid)


class TestNormalizeAllTitlesDataChange:
    """批量归一 → 两条域级事件（chapter + outline，§2.1 保守取细）。"""

    async def test_normalize_all_titles_publishes_two_domain_events(
        self, svc, pid, recorded_events
    ) -> None:
        """批量归一且有变化 → 恰好两条域级事件（resource_id=str(project_id)）。"""
        # 前置守卫：本用例依赖「该标题在该格式下确有变化」，避免归一规则漂移导致假契约
        assert normalize_chapter_title(RAW_TITLE, TARGET_FMT) != RAW_TITLE
        await svc.create_chapter(pid, RAW_TITLE)
        recorded_events.clear()

        result = await svc.normalize_all_titles(pid, TARGET_FMT)

        assert result == {"chapters_replaced": 1, "outlines_replaced": 0}
        assert len(recorded_events) == 2
        tuples = {(e.domain, e.op, e.resource_id, e.project_id) for e in recorded_events}
        assert tuples == {
            ("chapter", "update", str(pid), str(pid)),
            ("outline", "update", str(pid), str(pid)),
        }

    async def test_normalize_all_titles_no_change_publishes_nothing(
        self, svc, pid, recorded_events
    ) -> None:
        """反例：二次同 fmt 调用（两计数全 0，幂等无变化）→ 零发布。"""
        await svc.create_chapter(pid, RAW_TITLE)
        assert await svc.normalize_all_titles(pid, TARGET_FMT) is not None
        recorded_events.clear()

        result = await svc.normalize_all_titles(pid, TARGET_FMT)

        assert result == {"chapters_replaced": 0, "outlines_replaced": 0}
        assert recorded_events == []

    async def test_normalize_all_titles_project_missing_publishes_nothing(
        self, svc, recorded_events
    ) -> None:
        """反例：项目不存在（返回 None）→ 零发布。"""
        assert await svc.normalize_all_titles(uuid.UUID(int=999999), TARGET_FMT) is None
        assert recorded_events == []
