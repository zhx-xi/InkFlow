"""#988 草稿来源大纲节点绑定 — SQLiteDraftRepository source_outline_id 持久化 RED 契约.

被测模块（当前未实现，对照 origin/main 13b1305）:
- DraftORM 无 source_outline_id 列（infrastructure/database/models/agent_run.py:135+）
- SQLiteDraftRepository.create 不接收该 kwarg → TypeError（【R】）
- _orm_to_domain 不透传该列 → get/list 返回 Draft.source_outline_id 缺失（【R】）

GREEN 必实现（父侧定稿契约）:
- DraftORM 增列: source_outline_id: Mapped[str | None] = mapped_column(
    String(36), nullable=True, index=True)（镜像 volume_id 列形态，可空无 FK）
- SQLiteDraftRepository.create(*, project_id, chapter_id, content, summary="",
  agent_run_id=None, volume_id=None, source_outline_id=None) → str(uuid) 落库
- _orm_to_domain: source_outline_id=uuid.UUID(orm.source_outline_id) if ... else None

fixture 镜像 tests/unit/infrastructure/database/test_draft_repo.py（真 in-memory
aiosqlite + Base.metadata.create_all + 独立 session）。Draft.id/project_id 为
String(36) 列（无 SQLite INTEGER 溢出风险，随机 uuid4 无害）。

asyncio 模式: pyproject asyncio_mode = "auto"；文件级 pytestmark 双保险。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.infrastructure.database.repositories.draft_repo import (
    SQLiteDraftRepository,
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
OUTLINE_ID = uuid.UUID(int=51)  # 小值 UUID（int↔UUID 惯例，与真实 outline 行主键同形）
CONTENT = "草稿正文内容（source_outline_id 持久化契约）。"


def _utcnow() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（镜像 test_draft_repo）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project(db_session):
    """1 个项目（drafts.project_id 语义依赖，镜像 test_draft_repo.project fixture）。"""
    from inkflow.infrastructure.database.models.project import ProjectORM

    proj = ProjectORM(name="测试项目")
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


class TestDraftRepoSourceOutline:
    """#988: source_outline_id 列落库/读回/ORM 直读持久化契约."""

    async def test_create_persists_source_outline_id(self, db_session, project):
        """【R】create(source_outline_id=X) → 返回实体与读回实体均携带该值.

        当前 repo.create 无该形参 → TypeError（RED）。
        """
        repo = SQLiteDraftRepository(db_session)

        draft = await repo.create(
            project_id=PROJECT_ID,
            chapter_id=None,
            content=CONTENT,
            source_outline_id=OUTLINE_ID,
        )

        assert isinstance(draft, Draft)
        assert draft.source_outline_id == OUTLINE_ID

        fetched = await repo.get(draft.id)
        assert fetched is not None
        assert fetched.source_outline_id == OUTLINE_ID

    async def test_create_without_source_outline_id_is_none(self, db_session, project):
        """【R→G】不传 source_outline_id → 列落 NULL，读回 None（存量语义守护）.

        当前 create(source_outline_id=...) 不存在但本用例不调该形参 → 当前 PASS；
        GREEN 后仍 PASS（默认 None 透传）。
        """
        repo = SQLiteDraftRepository(db_session)

        draft = await repo.create(
            project_id=PROJECT_ID,
            chapter_id=None,
            content=CONTENT,
        )

        assert draft.source_outline_id is None
        fetched = await repo.get(draft.id)
        assert fetched is not None
        assert fetched.source_outline_id is None

    async def test_column_stored_as_uuid_string(self, db_session, project):
        """【R】行级真实列存在且存 str(uuid)（迁移落库实证，镜像 update_chapter_binding 直读法）.

        当前 drafts 表无 source_outline_id 列 → SELECT 抛 OperationalError（RED）。
        """
        repo = SQLiteDraftRepository(db_session)
        draft = await repo.create(
            project_id=PROJECT_ID,
            chapter_id=None,
            content=CONTENT,
            source_outline_id=OUTLINE_ID,
        )

        row = (
            await db_session.execute(
                text("SELECT source_outline_id FROM drafts WHERE id = :did"),
                {"did": draft.id},
            )
        ).scalar()

        assert row == str(OUTLINE_ID)

    async def test_list_returns_source_outline_id(self, db_session, project):
        """【R】list 页内实体透传 source_outline_id（响应 DTO 数据源）.

        当前 create 不接受该 kwarg → TypeError（RED）。
        """
        repo = SQLiteDraftRepository(db_session)
        await repo.create(
            project_id=PROJECT_ID,
            chapter_id=None,
            content="草稿A",
            source_outline_id=OUTLINE_ID,
        )
        await repo.create(project_id=PROJECT_ID, chapter_id=None, content="草稿B")

        items, total = await repo.list(project_id=PROJECT_ID)

        assert total == 2
        by_content = {d.content: d for d in items}
        assert by_content["草稿A"].source_outline_id == OUTLINE_ID
        assert by_content["草稿B"].source_outline_id is None

    async def test_update_status_preserves_source_outline_id(self, db_session, project):
        """【R→G】状态迁移（确认流）不丢来源字段（Draft 自取通道的持久化前提）.

        update_status 走 ORM 行改列 → 未触碰列保持；当前 create 拒收 kwarg → RED。
        """
        repo = SQLiteDraftRepository(db_session)
        draft = await repo.create(
            project_id=PROJECT_ID,
            chapter_id=None,
            content=CONTENT,
            source_outline_id=OUTLINE_ID,
        )

        updated = await repo.update_status(draft.id, DraftStatus.CONFIRMED, confirmed_at=_utcnow())

        assert updated is not None
        assert updated.source_outline_id == OUTLINE_ID
