"""#996/#997 RED 全链集成契约 — 锚点落库 + 同章幂等覆盖 + confirm 回填（真 DB 轨）.

契约真相源: specs/f27-writer-agent/spec.md §5.2 + specs/f44-book-orchestrator/spec.md §5.2。

被测链路（真实装配，禁 mock 服务层）:
1. SaveDraftToolDeps 带锚点（expected_source_outline_id=OUTLINE、
   expected_volume_outline_id=VOLUME_OUTLINE）+ 真实 DraftService(真实 SQLiteDraftRepository)
   → tool.func 调 2 次（第二次新内容）。
2. #997 幂等: 第二次命中 → 覆盖 content，drafts 表该 outline 仅 1 行、
   content==第二版、source_outline_id 非空、volume_id==卷 UUID；两次 payload draft_id 相同。
3. DraftService.confirm（chapter_creator + outline_bindder）→ bindder 收到
   (str(source_outline_id), str(新章 id))（D4 回填真数据验证）。

当前实现对照（RED）: 工具硬编码 source_outline_id=None + volume_lookup 传 None + 从不调
find_pending（每次 create 新行）→ ① 二稿并存（drafts 表该 outline 行数≠1）② content 非
第二版 ③ 两次 draft_id 不同 ④ confirm 无效 source_outline_id → bindder 不被调。全链 RED。

seed 形态镜像 tests/integration/test_book_run_953_bridge.py /
test_draft_source_outline_backfill_988.py:
真实 in-memory aiosqlite + 小值 UUID（int↔ORM 惯例防溢出）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.services.draft_service import DraftService
from inkflow.infrastructure.agent.tools.save_draft_tool import (
    SaveDraftToolDeps,
    build_save_draft_tool,
)
from inkflow.infrastructure.database.models.agent_run import DraftORM
from inkflow.infrastructure.database.repositories.draft_repo import (
    SQLiteDraftRepository,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# 小值 UUID（int↔ORM 惯例）：项目 id=7、卷 id=41、大纲章节点 id=51、自动建章 id=61
PROJECT_ID = uuid.UUID(int=7)
VOLUME_UUID = uuid.UUID(int=41)
VOLUME_OUTLINE_ID = uuid.UUID(int=41)
OUTLINE_ID = uuid.UUID(int=51)
NEW_CHAPTER_ID = uuid.UUID(int=61)
CONTENT_V1 = "第一版草稿正文。"
CONTENT_V2 = "第二版草稿正文（幂等覆盖后）。"
SUMMARY_V1 = "第一版摘要"


class _DummyAudit:
    """极简审计替身：record 为 AsyncMock（错误形态来自会话/锁，非审计）。"""

    def __init__(self) -> None:
        self.record = AsyncMock(return_value=None)


class _FakeChapterCreator:
    """confirm 自动建章替身：记录调用并返回固定新章 id（SimpleNamespace.id）。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def __call__(self, project_id, title, *, volume_id=None, content=""):
        self.calls.append((project_id, title, volume_id))
        return SimpleNamespace(id=NEW_CHAPTER_ID)


async def _make_real_session() -> tuple[AsyncSession, object]:
    """真实 in-memory aiosqlite + 单 AsyncSession（镜像 953 bridge 形态）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db: AsyncSession = factory()
    return db, engine


class TestBookDraftAnchorIdemChain996997:
    """全链行为锁：#996 锚点落库 + #997 幂等覆盖 + confirm 回填（真 DB，无 mock 服务层）。"""

    async def test_anchor_chain_idempotent_overwrite_and_confirm_backfill(self) -> None:
        """【R】① 同链 2 次 save_draft → 1 行 + content==v2 + source_outline_id 非空 +
        volume_id==卷 UUID；② 两次 payload draft_id 相同；③ confirm → bindder 回填。

        当前实现（RED）: 二稿并存 / content 非 v2 / 两次 draft_id 不同 / bindder 不被调。
        """
        db, engine = await _make_real_session()
        try:
            repo = SQLiteDraftRepository(db)
            creator = _FakeChapterCreator()
            recorded_binds: list[tuple] = []

            async def _outline_bindder(source_outline: str, chapter_id: str) -> None:
                recorded_binds.append((source_outline, chapter_id))

            draft_svc = DraftService(
                draft_repo=repo,
                chapter_creator=creator,
                outline_bindder=_outline_bindder,
            )

            async def _volume_lookup(project_id, key):
                if key is None:
                    return None
                return str(VOLUME_UUID)

            deps = SaveDraftToolDeps(
                draft_service=draft_svc,
                audit_service=_DummyAudit(),
                expected_project_id=PROJECT_ID,
                # book 轨 expected_chapter_id 恒 None（confirm 自动建章）
                expected_chapter_id=None,
                volume_lookup=_volume_lookup,
            )
            # #996 锚点字段当前 dataclass 缺失 → setattr 注入（行为断言成为 RED 主锚）
            deps.expected_source_outline_id = OUTLINE_ID
            deps.expected_volume_outline_id = VOLUME_OUTLINE_ID
            tool = build_save_draft_tool(deps)

            # ① 第一次 save_draft（v1）
            r1 = json.loads(await tool.func(content=CONTENT_V1, summary=SUMMARY_V1))
            assert r1["ok"] is True
            first_draft_id = r1["draft_id"]

            # ② 第二次 save_draft（v2）——应幂等覆盖同稿，不新增行
            r2 = json.loads(await tool.func(content=CONTENT_V2))
            assert r2["ok"] is True
            second_draft_id = r2["draft_id"]
            assert second_draft_id == first_draft_id
            assert r2.get("overwritten") is True

            # 该 outline 在 drafts 表仅 1 行，content==v2，source_outline_id 非空，volume_id==卷
            rows = (
                await db.execute(
                    select(DraftORM).where(DraftORM.source_outline_id == str(OUTLINE_ID))
                )
            ).scalars().all()
            assert len(rows) == 1, f"同章幂等应仅 1 行，实际 {len(rows)}"
            row = rows[0]
            assert row.content == CONTENT_V2
            assert row.source_outline_id == str(OUTLINE_ID)
            assert row.volume_id == str(VOLUME_UUID)

            fetched_draft = await draft_svc.get(first_draft_id)
            assert fetched_draft is not None
            assert fetched_draft.content == CONTENT_V2
            assert fetched_draft.source_outline_id == OUTLINE_ID
            assert fetched_draft.volume_id == VOLUME_UUID

            # ③ confirm（自动建章 + outline_bindder D4 回填）
            confirmed = await draft_svc.confirm(first_draft_id)
            assert confirmed.status.value == "confirmed"

            assert creator.calls, "confirm 应触发自动建章（chapter_creator）"
            assert recorded_binds, "D4 回填应触发 outline_bindder"
            assert recorded_binds[-1] == (str(OUTLINE_ID), str(NEW_CHAPTER_ID))
        finally:
            await engine.dispose()
