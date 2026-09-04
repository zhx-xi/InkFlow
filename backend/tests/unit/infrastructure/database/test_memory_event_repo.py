"""F28 M3 事件仓储 RED 契约测试 — SQLiteMemoryEventRepository（真实 in-memory SQLite 轨）.

被测模块（全部未实现，1l repo 整模块 RED 形态）:
    from inkflow.infrastructure.database.repositories.memory_event_repo import (
        SQLiteMemoryEventRepository,
    )

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. SQLiteMemoryEventRepository（infrastructure/database/repositories/
   memory_event_repo.py 新建，异步 SQLAlchemy，构造签名
   `SQLiteMemoryEventRepository(db_session: AsyncSession)`，
   镜像 F27 draft_repo 模式）:

       class SQLiteMemoryEventRepository:
           async def create(
               self, *, project_id: uuid.UUID, draft_id: str | None = None,
               chapter_id: uuid.UUID | None = None,
               agent_run_id: str | None = None,
               event_type: MemoryEventType,
               before_content: str | None = None,
               after_content: str | None = None,
           ) -> MemoryEvent: ...
           async def list_by_project(
               self, project_id: uuid.UUID,
               event_type: MemoryEventType | None = None,
               offset: int = 0, limit: int = 50,
           ) -> tuple[list[MemoryEvent], int]: ...
           async def list_edited_by_project(
               self, project_id: uuid.UUID,
           ) -> list[MemoryEvent]: ...
           async def count_by_project(self, project_id: uuid.UUID) -> int: ...
           async def delete_by_project(self, project_id: uuid.UUID) -> int: ...

   语义: list_by_project 按 project_id + event_type 过滤，created_at desc，
   分页返回 (列表, total)；list_edited_by_project 只 DRAFT_EDITED，
   created_at asc（提取顺序稳定）；count_by_project 返回项目事件总数；
   delete_by_project 返回删除行数。

2. diff_chars 计算归属歧义（父侧契约注明）: create 语义 =
   len(after_content or "") - len(before_content or "")，但服务层也可能
   计算——GREEN 时定。本文件只锁「create 返回的 diff_chars 与读回一致 +
   类型 int」，不锁具体值。

3. 领域 MemoryEvent/MemoryEventType（domain/models/memory_event.py 新建，
   Pydantic + StrEnum，model_config={"from_attributes": True}）:

       class MemoryEventType(StrEnum):
           DRAFT_EDITED = "draft_edited"
           DRAFT_REJECTED = "draft_rejected"
           DRAFT_CONFIRMED = "draft_confirmed"

       class MemoryEvent(BaseModel):
           id: str
           project_id: uuid.UUID
           draft_id: str | None = None
           chapter_id: uuid.UUID | None = None
           agent_run_id: str | None = None
           event_type: MemoryEventType
           before_content: str | None = None
           after_content: str | None = None
           diff_chars: int = 0
           created_at: datetime

4. ORM（infrastructure/database/models/preference.py 新建，
   ProjectPreferenceORM + MemoryEventORM 两表同文件）: memory_events 表列
   （spec §2.3）— id(String36 PK default uuid4) / project_id(String36 idx
   无 FK) / draft_id(String36) / chapter_id(String36) / agent_run_id(
   String36) / event_type(String20) / before_content(Text) / after_content(
   Text) / diff_chars(Integer) / created_at(DateTime)。全部 FK 可空且无 FK
   声明（镜像 drafts 先例）。

RED 预期
--------
收集期失败（1l 整模块 RED 形态: pytest exit 2 / collected 0 items /
1 error）:
    ModuleNotFoundError: No module named
    'inkflow.infrastructure.database.repositories.memory_event_repo'
顶部仅 import 主契约模块（memory_event_repo）；domain models / ORM models
全部惰性（fixture 与用例体内 import）——部分落地态（领域层先于基础设施）
收集错误保持聚焦主模块（规则 1l）。

asyncio 模式: 本 venv pytest-asyncio mode=Mode.AUTO（pyproject
asyncio_mode = "auto" 生效）；文件级 pytestmark = pytest.mark.asyncio
双保险（STRICT/AUTO 两种模式均成立），全部用例 async def。
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.infrastructure.database.repositories.memory_event_repo import (
    SQLiteMemoryEventRepository,
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
PROJECT_ID_2 = uuid.UUID("87654321-4321-8765-4321-876543218765")
CHAPTER_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库.

    ORM 惰性导入必须在 create_all 之前（规则 1l）——Base.metadata 需先注册
    新表（MemoryEventORM），否则 create_all 不建 memory_events 表.
    """

    # 惰性：RED 阶段模块未实现（create_all 前注册表——load-bearing）
    from inkflow.infrastructure.database.models.preference import (  # noqa: F401  # 惰性导入触发 Base.metadata 表注册（create_all 需要）
        MemoryEventORM,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _create_event(repo, *, event_type, project_id=PROJECT_ID, **kw):
    """经 repo.create 落库一条事件（event_type 必填，其余字段可覆盖）."""
    values = {
        "project_id": project_id,
        "draft_id": None,
        "chapter_id": None,
        "agent_run_id": None,
        "before_content": None,
        "after_content": None,
    }
    values.update(kw)
    return await repo.create(event_type=event_type, **values)


async def _insert_event_direct(db_session, *, project_id, event_type, draft_id, created_at):
    """排序/过滤造数：repo.create 不保留显式 created_at（DB 默认 _utcnow）."""
    from inkflow.infrastructure.database.models.preference import (
        MemoryEventORM,
    )

    await db_session.execute(
        insert(MemoryEventORM).values(
            project_id=str(project_id),
            event_type=event_type,
            draft_id=draft_id,
            diff_chars=0,
            created_at=created_at,
        )
    )
    await db_session.commit()


@pytest.mark.integration
class TestSQLiteMemoryEventRepository:
    """SQLiteMemoryEventRepository 集成测试（真实 in-memory SQLite 轨）."""

    async def test_create_roundtrips_full_fields(self, db_session):
        """契约①: create 落库全字段（含全部可选关联 id），list 读回等值."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.memory_event import MemoryEvent, MemoryEventType

        repo = SQLiteMemoryEventRepository(db_session)
        event = await repo.create(
            project_id=PROJECT_ID,
            draft_id="draft-123",
            chapter_id=CHAPTER_ID,
            agent_run_id="run-456",
            event_type=MemoryEventType.DRAFT_EDITED,
            before_content="旧内容",
            after_content="新内容",
        )

        assert isinstance(event, MemoryEvent)
        assert event.project_id == PROJECT_ID
        assert event.draft_id == "draft-123"
        assert event.chapter_id == CHAPTER_ID
        assert event.agent_run_id == "run-456"
        assert event.event_type == MemoryEventType.DRAFT_EDITED
        assert event.before_content == "旧内容"
        assert event.after_content == "新内容"
        assert isinstance(event.created_at, datetime)

        # 持久化验证：读回
        items, total = await repo.list_by_project(PROJECT_ID)
        assert total == 1
        fetched = items[0]
        assert fetched.draft_id == "draft-123"
        assert fetched.chapter_id == CHAPTER_ID
        assert fetched.agent_run_id == "run-456"
        assert fetched.event_type == MemoryEventType.DRAFT_EDITED
        assert fetched.before_content == "旧内容"
        assert fetched.after_content == "新内容"

    async def test_create_minimal_fields_default_none(self, db_session):
        """契约②: 仅 project_id + event_type，其余可选字段缺省 None."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.memory_event import MemoryEventType

        repo = SQLiteMemoryEventRepository(db_session)
        event = await repo.create(project_id=PROJECT_ID, event_type=MemoryEventType.DRAFT_REJECTED)

        assert isinstance(event.id, str)
        assert len(event.id) == 36
        assert event.draft_id is None
        assert event.chapter_id is None
        assert event.agent_run_id is None
        assert event.before_content is None
        assert event.after_content is None

    async def test_diff_chars_field_roundtrips(self, db_session):
        """契约③: diff_chars 落库读回一致（值由谁计算 GREEN 时定，见文件头）."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.memory_event import MemoryEventType

        repo = SQLiteMemoryEventRepository(db_session)
        event = await repo.create(
            project_id=PROJECT_ID,
            event_type=MemoryEventType.DRAFT_EDITED,
            before_content="abc",
            after_content="abcdef",
        )

        assert isinstance(event.diff_chars, int)
        items, total = await repo.list_by_project(PROJECT_ID)
        assert total == 1
        assert items[0].diff_chars == event.diff_chars

    async def test_list_by_project_filters_and_total(self, db_session):
        """契约④: list_by_project 按 project_id 过滤，返回 (列表, total)."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.memory_event import MemoryEventType

        repo = SQLiteMemoryEventRepository(db_session)
        await _create_event(repo, event_type=MemoryEventType.DRAFT_EDITED, draft_id="D1")
        await _create_event(repo, event_type=MemoryEventType.DRAFT_REJECTED, draft_id="R1")
        await _create_event(
            repo,
            event_type=MemoryEventType.DRAFT_EDITED,
            project_id=PROJECT_ID_2,
            draft_id="DX",
        )

        items, total = await repo.list_by_project(PROJECT_ID)

        assert total == 2
        assert {e.draft_id for e in items} == {"D1", "R1"}

    async def test_list_by_project_filters_by_event_type(self, db_session):
        """契约⑤: event_type 过滤（不传 = 全部）."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.memory_event import MemoryEventType

        repo = SQLiteMemoryEventRepository(db_session)
        await _create_event(repo, event_type=MemoryEventType.DRAFT_EDITED, draft_id="D1")
        await _create_event(repo, event_type=MemoryEventType.DRAFT_REJECTED, draft_id="R1")

        items, total = await repo.list_by_project(
            PROJECT_ID, event_type=MemoryEventType.DRAFT_REJECTED
        )

        assert total == 1
        assert [e.draft_id for e in items] == ["R1"]

    async def test_list_by_project_sorts_created_at_desc(self, db_session):
        """契约⑥: created_at desc（最新在前）——直插显式时间造数."""
        repo = SQLiteMemoryEventRepository(db_session)
        await _insert_event_direct(
            db_session,
            project_id=PROJECT_ID,
            event_type="draft_edited",
            draft_id="D1",
            created_at=datetime(2026, 8, 1, 10, 0, 0),
        )
        await _insert_event_direct(
            db_session,
            project_id=PROJECT_ID,
            event_type="draft_edited",
            draft_id="D2",
            created_at=datetime(2026, 8, 1, 11, 0, 0),
        )
        await _insert_event_direct(
            db_session,
            project_id=PROJECT_ID,
            event_type="draft_edited",
            draft_id="D3",
            created_at=datetime(2026, 8, 1, 12, 0, 0),
        )

        items, total = await repo.list_by_project(PROJECT_ID)

        assert total == 3
        assert [e.draft_id for e in items] == ["D3", "D2", "D1"]

    async def test_list_by_project_pagination(self, db_session):
        """契约⑦: offset/limit 分页，total 恒为全量计数."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.memory_event import MemoryEventType

        repo = SQLiteMemoryEventRepository(db_session)
        for i in range(5):
            await _create_event(repo, event_type=MemoryEventType.DRAFT_EDITED, draft_id=f"D{i}")

        page1, total = await repo.list_by_project(PROJECT_ID, offset=0, limit=2)
        assert total == 5
        assert len(page1) == 2

        last_page, total_last = await repo.list_by_project(PROJECT_ID, offset=4, limit=2)
        assert total_last == 5
        assert len(last_page) == 1

        page_all, _ = await repo.list_by_project(PROJECT_ID, offset=0, limit=50)
        assert len(page_all) == 5

    async def test_list_edited_by_project_only_edited_asc(self, db_session):
        """契约⑧: 只含 DRAFT_EDITED，created_at asc（提取顺序稳定）."""
        repo = SQLiteMemoryEventRepository(db_session)
        await _insert_event_direct(
            db_session,
            project_id=PROJECT_ID,
            event_type="draft_edited",
            draft_id="D1",
            created_at=datetime(2026, 8, 1, 10, 0, 0),
        )
        await _insert_event_direct(
            db_session,
            project_id=PROJECT_ID,
            event_type="draft_rejected",
            draft_id="R1",
            created_at=datetime(2026, 8, 1, 11, 0, 0),
        )
        await _insert_event_direct(
            db_session,
            project_id=PROJECT_ID,
            event_type="draft_edited",
            draft_id="D3",
            created_at=datetime(2026, 8, 1, 12, 0, 0),
        )
        await _insert_event_direct(
            db_session,
            project_id=PROJECT_ID_2,
            event_type="draft_edited",
            draft_id="DX",
            created_at=datetime(2026, 8, 1, 12, 30, 0),
        )

        items = await repo.list_edited_by_project(PROJECT_ID)

        assert [e.draft_id for e in items] == ["D1", "D3"]

    async def test_list_edited_by_project_empty_when_no_edited(self, db_session):
        """契约⑨: 无 DRAFT_EDITED 事件 → 空列表."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.memory_event import MemoryEventType

        repo = SQLiteMemoryEventRepository(db_session)
        await _create_event(repo, event_type=MemoryEventType.DRAFT_REJECTED, draft_id="R1")

        assert await repo.list_edited_by_project(PROJECT_ID) == []

    async def test_count_by_project(self, db_session):
        """契约⑩: count_by_project 只统计本项目事件."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.memory_event import MemoryEventType

        repo = SQLiteMemoryEventRepository(db_session)
        await _create_event(repo, event_type=MemoryEventType.DRAFT_EDITED)
        await _create_event(repo, event_type=MemoryEventType.DRAFT_REJECTED)
        await _create_event(repo, event_type=MemoryEventType.DRAFT_EDITED, project_id=PROJECT_ID_2)

        assert await repo.count_by_project(PROJECT_ID) == 2

    async def test_count_by_project_returns_zero(self, db_session):
        """契约⑪: 无事件项目 → 0."""
        repo = SQLiteMemoryEventRepository(db_session)

        assert await repo.count_by_project(PROJECT_ID) == 0

    async def test_delete_by_project_returns_count_and_isolates(self, db_session):
        """契约⑫: delete_by_project 返回删除行数，其他项目事件保留."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.memory_event import MemoryEventType

        repo = SQLiteMemoryEventRepository(db_session)
        await _create_event(repo, event_type=MemoryEventType.DRAFT_EDITED)
        await _create_event(repo, event_type=MemoryEventType.DRAFT_REJECTED)
        await _create_event(repo, event_type=MemoryEventType.DRAFT_EDITED, project_id=PROJECT_ID_2)

        deleted = await repo.delete_by_project(PROJECT_ID)

        assert deleted == 2
        assert await repo.count_by_project(PROJECT_ID) == 0
        assert await repo.count_by_project(PROJECT_ID_2) == 1
