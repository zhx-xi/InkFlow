"""F27 M3 草稿仓储 RED 契约测试 — DraftRepository（真实 in-memory SQLite 轨）.

被测模块（全部未实现，1l repo 整模块 RED 形态）:
    from inkflow.infrastructure.database.repositories.draft_repo import SQLiteDraftRepository

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. SQLiteDraftRepository（infrastructure/database/repositories/draft_repo.py 新建，
   异步 SQLAlchemy，构造签名 `SQLiteDraftRepository(db_session: AsyncSession)`，
   镜像 ExecutionStore/F34 audit_log_repo 模式）:

       class SQLiteDraftRepository:
           async def create(
               self, *, project_id: uuid.UUID, chapter_id: uuid.UUID | None,
               content: str, summary: str = "", agent_run_id: str | None = None,
           ) -> Draft:
               '''创建草稿（status=DRAFT），单次 commit（单工具单事务，ADR-F 约束②）.
               返回领域 Draft（id=uuid.UUID 字符串，created_at=UTC 字符串）.'''
           async def get(self, draft_id: str) -> Draft | None: ...
           async def list(
               self, project_id: uuid.UUID, status: DraftStatus | None = None,
               offset: int = 0, limit: int = 50,
           ) -> tuple[list[Draft], int]: ...
           async def update_status(
               self, draft_id: str, status: DraftStatus, confirmed_at: datetime | None = None,
           ) -> Draft | None: ...
           async def update_content(self, draft_id: str, content: str) -> Draft | None: ...

2. DraftORM（infrastructure/database/models/agent_run.py 或 draft.py 新建）:
   - 表名 drafts；列: id(str uuid4 主键) / project_id(FK projects.id, CASCADE) /
     chapter_id(FK chapters.id, nullable, CASCADE) / agent_run_id(str nullable) /
     content(Text) / summary(Text default "") / status(str default "draft") /
     created_at(DateTime UTC) / confirmed_at(DateTime nullable)
   - FK 级联与 audit_logs 对齐（F34 先例，E14 语义）
   - id 存储形态: uuid4 字符串（与 AgentExecutionORM.id 一致，SQLite 兼容）

3. 领域 Draft（domain/models/draft.py 新建，Pydantic）:

       class DraftStatus(StrEnum):
           DRAFT = "draft"
           CONFIRMED = "confirmed"
           REJECTED = "rejected"

       class Draft(BaseModel):
           id: str
           project_id: uuid.UUID
           chapter_id: uuid.UUID | None = None
           agent_run_id: str | None = None
           content: str
           status: DraftStatus = DraftStatus.DRAFT
           summary: str = ""
           created_at: datetime
           confirmed_at: datetime | None = None

RED 预期
--------
收集期失败（1l 整模块 RED 形态: pytest exit 2 / collected 0 items / 1 error）:
    ModuleNotFoundError: No module named
    'inkflow.infrastructure.database.repositories.draft_repo'
顶部仅 import 主契约模块（draft_repo）；ORM 惰性导入在 create_all 之前
（规则 1l：ORM 惰性导入必须在 create_all 之前——fixture 内 import）。

asyncio 模式: 本 venv（pytest-asyncio 1.4.0）实测头部 asyncio: mode=Mode.AUTO
（pyproject asyncio_mode = "auto" 生效）；文件级 pytestmark = pytest.mark.asyncio
双保险（STRICT/AUTO 两种模式均成立），全部用例 async def。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.infrastructure.database.repositories.draft_repo import (
    SQLiteDraftRepository,
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
CONTENT = "草稿正文内容。"
ZERO_PROJECT_ID = uuid.UUID(int=0)  # #275: rc9 缺陷数据签名（全零 UUID）


def _utcnow() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库.

    ORM 惰性导入必须在 create_all 之前（规则 1l）——Base.metadata 需先注册
    新表（DraftORM/ProjectORM/ChapterORM），否则 create_all 不建 drafts 表.
    """

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project(db_session):
    """1 个项目（drafts 表 FK 依赖 projects.id）."""
    from inkflow.infrastructure.database.models.project import ProjectORM

    proj = ProjectORM(name="测试项目")
    db_session.add(proj)
    await db_session.commit()
    await db_session.refresh(proj)
    return proj


@pytest.fixture
async def chapter(db_session, project):
    """1 个章节（drafts 表 chapter_id FK 依赖，可选）."""
    from inkflow.infrastructure.database.models.chapter import ChapterORM

    ch = ChapterORM(
        project_id=project.id,
        title="第一章",
        content="",
        status="draft",
        word_count=0,
        order_index=1.0,
    )
    db_session.add(ch)
    await db_session.commit()
    await db_session.refresh(ch)
    return ch


