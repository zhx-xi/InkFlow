"""#1095 RED 契约（落库路径）— ChapterService 正文归一接入.

issue #1095 根因 1: 正文 content 落库链路无标题/缩进归一。
本文件断言「归一函数被真正接入落库路径」—— 纯函数单测（
test_chapter_content_normalize_1095.py）只证明函数正确，
不证明它在落库时被调用。

落库路径（源码实证）:
  - chapter_service.create_chapter      → repo.add_chapter
  - chapter_service.update_chapter      → repo.update_chapter（draft_service.confirm 走此处）
  Repository 层（chapter_repo.add/update_chapter）**不得**重复归一（单一真相面，
  避免双层归一双重缩进风险）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.chapter import ChapterUpdate
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.infrastructure.database.models.project import ProjectORM

FULLWIDTH = "\u3000"


@pytest.fixture
async def db_session():
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
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest.fixture
async def svc(db_session) -> ChapterService:
    return ChapterService(db_session)


class TestCreateChapterNormalizes:
    """create_chapter 落库前归一（book run 建章路径）。"""

    async def test_create_strips_duplicate_title_and_indents(self, svc, project) -> None:
        title = "第1章 雪夜怪梦"
        content = f"{title}\n\n师父停了三天。"
        ch = await svc.create_chapter(uuid.UUID(int=project.id), title, content=content)
        assert ch.content is not None
        assert title not in ch.content, "落库 content 仍含重复标题"
        assert ch.content.startswith(FULLWIDTH * 2)

    async def test_create_with_hash_title_clean(self, svc, project) -> None:
        title = "第4章 医武不分家"
        ch = await svc.create_chapter(
            uuid.UUID(int=project.id), title, content=f"# {title}\n\n李慕白醒了。"
        )
        assert "#" not in (ch.content or "")
        assert "李慕白醒了。" in (ch.content or "")

    async def test_indent_applied_to_unindented_body(self, svc, project) -> None:
        """真实 book run 形态：标题已单独归一，正文 0/58 行无缩进（issue #1095 实测）。

        正文无重复标题、无 markdown，仅缺段首全角缩进 —— 这**仍属脏数据**，
        落库前必须补全角缩进（否则子现象 3 在真实生成路径上完全未修复）。
        """
        ch = await svc.create_chapter(
            uuid.UUID(int=project.id),
            "第1章 雪夜怪梦",
            content="师父停了三天。\n\n李慕白醒了。",
        )
        content = ch.content or ""
        assert "师父停了三天。" in content and "李慕白醒了。" in content
        paragraphs = [p for p in content.split("\n") if p.strip()]
        for para in paragraphs:
            assert para.startswith(FULLWIDTH * 2), f"落库正文缺全角缩进: {para!r}"

    async def test_create_empty_content_untouched(self, svc, project) -> None:
        """空正文 → 保持空（draft_service 先建空章再落正文，不得凭空造内容）。"""
        ch = await svc.create_chapter(uuid.UUID(int=project.id), "第一章", content="")
        assert (ch.content or "").strip() == ""


class TestUpdateChapterNormalizes:
    """update_chapter 落库前归一（draft_service.confirm 写正式章节走此处）。"""

    async def test_update_normalizes_content(self, svc, project) -> None:
        ch = await svc.create_chapter(uuid.UUID(int=project.id), "第1章 雪夜怪梦")
        title = ch.title
        updated = await svc.update_chapter(
            ch.id,
            ChapterUpdate(content=f"# {title}\n\n师父停了三天。\n\n李慕白醒了。"),
        )
        assert updated is not None
        assert "#" not in (updated.content or "")
        assert title not in (updated.content or "")
        paragraphs = [p for p in (updated.content or "").split("\n") if p.strip()]
        for para in paragraphs:
            assert para.startswith(FULLWIDTH * 2), f"段首缺全角缩进: {para!r}"

    async def test_update_partial_title_only_keeps_content(self, svc, project) -> None:
        """只改 title 的部分更新 → content 不受影响（不误归一为空）。"""
        ch = await svc.create_chapter(
            uuid.UUID(int=project.id), "第1章 雪夜怪梦", content="师父停了三天。"
        )
        updated = await svc.update_chapter(ch.id, ChapterUpdate(title="第1章 雪夜梦"))
        assert updated is not None
        assert "师父停了三天。" in (updated.content or "")


class TestWordCountConsistencyOnPersist:
    """落库后 word_count 与可见正文一致（issue 影响面）。"""

    async def test_word_count_excludes_stripped_title(self, svc, project) -> None:
        """字数不得把已剥离的重复标题行计入。"""
        title = "第1章 雪夜怪梦"
        ch = await svc.create_chapter(
            uuid.UUID(int=project.id), title, content=f"# {title}\n\n师父停了三天。"
        )
        from inkflow.domain.services._word_count import count_words

        assert ch.word_count == count_words(ch.content or "")
        assert ch.word_count == count_words("师父停了三天。")
