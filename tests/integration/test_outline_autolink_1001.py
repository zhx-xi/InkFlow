"""#1001 集成契约 — 正文落盘 → outlines.chapter_id 自动回填（真 DB 轨）.

被测链路（真实装配，禁 mock 服务层）:
1. seed 项目 + 卷 + 章级大纲（name == 章标题）+ 空正文章
2. `get_chapter_service(db)`（deps 装配 outline_autolinker）→ update_chapter(content)
3. 直证 `SELECT outlines.chapter_id` 回填；重复写入幂等；无命中/已绑不动
4. 草稿确认流（#996 验收）：DraftService.confirm 自动建章 → 同一触发点回填

seed 形态镜像 test_draft_source_outline_backfill_988.py：小值 id（int↔UUID 惯例）
防随机 uuid4 溢出 SQLite INTEGER 列。

同名多条（§16.2 防御分支）在真库不可构造（uq_outlines_active_name 全唯一）→
由 backend/tests/unit/domain/services/test_outline_autolink_1001.py Mock 轨直证。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.api.deps import get_chapter_service, get_draft_service
from inkflow.core.database import Base
from inkflow.domain.models.chapter import ChapterUpdate
from inkflow.infrastructure.database.models.chapter import ChapterORM, VolumeORM
from inkflow.infrastructure.database.models.outline import OutlineORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.draft_repo import SQLiteDraftRepository

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# 小值 UUID（int↔UUID 惯例）：项目 id=7、卷 id=41、章级大纲 id=51
PROJECT_ID = uuid.UUID(int=7)
PROJECT_ID_INT = 7
VOLUME_ID_INT = 41
OUTLINE_ID_INT = 51
CHAPTER_ID_INT = 61
OTHER_CHAPTER_ID_INT = 62
UNMATCHED_CHAPTER_ID_INT = 63

CHAPTER_UUID = uuid.UUID(int=CHAPTER_ID_INT)
OTHER_CHAPTER_UUID = uuid.UUID(int=OTHER_CHAPTER_ID_INT)
UNMATCHED_CHAPTER_UUID = uuid.UUID(int=UNMATCHED_CHAPTER_ID_INT)

TITLE = "第一章 启程"
CONTENT = "启程一章的正文（自动关联集成契约）。"


async def _make_real_session() -> tuple[AsyncSession, object]:
    """真实 in-memory aiosqlite + 单 AsyncSession。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db: AsyncSession = factory()
    return db, engine


def _seed_base(db: AsyncSession, *, outline_chapter_id: int | None = None) -> None:
    """seed 项目(7) + 卷(41) + 章级大纲(51, name=TITLE) + 三章(61/62/63)。"""
    db.add(ProjectORM(id=PROJECT_ID_INT, name="测试项目"))
    db.add(VolumeORM(id=VOLUME_ID_INT, project_id=PROJECT_ID_INT, title="第一卷"))
    db.add(
        OutlineORM(
            id=OUTLINE_ID_INT,
            project_id=PROJECT_ID_INT,
            name=TITLE,
            description="",
            sort_order=0,
            level="chapter",
            volume_id=VOLUME_ID_INT,
            chapter_id=outline_chapter_id,
        )
    )
    db.add(
        ChapterORM(
            id=CHAPTER_ID_INT,
            project_id=PROJECT_ID_INT,
            volume_id=VOLUME_ID_INT,
            title=TITLE,
            content="",
            status="draft",
            word_count=0,
            order_index=1.0,
        )
    )
    db.add(
        ChapterORM(
            id=OTHER_CHAPTER_ID_INT,
            project_id=PROJECT_ID_INT,
            volume_id=VOLUME_ID_INT,
            title="另一章",
            content="另一章正文",
            status="draft",
            word_count=0,
            order_index=2.0,
        )
    )
    db.add(
        ChapterORM(
            id=UNMATCHED_CHAPTER_ID_INT,
            project_id=PROJECT_ID_INT,
            volume_id=VOLUME_ID_INT,
            title="未匹配章",
            content="",
            status="draft",
            word_count=0,
            order_index=3.0,
        )
    )


