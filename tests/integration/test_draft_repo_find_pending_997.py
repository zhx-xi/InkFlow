"""#997 RED 集成契约测试 — SQLiteDraftRepository.find_pending + update_content 守卫（真 DB 轨）.

契约真相源: specs/f27-writer-agent/spec.md §5.2「DraftService/仓储增量（D2 拍板）」+ 拍板契约 F/G:

F. SQLiteDraftRepository 新增 async find_pending(project_id, *, chapter_id=None,
   source_outline_id=None) -> Draft | None:
   WHERE project_id=str AND status='draft' AND 非 None 入参键的 OR(chapter_id=str,
   source_outline_id=str)，ORDER BY created_at DESC LIMIT 1；两键皆 None → None（防御）。

G. SQLiteDraftRepository.update_content(draft_id, content, summary=None): 加 status='draft'
   守卫（confirmed/rejected → 不改不 commit 返回 None）；summary 非 None 同行覆盖。

当前实现对照（RED）: repo 无 find_pending（AttributeError）；update_content 无 summary 形参
（TypeError unexpected kwarg summary）+ 无 status 守卫（confirmed 稿仍被改正文 → 断言 FAIL）。

seed 形态镜像 tests/integration/test_book_run_953_bridge.py /
test_draft_source_outline_backfill_988.py:
真实 in-memory aiosqlite + 小值 UUID（int↔ORM id 惯例防溢出）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.draft import DraftStatus
from inkflow.infrastructure.database.models.agent_run import DraftORM
from inkflow.infrastructure.database.repositories.draft_repo import (
    SQLiteDraftRepository,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# 小值 UUID（int↔ORM 惯例）：项目 id=7、章 id=8、异章 id=9、大纲章点 id=51
PROJECT_ID = uuid.UUID(int=7)
CHAPTER_ID = uuid.UUID(int=8)
DIFFERENT_CHAPTER_ID = uuid.UUID(int=9)
OUTLINE_ID = uuid.UUID(int=51)
CONTENT_V1 = "第一版草稿正文。"
CONTENT_V2 = "第二版草稿正文。"
SUMMARY_OLD = "旧摘要"
SUMMARY_NEW = "新摘要"


async def _make_real_session() -> tuple[AsyncSession, object]:
    """真实 in-memory aiosqlite + 单 AsyncSession（镜像 953 bridge 形态）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db: AsyncSession = factory()
    return db, engine


async def _backdate(db: AsyncSession, draft_id: str) -> None:
    """把草稿 created_at 回拨 1 小时（使 find_pending 的 created_at DESC 判定确定）。"""
    orm = await db.get(DraftORM, draft_id)
    assert orm is not None
    orm.created_at = datetime.now(UTC) - timedelta(hours=1)
    await db.commit()


class TestSQLiteDraftRepositoryFindPending997:
    """SQLiteDraftRepository.find_pending 契约（#997 契约 F）。"""

    async def test_find_pending_returns_latest_draft_by_created_at(self) -> None:
        """【R→G】同章两稿 → find_pending 返回 created_at 最新且 status=draft 的那稿。

        当前 repo 无 find_pending → AttributeError（RED）。
        """
        db, engine = await _make_real_session()
        try:
            repo = SQLiteDraftRepository(db)
            d1 = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=CONTENT_V1,
                summary=SUMMARY_OLD,
                source_outline_id=OUTLINE_ID,
            )
            d2 = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=CONTENT_V2,
                summary=SUMMARY_OLD,
                source_outline_id=OUTLINE_ID,
            )
            await _backdate(db, d1.id)  # d1 回拨 → d2 必然最新

            found = await repo.find_pending(PROJECT_ID, source_outline_id=OUTLINE_ID)

            assert found is not None
            assert found.id == d2.id
            assert found.content == CONTENT_V2
            assert found.status is DraftStatus.DRAFT
        finally:
            await engine.dispose()

    async def test_find_pending_or_key_matches_source_outline_despite_chapter(self) -> None:
        """【R→G】OR 语义：source_outline_id 命中而传入 chapter_id 不同 → 仍命中（非 AND）。"""
        db, engine = await _make_real_session()
        try:
            repo = SQLiteDraftRepository(db)
            d = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=CHAPTER_ID,
                content=CONTENT_V1,
                source_outline_id=OUTLINE_ID,
            )

            found = await repo.find_pending(
                PROJECT_ID, chapter_id=DIFFERENT_CHAPTER_ID, source_outline_id=OUTLINE_ID
            )

            assert found is not None
            assert found.id == d.id
        finally:
            await engine.dispose()

    async def test_find_pending_returns_draft_keyed_by_chapter_id(self) -> None:
        """【R→G】仅 chapter_id 归组键命中（同章绑定）。"""
        db, engine = await _make_real_session()
        try:
            repo = SQLiteDraftRepository(db)
            d = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=CHAPTER_ID,
                content=CONTENT_V1,
                source_outline_id=None,
            )

            found = await repo.find_pending(PROJECT_ID, chapter_id=CHAPTER_ID)

            assert found is not None
            assert found.id == d.id
        finally:
            await engine.dispose()

    async def test_find_pending_all_confirmed_or_rejected_returns_none(self) -> None:
        """【R→G】同 outline 两稿全 confirmed/rejected → find_pending 返回 None（只查 draft）。"""
        db, engine = await _make_real_session()
        try:
            repo = SQLiteDraftRepository(db)
            c1 = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=CONTENT_V1,
                source_outline_id=OUTLINE_ID,
            )
            c2 = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=CONTENT_V2,
                source_outline_id=OUTLINE_ID,
            )
            await repo.update_status(c1.id, DraftStatus.CONFIRMED)
            await repo.update_status(c2.id, DraftStatus.REJECTED)

            found = await repo.find_pending(PROJECT_ID, source_outline_id=OUTLINE_ID)

            assert found is None
        finally:
            await engine.dispose()

    async def test_find_pending_no_anchor_keys_returns_none(self) -> None:
        """【R→G】两归组键皆 None → 直接 None（防御，不扫库）。"""
        db, engine = await _make_real_session()
        try:
            repo = SQLiteDraftRepository(db)
            await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=CONTENT_V1,
                source_outline_id=OUTLINE_ID,
            )

            found = await repo.find_pending(PROJECT_ID)

            assert found is None
        finally:
            await engine.dispose()