@pytest.mark.integration
class TestDraftRepository:
    """SQLiteDraftRepository 集成测试."""

    async def test_create_draft(self, db_session, project, chapter):
        """契约①: create 落库 status=DRAFT，返回领域 Draft 含 id/时间戳."""
        repo = SQLiteDraftRepository(db_session)

        draft = await repo.create(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            content=CONTENT,
            summary="测试草稿",
        )

        assert isinstance(draft, Draft)
        assert draft.status == DraftStatus.DRAFT
        assert draft.project_id == PROJECT_ID
        assert draft.content == CONTENT
        assert draft.summary == "测试草稿"
        assert isinstance(draft.id, str)
        assert isinstance(draft.created_at, datetime)

        # 持久化验证：读回
        fetched = await repo.get(draft.id)
        assert fetched is not None
        assert fetched.content == CONTENT
        assert fetched.status == DraftStatus.DRAFT

    async def test_create_draft_without_chapter(self, db_session, project):
        """契约②: chapter_id 可选（None = 确认时指定目标章节）."""
        repo = SQLiteDraftRepository(db_session)

        draft = await repo.create(project_id=PROJECT_ID, chapter_id=None, content=CONTENT)

        assert draft.chapter_id is None
        fetched = await repo.get(draft.id)
        assert fetched is not None
        assert fetched.chapter_id is None

    async def test_get_missing_returns_none(self, db_session, project):
        """契约③: get 对缺失草稿返回 None."""
        repo = SQLiteDraftRepository(db_session)

        assert await repo.get("00000000-0000-0000-0000-000000000000") is None

    async def test_list_filters_by_status(self, db_session, project, chapter):
        """契约④: list 按 project_id + status 过滤，分页倒序（created_at desc）."""
        repo = SQLiteDraftRepository(db_session)

        await repo.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content="草稿A")
        d2 = await repo.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content="草稿B")
        await repo.create(
            project_id=uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            chapter_id=None,
            content="其他项目草稿",
        )

        items, total = await repo.list(project_id=PROJECT_ID)
        assert total == 2
        assert {d.content for d in items} == {"草稿A", "草稿B"}

        # status 过滤
        await repo.update_status(d2.id, DraftStatus.CONFIRMED, confirmed_at=_utcnow())
        items_confirmed, total_confirmed = await repo.list(
            project_id=PROJECT_ID, status=DraftStatus.CONFIRMED
        )
        assert total_confirmed == 1
        assert items_confirmed[0].id == d2.id

    async def test_update_status_confirm(self, db_session, project, chapter):
        """契约⑤: update_status → CONFIRMED + confirmed_at 回填（确认流核心）."""
        repo = SQLiteDraftRepository(db_session)
        draft = await repo.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content=CONTENT)

        updated = await repo.update_status(draft.id, DraftStatus.CONFIRMED, confirmed_at=_utcnow())

        assert updated is not None
        assert updated.status == DraftStatus.CONFIRMED
        assert updated.confirmed_at is not None
        # 持久化读回
        fetched = await repo.get(draft.id)
        assert fetched is not None
        assert fetched.status == DraftStatus.CONFIRMED

    async def test_update_status_reject(self, db_session, project, chapter):
        """契约⑥: update_status → REJECTED（拒绝保留记录，供 F28 分析）."""
        repo = SQLiteDraftRepository(db_session)
        draft = await repo.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content=CONTENT)

        updated = await repo.update_status(draft.id, DraftStatus.REJECTED)

        assert updated is not None
        assert updated.status == DraftStatus.REJECTED
        assert updated.confirmed_at is None

    async def test_update_status_missing_returns_none(self, db_session, project):
        """契约⑦: update_status 对缺失草稿返回 None."""
        repo = SQLiteDraftRepository(db_session)

        result = await repo.update_status(
            "00000000-0000-0000-0000-000000000000", DraftStatus.CONFIRMED
        )
        assert result is None

    async def test_update_content(self, db_session, project, chapter):
        """契约⑧: update_content 修改草稿正文（确认前用户手动修改落库）."""
        repo = SQLiteDraftRepository(db_session)
        draft = await repo.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content="旧内容")

        updated = await repo.update_content(draft.id, "新内容")

        assert updated is not None
        assert updated.content == "新内容"
        fetched = await repo.get(draft.id)
        assert fetched is not None
        assert fetched.content == "新内容"

    async def test_prune_orphans_deletes_zero_project_drafts(self, db_session, project, chapter):
        """契约⑨（#275 清理）: prune_orphans 删除 project_id=全零 的草稿，正常草稿保留.

        RED 预期: SQLiteDraftRepository 无 prune_orphans → AttributeError FAILED。
        """
        repo = SQLiteDraftRepository(db_session)
        await repo.create(project_id=ZERO_PROJECT_ID, chapter_id=None, content="孤儿A")
        await repo.create(project_id=ZERO_PROJECT_ID, chapter_id=None, content="孤儿B")
        await repo.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content="正常草稿")

        count = await repo.prune_orphans()

        assert count == 2
        _, total_zero = await repo.list(project_id=ZERO_PROJECT_ID)
        assert total_zero == 0
        _, total_normal = await repo.list(project_id=PROJECT_ID)
        assert total_normal == 1

    async def test_prune_orphans_dry_run_counts_only(self, db_session, project, chapter):
        """契约⑩（#275 清理）: dry_run=True 只统计不删除."""
        repo = SQLiteDraftRepository(db_session)
        await repo.create(project_id=ZERO_PROJECT_ID, chapter_id=None, content="孤儿")

        count = await repo.prune_orphans(dry_run=True)

        assert count == 1
        _, total = await repo.list(project_id=ZERO_PROJECT_ID)
        assert total == 1
