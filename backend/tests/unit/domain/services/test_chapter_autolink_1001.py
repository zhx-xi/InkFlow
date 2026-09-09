"""#1001 RED 契约 — ChapterService 正文落盘 → 章级大纲自动关联触发点.

契约依据: specs/f11-outline/spec.md §16.3（触发点：正文首次非空白落盘；
弱依赖：关联异常不影响落盘）。当前构造签名无 outline_autolinker → TypeError（RED）。

形态镜像 test_chapter_service.py：真实 SQLiteChapterRepository + in-memory 引擎
（ChapterService.__init__ 硬编码实例化仓储）；自动关联器用 AsyncMock 注入 spy。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.chapter import ChapterUpdate
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.infrastructure.database.models.project import ProjectORM

TITLE = "第一章 启程"


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库。"""
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
async def project(db_session) -> ProjectORM:
    """基础项目（章节 FK 依赖）。"""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest.fixture
def autolinker() -> AsyncMock:
    """自动关联器 spy（默认成功）。"""
    return AsyncMock(return_value=None)


@pytest.fixture
async def svc(db_session, autolinker: AsyncMock) -> ChapterService:
    """被测服务实例（注入自动关联器 spy）。"""
    return ChapterService(db_session, outline_autolinker=autolinker)


class TestChapterAutolinkTrigger:
    """§16.3 触发点 — 正文首次非空白落盘。"""

    async def test_first_nonempty_content_triggers(self, svc, autolinker, project) -> None:
        """【R】空章 → 首次写入正文 → 关联器收到 (project_id, chapter_id, title)。"""
        pid = uuid.UUID(int=project.id)
        ch = await svc.create_chapter(pid, TITLE, content="")
        autolinker.reset_mock()

        saved = await svc.update_chapter(ch.id, ChapterUpdate(content="正文第一段"))
        assert saved is not None
        autolinker.assert_awaited_once_with(pid, ch.id, TITLE)

    async def test_second_content_write_does_not_retrigger(
        self, svc, autolinker, project
    ) -> None:
        """【R】已有正文后再写正文 → 不再触发（幂等：重复写入不重复）。"""
        pid = uuid.UUID(int=project.id)
        ch = await svc.create_chapter(pid, TITLE, content="")
        await svc.update_chapter(ch.id, ChapterUpdate(content="第一段"))
        autolinker.reset_mock()

        await svc.update_chapter(ch.id, ChapterUpdate(content="第一段 + 第二段"))
        autolinker.assert_not_awaited()

    async def test_blank_content_does_not_trigger(self, svc, autolinker, project) -> None:
        """【R】正文为纯空白 → 不触发（正文「出现」= 非空白）。"""
        pid = uuid.UUID(int=project.id)
        ch = await svc.create_chapter(pid, TITLE, content="")
        autolinker.reset_mock()

        await svc.update_chapter(ch.id, ChapterUpdate(content="   \n  "))
        autolinker.assert_not_awaited()

    async def test_whitespace_then_real_content_triggers(
        self, svc, autolinker, project
    ) -> None:
        """【R】先落空白再落正文 → 空白不算「首次正文」→ 仍触发。"""
        pid = uuid.UUID(int=project.id)
        ch = await svc.create_chapter(pid, TITLE, content="")
        await svc.update_chapter(ch.id, ChapterUpdate(content="   "))
        autolinker.reset_mock()

        await svc.update_chapter(ch.id, ChapterUpdate(content="正文"))
        autolinker.assert_awaited_once_with(pid, ch.id, TITLE)

    async def test_title_only_update_does_not_trigger(
        self, svc, autolinker, project
    ) -> None:
        """【R】仅改标题（正文已存在）→ 不重触发（仅「正文首次落盘」入口）。"""
        pid = uuid.UUID(int=project.id)
        ch = await svc.create_chapter(pid, TITLE, content="正文")
        autolinker.reset_mock()

        await svc.update_chapter(ch.id, ChapterUpdate(title="第二章 转折"))
        autolinker.assert_not_awaited()

    async def test_create_with_content_triggers(self, svc, autolinker, project) -> None:
        """【R】创建即带正文 → 触发（正文出现的另一入口）。"""
        pid = uuid.UUID(int=project.id)
        ch = await svc.create_chapter(pid, TITLE, content="创建即带正文")
        autolinker.assert_awaited_once_with(pid, ch.id, TITLE)

    async def test_create_without_content_does_not_trigger(
        self, svc, autolinker, project
    ) -> None:
        """【R】创建空章 → 不触发。"""
        pid = uuid.UUID(int=project.id)
        await svc.create_chapter(pid, TITLE, content="")
        autolinker.assert_not_awaited()

    async def test_no_autolinker_injected_is_noop(self, db_session, project) -> None:
        """【R】未注入关联器 → 空操作（向后兼容，正文照常落盘）。"""
        pid = uuid.UUID(int=project.id)
        svc = ChapterService(db_session)
        ch = await svc.create_chapter(pid, TITLE, content="")
        saved = await svc.update_chapter(ch.id, ChapterUpdate(content="正文"))
        assert saved is not None
        assert saved.content == "正文"

    async def test_autolinker_exception_does_not_break_save(
        self, db_session, project
    ) -> None:
        """【R】弱依赖铁律：关联器抛错 → 正文仍落盘、update 不抛错。"""
        pid = uuid.UUID(int=project.id)
        boom = AsyncMock(side_effect=RuntimeError("autolink boom"))
        svc = ChapterService(db_session, outline_autolinker=boom)
        ch = await svc.create_chapter(pid, TITLE, content="")

        saved = await svc.update_chapter(ch.id, ChapterUpdate(content="正文必须落盘"))
        assert saved is not None
        assert saved.content == "正文必须落盘"
        reread = await svc.get_chapter(ch.id)
        assert reread is not None
        assert reread.content == "正文必须落盘"

    async def test_update_missing_chapter_does_not_trigger(
        self, svc, autolinker, project
    ) -> None:
        """【R】更新不存在的章节 → None 且不触发。"""
        missing = uuid.UUID("3f2e1d4a-0000-4000-8000-00000000dead")
        assert await svc.update_chapter(missing, ChapterUpdate(content="正文")) is None
        autolinker.assert_not_awaited()