class TestSQLiteDraftRepositoryUpdateContentGuard997:
    """SQLiteDraftRepository.update_content 守卫契约（#997 契约 G）。"""

    async def test_update_content_confirmed_returns_none_and_unchanged(self) -> None:
        """【R→G】confirmed 稿 → update_content 返回 None 且正文不变（status='draft' 守卫）。

        当前无守卫：update_content 直接改正文并返回 confirmed 稿 → 断言 FAIL（RED）。
        """
        db, engine = await _make_real_session()
        try:
            repo = SQLiteDraftRepository(db)
            d = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=CONTENT_V1,
                source_outline_id=OUTLINE_ID,
            )
            await repo.update_status(d.id, DraftStatus.CONFIRMED)

            result = await repo.update_content(d.id, "不该生效的新正文")

            assert result is None
            fetched = await repo.get(d.id)
            assert fetched is not None
            assert fetched.content == CONTENT_V1  # 正文未变
        finally:
            await engine.dispose()

    async def test_update_content_rejected_returns_none(self) -> None:
        """【R→G】rejected 稿 → update_content 返回 None（status 守卫覆盖 rejected）。"""
        db, engine = await _make_real_session()
        try:
            repo = SQLiteDraftRepository(db)
            d = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=CONTENT_V1,
                source_outline_id=OUTLINE_ID,
            )
            await repo.update_status(d.id, DraftStatus.REJECTED)

            result = await repo.update_content(d.id, "不该生效的新正文")

            assert result is None
        finally:
            await engine.dispose()

    async def test_update_content_summary_overrides_and_content(self) -> None:
        """【R→G】update_content(draft_id, content, summary=X) → 正文与 summary 同行覆盖。

        当前 update_content 无 summary 形参 → TypeError unexpected kwarg（RED）。
        """
        db, engine = await _make_real_session()
        try:
            repo = SQLiteDraftRepository(db)
            d = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=CONTENT_V1,
                summary=SUMMARY_OLD,
                source_outline_id=OUTLINE_ID,
            )

            result = await repo.update_content(d.id, CONTENT_V2, summary=SUMMARY_NEW)

            assert result is not None
            assert result.content == CONTENT_V2
            assert result.summary == SUMMARY_NEW
        finally:
            await engine.dispose()

    async def test_update_content_draft_success(self) -> None:
        """【R→G】draft 稿 update_content 正常生效（status 守卫不误伤 draft 态）。"""
        db, engine = await _make_real_session()
        try:
            repo = SQLiteDraftRepository(db)
            d = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=CONTENT_V1,
                summary=SUMMARY_OLD,
                source_outline_id=OUTLINE_ID,
            )

            result = await repo.update_content(d.id, CONTENT_V2)

            assert result is not None
            assert result.content == CONTENT_V2
            assert result.summary == SUMMARY_OLD  # summary 缺省（None）保原值
        finally:
            await engine.dispose()
