"""#988 集成契约 — 草稿记录 source_outline_id → confirm 自取 → outlines 回填闭环（真 DB 轨）.

被测链路（真实装配，禁 mock 服务层）:
1. SQLiteDraftRepository.create(source_outline_id=X) 落库（DraftORM 新列）
2. get_draft_service(db) 装配（deps 已注入 chapter_creator/outline_bindder）
3. svc.confirm(draft.id) 无显式参数 → 草稿自取 → 自动建章 + 双回填:
   drafts.chapter_id 绑定 + outlines.chapter_id 回填（D4 生效值优先:
   显式 > draft.source_outline_id > None）
4. Draft 模型默认字段 + repo 透传 + _orm_to_domain 读回（当前全链缺失 → RED）

当前 RED 根因: repo.create 无 source_outline_id kwarg → TypeError（用例首步即炸）。

seed 形态镜像 test_draft_confirm_http_assembly_988.py: 小值 id（int↔UUID 惯例）
防随机 uuid4 溢出 SQLite INTEGER 列。
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

DRAFT_CONTENT = "这是 chat/book 轨 agent 写出的章节草稿正文（来源锚定集成契约）。"
DRAFT_SUMMARY = "第一章草稿摘要（自取回填）"


async def _make_real_session() -> tuple[AsyncSession, object]:
    """真实 in-memory aiosqlite + 单 AsyncSession（镜像 988 http_assembly）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db: AsyncSession = factory()
    return db, engine


async def _seed_project_volume_outline(db: AsyncSession) -> None:
    """seed 项目(id=7) + 卷(id=41) + 章 outline 点(id=51, volume_id=41)."""
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


class TestDraftSourceOutlineSelfFetch988:
    """#988 记录→自取→回填闭环：真 repo + 真装配 + 真 SQLite（无 mock）."""

    async def test_recorded_source_outline_confirm_backfills_without_param(self) -> None:
        """【R】create(source_outline_id) 记录 → confirm 无参自取 → 章点回填 + 绑定。

        当前 RED: repo.create 无该 kwarg → TypeError（GREEN 全链后转 PASS）。
        """
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
                source_outline_id=OUTLINE_UUID,  # 当前 TypeError → RED
            )

            # 记录持久化可读回（仓储列 ↔ 领域字段闭环）
            fetched = await repo.get(draft.id)
            assert fetched is not None
            assert fetched.source_outline_id == OUTLINE_UUID

            svc = get_draft_service(db)
            confirmed = await svc.confirm(draft.id)  # 无显式 source_outline_id → 自取

            assert confirmed.status.value == "confirmed"
            chapters = (await db.execute(select(ChapterORM))).scalars().all()
            assert len(chapters) == 1
            ch = chapters[0]
            assert ch.title == DRAFT_SUMMARY  # summary[:30] 派生（既有规则）
            assert ch.content == DRAFT_CONTENT
            assert ch.status == "final"
            assert ch.volume_id == VOLUME_ID_INT  # 草稿卷透传（#976 D3 既有语义）

            # D4 回填真数据验证：outlines.chapter_id = 新章
            outline_row = await db.get(OutlineORM, OUTLINE_ID_INT)
            assert outline_row is not None
            assert outline_row.chapter_id == ch.id
        finally:
            await engine.dispose()

    async def test_unrecorded_source_confirm_stays_unbound(self) -> None:
        """【R→G】未记录来源（chat 轨 fallback 前形态）→ confirm 不崩、无回填。

        当前 repo.create(source_outline_id=...) 本用例不调，走既有路径 PASS；
        GREEN 后语义不变（None → D4 不触发，防过度回填）。
        """
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
            assert draft.source_outline_id is None  # 当前 AttributeError → RED

            svc = get_draft_service(db)
            confirmed = await svc.confirm(draft.id)

            assert confirmed.status.value == "confirmed"
            outline_row = await db.get(OutlineORM, OUTLINE_ID_INT)
            assert outline_row is not None
            assert outline_row.chapter_id is None  # 无来源 → 零误绑
        finally:
            await engine.dispose()

    async def test_explicit_param_overrides_recorded_value(self) -> None:
        """【R】显式 confirm(source_outline_id=Y) 优先于草稿记录值（决策 1 契约）.

        seed 两章点（51 记录 / 52 显式）→ 回填目标是 52，不是 51。
        """
        db, engine = await _make_real_session()
        try:
            await _seed_project_volume_outline(db)
            # 注意: outlines.volume_id 全表唯一索引 uq_outlines_volume_id（#592），
            # 第二章点不再挂卷 41（D4 回填与 volume_id 无关）。
            db.add(
                OutlineORM(
                    id=52,
                    project_id=7,
                    name="显式目标章点",
                    description="",
                    sort_order=1,
                    level="chapter",
                    volume_id=None,
                )
            )
            await db.commit()
            repo = SQLiteDraftRepository(db)
            draft = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=DRAFT_CONTENT,
                summary=DRAFT_SUMMARY,
                volume_id=VOLUME_UUID,
                source_outline_id=OUTLINE_UUID,  # 记录 51
            )

            svc = get_draft_service(db)
            await svc.confirm(draft.id, source_outline_id=uuid.UUID(int=52))  # 显式 52

            row51 = await db.get(OutlineORM, OUTLINE_ID_INT)
            row52 = await db.get(OutlineORM, 52)
            assert row51 is not None and row52 is not None
            ch = (await db.execute(select(ChapterORM))).scalars().one()
            assert row52.chapter_id == ch.id  # 显式优先
            assert row51.chapter_id is None  # 记录值被覆盖不回填
        finally:
            await engine.dispose()

    async def test_chapter_service_created_chapter_final_state(self) -> None:
        """【R】自动建章经真实 ChapterService 落库 FINAL（既有 D4 行为，新列共存回归）.

        与用例 1 同链路但经 chapter_svc 读回（领域面读，非 ORM 直读）。
        """
        db, engine = await _make_real_session()
        try:
            await _seed_project_volume_outline(db)
            repo = SQLiteDraftRepository(db)
            draft = await repo.create(
                project_id=PROJECT_ID,
                chapter_id=None,
                content=DRAFT_CONTENT,
                summary=DRAFT_SUMMARY,
                source_outline_id=OUTLINE_UUID,
            )

            svc = get_draft_service(db)
            confirmed = await svc.confirm(draft.id)
            assert confirmed.chapter_id is not None

            chapter_svc = ChapterService(db)
            chapter = await chapter_svc.get_chapter(confirmed.chapter_id)
            assert chapter is not None
            assert chapter.status.value == "final"
            assert chapter.content == DRAFT_CONTENT
        finally:
            await engine.dispose()
