"""#976 RED-2 集成契约测试 — confirm 自动建章（真实 in-memory SQLite + 真实服务装配）.

被测链路（当前实现未落地，对照当前实现全部 RED）:
- DraftService.__init__ 不接收 chapter_creator / outline_bindder → TypeError（【R】）
- SQLiteDraftRepository.create 不接收 volume_id kwarg → TypeError（【R】）
- DraftORM 无 volume_id 列 / Draft 域模型无 volume_id → 读回缺字段（【R】）

GREEN 判据（父侧定稿契约 §2.4 D4 落库断言）:
1. seed 项目(id=7) + 卷(id=41) + 章 outline 点(id=51, 含 volume_id=41)
2. draft_repo.create(volume_id=str(uuid.UUID(int=41)), chapter_id=None)
3. DraftService 真实装配（SQLiteDraftRepository + ChapterService + chapter_creator +
   outline_bindder 真实闭包）→ confirm(source_outline_id=uuid.UUID(int=51))
4. 断言: ① 新 Chapter 落库（title 派生、content==draft.content、status=FINAL、
   word_count>0、volume_id 透传=41）；② draft.chapter_id 回填 == uuid.UUID(int=new_ch.id)；
   ③ OutlineORM(51).chapter_id 回填 == new_ch.id

项目/卷/章 id 一律用 seed 行取小值（int↔uuid.UUID(int=X) 惯例，防随机 uuid4 溢出
SQLite INTEGER 列——镜像 tests/integration/test_book_run_953_bridge.py 头部注释）。
Draft.id 是 String(36) 无此限制（id 由 ORM default 生成 uuid4 字符串）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.domain.services.draft_service import DraftService
from inkflow.infrastructure.database.models.chapter import ChapterORM, VolumeORM
from inkflow.infrastructure.database.models.outline import OutlineORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.draft_repo import (
    SQLiteDraftRepository,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# 小值 UUID（int↔UUID 惯例）：项目 id=7、卷 id=41、章 outline 点 id=51，防随机溢出 INTEGER 列
PROJECT_ID = uuid.UUID(int=7)
VOLUME_UUID = uuid.UUID(int=41)
OUTLINE_UUID = uuid.UUID(int=51)
VOLUME_ID_INT = 41
OUTLINE_ID_INT = 51

DRAFT_CONTENT = "这是 agent 写出的章节草稿正文，用于测试 confirm 自动建章落库正确性。"
DRAFT_SUMMARY = "第一章草稿摘要"


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _make_real_session() -> tuple[AsyncSession, object]:
    """真实 in-memory aiosqlite + 单 AsyncSession
    （镜像 test_book_run_953_bridge._make_real_session）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db: AsyncSession = factory()
    return db, engine


async def _seed_project_volume_outline(db: AsyncSession) -> None:
    """seed 项目(id=7) + 卷(id=41) + 章 outline 点(id=51, 含 volume_id=41).

    全部用 seed 行取小值 id（int↔uuid.UUID(int=X)），禁随机 uuid4 进 INTEGER 列。
    """
    db.add(ProjectORM(id=7, name="测试项目"))
    db.add(VolumeORM(id=VOLUME_ID_INT, project_id=7, title="第一卷"))
    db.add(
        OutlineORM(
            id=OUTLINE_ID_INT,
            project_id=7,
            name="第一卷章点",
            description="",
            sort_order=0,
            level="chapter",
            volume_id=VOLUME_ID_INT,
        )
    )
    await db.commit()


def _assemble_draft_service(db: AsyncSession) -> DraftService:
    """真实装配 DraftService（chapter_creator=ChapterService.create_chapter，
    outline_bindder 真实闭包）.

    镜像 api/deps.py get_draft_service 的接线点但注入 chapter_creator/outline_bindder。
    当前 DraftService.__init__ 不接受这些参数 → TypeError（RED）。
    """
    chapter_svc = ChapterService(db)

    async def _outline_bindder(chapter_outline_id: str, chapter_uuid_str: str) -> None:
        """回填 outlines.chapter_id（镜像 OutlineRepo 回填；str uuid → int id）。"""
        outline_id = uuid.UUID(chapter_outline_id).int
        ch_id = uuid.UUID(chapter_uuid_str).int
        orm = await db.get(OutlineORM, outline_id)
        if orm is not None:
            orm.chapter_id = ch_id
            await db.commit()

    return DraftService(
        draft_repo=SQLiteDraftRepository(db),
        chapter_service=chapter_svc,
        chapter_creator=chapter_svc.create_chapter,
        outline_bindder=_outline_bindder,
    )


class TestDraftConfirmAutoChapter976:
    """#976 confirm 自动建章：真实 DB + 真实服务 -> 新章落库 + 双回填."""

    async def test_confirm_auto_creates_chapter_and_backfills(self) -> None:
        """【R】confirm(source_outline_id) → 新章 FINAL + 落库 + draft.chapter_id 回填 +
        outlines.chapter_id 回填。"""
        db, engine = await _make_real_session()
        try:
            await _seed_project_volume_outline(db)

            # 落卷绑定草稿（chapter_id=None）
            repo = SQLiteDraftRepository(db)
            draft = await repo.create(  # 当前无 volume_id kwarg → TypeError（RED 锚）
                project_id=PROJECT_ID,
                chapter_id=None,
                content=DRAFT_CONTENT,
                summary=DRAFT_SUMMARY,
                volume_id=VOLUME_UUID,
            )

            svc = _assemble_draft_service(db)  # 不接受 chapter_creator（RED 锚）

            confirmed = await svc.confirm(draft.id, source_outline_id=OUTLINE_UUID)

            assert confirmed.status.value == "confirmed"

            # ① 新 Chapter 落库
            chapters = (await db.execute(select(ChapterORM))).scalars().all()
            assert len(chapters) == 1
            ch = chapters[0]
            assert ch.title == DRAFT_SUMMARY  # 标题 = summary[:30]
            assert ch.content == DRAFT_CONTENT
            assert ch.status == "final"
            assert ch.word_count > 0
            assert ch.volume_id == VOLUME_ID_INT  # 草稿 volume_id 透传（UUID→int）

            new_chapter_id = uuid.UUID(int=ch.id)

            # ② draft.chapter_id 回填（repo 读回）
            fetched = await repo.get(draft.id)
            assert fetched is not None
            assert fetched.chapter_id == new_chapter_id
            assert fetched.status.value == "confirmed"

            # ③ outlines.chapter_id 回填
            outline_row = await db.get(OutlineORM, OUTLINE_ID_INT)
            assert outline_row is not None
            assert outline_row.chapter_id == ch.id
        finally:
            await engine.dispose()
