"""#988 GREEN round-3 集成契约测试 — get_draft_service 真实装配闭环（#976 confirm 根修）.

被测链路: POST /api/v1/agent/drafts/{id}/confirm 路由的 svc 来自
inkflow.api.deps.get_draft_service（api/deps.py:221-231）。本文件直调该装配
（db 参数注入真 session，禁 mock / 禁测试手搭 chapter_creator/outline_bindder），
覆盖父侧盘点的断头路: 通用轨装配未注入 chapter_creator → GUI 审批弹层对未绑章
草稿 confirm 真实内核仍 409（#976），同时让共享工厂闭包被真实执行（func-cov 消红）。

- 【R】未绑章草稿（带卷 + source_outline_id）confirm → 自动建章 + 双回填
- 【R】同装配 confirm 显式 title → 自动建章标题优先于 summary 派生
- 【G】已绑定章草稿 confirm → 正常确认且不新建章（装配注入零回归）

装配断言降级说明（§2 允许）: ConfirmRequest body → svc.confirm kwargs 透传已由
tests/api/test_f27_agentic_api.py mock 轨锁定；本文件补「真实装配执行」层——
必须走 deps 层装配代码本身（get_draft_service 是路由同构依赖），门禁语义才达
（books.py 内嵌 _outline_bindder 只构造不执行的 func-cov 红即由此迁移消除）。

seed 形态镜像 tests/integration/test_draft_confirm_auto_chapter_976.py:
项目/卷/章 outline 点全部取小值 id（int↔uuid.UUID(int=X)），防随机 uuid4 溢出
SQLite INTEGER 列。Draft.id 为 String(36) uuid4 字符串无此限制。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.api.deps import get_draft_service
from inkflow.core.database import Base
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.infrastructure.database.models.chapter import ChapterORM, VolumeORM
from inkflow.infrastructure.database.models.outline import OutlineORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.draft_repo import (
    SQLiteDraftRepository,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# 小值 UUID（int↔UUID 惯例）：项目 id=7、卷 id=41、章 outline 点 id=51
PROJECT_ID = uuid.UUID(int=7)
VOLUME_UUID = uuid.UUID(int=41)
OUTLINE_UUID = uuid.UUID(int=51)
VOLUME_ID_INT = 41
OUTLINE_ID_INT = 51

DRAFT_CONTENT = "这是 agent 写出的章节草稿正文，用于测试 confirm 自动建章落库正确性。"
DRAFT_SUMMARY = "第一章草稿摘要"
EXPLICIT_TITLE = "显式定稿标题（title 优先）"


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
    """seed 项目(id=7) + 卷(id=41) + 章 outline 点(id=51, 含 volume_id=41)."""
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


class TestDraftConfirmHttpAssembly988:
    """#988 get_draft_service 真实装配：confirm 自动建章闭环 + 绑定章零回归."""

    async def test_unbound_draft_confirm_auto_creates_chapter(self) -> None:
        """【R】deps 装配下未绑章草稿 confirm → 自动建章 + draft/outline 双回填。"""
        db, engine = await _make_real_session()
        try:
            await _seed_project_volume_outline(db)
            repo = SQLiteDraftRepository(db)
            draft = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=DRAFT_CONTENT,
                summary=DRAFT_SUMMARY,
                volume_id=VOLUME_UUID,
            )

            svc = get_draft_service(db)  # 路由同构依赖：当前未注入 creator → RED
            confirmed = await svc.confirm(draft.id, source_outline_id=OUTLINE_UUID)

            assert confirmed.status.value == "confirmed"
            chapters = (await db.execute(select(ChapterORM))).scalars().all()
            assert len(chapters) == 1
            ch = chapters[0]
            assert ch.title == DRAFT_SUMMARY  # 无显式 title → summary 派生
            assert ch.content == DRAFT_CONTENT
            assert ch.status == "final"
            assert ch.word_count > 0
            assert ch.volume_id == VOLUME_ID_INT  # 草稿卷透传（UUID→int）

            fetched = await repo.get(draft.id)
            assert fetched is not None
            assert fetched.chapter_id == uuid.UUID(int=ch.id)
            assert fetched.status.value == "confirmed"

            outline_row = await db.get(OutlineORM, OUTLINE_ID_INT)
            assert outline_row is not None
            assert outline_row.chapter_id == ch.id
        finally:
            await engine.dispose()

    async def test_unbound_draft_confirm_title_passthrough(self) -> None:
        """【R】同装配 confirm 传 title → 自动建章标题显式优先于 summary 派生。"""
        db, engine = await _make_real_session()
        try:
            await _seed_project_volume_outline(db)
            repo = SQLiteDraftRepository(db)
            draft = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=DRAFT_CONTENT,
                summary=DRAFT_SUMMARY,
                volume_id=VOLUME_UUID,
            )

            svc = get_draft_service(db)  # 当前未注入 creator → RED
            confirmed = await svc.confirm(
                draft.id,
                source_outline_id=OUTLINE_UUID,
                title=EXPLICIT_TITLE,
            )

            assert confirmed.status.value == "confirmed"
            chapters = (await db.execute(select(ChapterORM))).scalars().all()
            assert len(chapters) == 1
            ch = chapters[0]
            assert ch.title == EXPLICIT_TITLE  # 显式 title 优先，非 summary 派生
            assert ch.status == "final"

            outline_row = await db.get(OutlineORM, OUTLINE_ID_INT)
            assert outline_row is not None
            assert outline_row.chapter_id == ch.id
        finally:
            await engine.dispose()

    async def test_bound_draft_confirm_keeps_existing_chapter(self) -> None:
        """【G】已绑定章草稿 confirm → 写既有章、置 CONFIRMED、不新建章。"""
        db, engine = await _make_real_session()
        try:
            db.add(ProjectORM(id=7, name="测试项目"))
            await db.commit()
            chapter_svc = ChapterService(db)
            chapter = await chapter_svc.create_chapter(
                PROJECT_ID,
                "既有章节",
                content="旧正文",
            )
            repo = SQLiteDraftRepository(db)
            draft = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=chapter.id,
                content=DRAFT_CONTENT,
                summary=DRAFT_SUMMARY,
            )

            svc = get_draft_service(db)  # 装配注入 creator/bindder 后仍走绑定路径
            confirmed = await svc.confirm(draft.id)

            assert confirmed.status.value == "confirmed"
            chapters = (await db.execute(select(ChapterORM))).scalars().all()
            assert len(chapters) == 1  # 绑定章 confirm 不触发自动建章
            ch = chapters[0]
            assert ch.title == "既有章节"
            assert ch.content == DRAFT_CONTENT
            assert ch.status == "final"
        finally:
            await engine.dispose()