class TestChapterContentAutolink1001:
    """§16.3 正文首次非空白落盘 → outlines.chapter_id 回填（真装配）。"""

    async def test_content_save_backfills_outline_chapter_id(self) -> None:
        """【R】空正文章落盘正文 → 同名唯一章级大纲 chapter_id 回填。"""
        db, engine = await _make_real_session()
        try:
            _seed_base(db)
            await db.commit()

            svc = get_chapter_service(db)
            saved = await svc.update_chapter(CHAPTER_UUID, ChapterUpdate(content=CONTENT))
            assert saved is not None

            outline_row = await db.get(OutlineORM, OUTLINE_ID_INT)
            assert outline_row is not None
            assert outline_row.chapter_id == CHAPTER_ID_INT
        finally:
            await engine.dispose()

    async def test_repeat_save_is_idempotent(self) -> None:
        """【R】重复写入正文 → 绑定保持唯一且不抛错。"""
        db, engine = await _make_real_session()
        try:
            _seed_base(db)
            await db.commit()

            svc = get_chapter_service(db)
            await svc.update_chapter(CHAPTER_UUID, ChapterUpdate(content="第一段"))
            await svc.update_chapter(CHAPTER_UUID, ChapterUpdate(content="第一段 + 第二段"))

            outline_row = await db.get(OutlineORM, OUTLINE_ID_INT)
            assert outline_row is not None
            assert outline_row.chapter_id == CHAPTER_ID_INT
        finally:
            await engine.dispose()

    async def test_no_title_match_leaves_chapter_id_null(self) -> None:
        """【R】章标题与任何章级大纲名都不精确相等 → 不回填（保留手动兜底）。"""
        db, engine = await _make_real_session()
        try:
            _seed_base(db)
            await db.commit()

            svc = get_chapter_service(db)
            await svc.update_chapter(
                UNMATCHED_CHAPTER_UUID, ChapterUpdate(content=CONTENT)
            )

            outline_row = await db.get(OutlineORM, OUTLINE_ID_INT)
            assert outline_row is not None
            assert outline_row.chapter_id is None
        finally:
            await engine.dispose()

    async def test_existing_other_binding_not_overwritten(self) -> None:
        """【R】大纲已绑别的章 → 正文落盘不覆盖（不静默改错）。"""
        db, engine = await _make_real_session()
        try:
            _seed_base(db, outline_chapter_id=OTHER_CHAPTER_ID_INT)
            await db.commit()

            svc = get_chapter_service(db)
            await svc.update_chapter(CHAPTER_UUID, ChapterUpdate(content=CONTENT))

            outline_row = await db.get(OutlineORM, OUTLINE_ID_INT)
            assert outline_row is not None
            assert outline_row.chapter_id == OTHER_CHAPTER_ID_INT
        finally:
            await engine.dispose()

    async def test_draft_confirm_backfills_by_title(self) -> None:
        """【R】#996 验收：草稿确认自动建章（标题=summary）→ 同名大纲自动回填。"""
        db, engine = await _make_real_session()
        try:
            _seed_base(db)
            await db.commit()

            repo = SQLiteDraftRepository(db)
            draft = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=CONTENT,
                summary=TITLE,
            )

            svc = get_draft_service(db)
            confirmed = await svc.confirm(draft.id)
            assert confirmed.status.value == "confirmed"

            chapters = (await db.execute(select(ChapterORM))).scalars().all()
            created = [c for c in chapters if c.title == TITLE and c.id != CHAPTER_ID_INT]
            assert len(created) == 1
            assert created[0].content == CONTENT

            outline_row = await db.get(OutlineORM, OUTLINE_ID_INT)
            assert outline_row is not None
            assert outline_row.chapter_id == created[0].id
        finally:
            await engine.dispose()
