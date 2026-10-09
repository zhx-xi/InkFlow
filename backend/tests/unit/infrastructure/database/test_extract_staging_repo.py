"""SQLExtractStagingRepository 集成测试 — in-memory SQLite（#1545 §5.9 补测）.

覆盖 ExtractionStagingRepositoryProtocol 全部方法（spec §5.9 / §9 仓储测试）:
- add_many 批量落库（返回写入行数；空列表 → 0 零写入）
- list_by_batch 字段往返保真（entity_type / action / name / payload；name 取自
  payload、写入序 id 升序）；未命中 → 空列表
- delete_by_batch 返回删除行数 + 幂等（重复删除 → 0，不报错）
- 项目隔离（不同 project_id 同 batch_id 互不可见 / 互不删除）

注: fixture 显式开启 PRAGMA foreign_keys=ON（SQLite 默认关闭），
FK CASCADE 语义才生效（同 test_extraction_run_repo.py 惯例）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.extraction import StagedEntry
from inkflow.infrastructure.database.models.extract_staging import ExtractStagingORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.extract_staging_repo import (
    SQLExtractStagingRepository,
)

BATCH = "ext-abc123"


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（启用 FK 级联）."""
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
    """一个基础项目（extract_staging 的 FK 依赖）."""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _pid(project: ProjectORM) -> uuid.UUID:
    """持久化返回的 project.id（int）→ 领域 UUID（UUID.int 陷阱）."""
    return uuid.UUID(int=project.id)


def _entry(
    entity_type: str,
    action: str,
    payload: dict,
) -> StagedEntry:
    """构造待暂存条目（name 由 payload 的 ``name`` 派生，同仓储读回口径）."""
    return StagedEntry(
        entity_type=entity_type,
        action=action,
        name=payload.get("name", ""),
        payload=payload,
    )


async def _count_rows(db_session, project_id: int) -> int:
    """直接查表统计某项目的暂存行数（绕过 repo，验证持久化真相）."""
    result = await db_session.execute(
        select(func.count())
        .select_from(ExtractStagingORM)
        .where(ExtractStagingORM.project_id == project_id)
    )
    return result.scalar_one()


@pytest.mark.integration
class TestExtractStagingRepository:
    """SQLExtractStagingRepository 集成测试."""

    # ── add_many ──

    async def test_add_many_persists_and_returns_row_count(self, db_session, project):
        """add_many 批量写入 → 返回写入行数 + 落库（直接查表印证）."""
        repo = SQLExtractStagingRepository(db_session)
        entries = [
            _entry("character", "create", {"id": "c1", "name": "角色甲"}),
            _entry("world_setting", "update", {"id": "w1", "name": "秘境", "payload_key": "v"}),
        ]

        written = await repo.add_many(_pid(project), BATCH, "character", entries)

        assert written == 2
        assert await _count_rows(db_session, project.id) == 2

    async def test_add_many_empty_writes_nothing(self, db_session, project):
        """空列表 → 返回 0 且零写入（无行落库）."""
        repo = SQLExtractStagingRepository(db_session)

        written = await repo.add_many(_pid(project), BATCH, "character", [])

        assert written == 0
        assert await _count_rows(db_session, project.id) == 0

    # ── list_by_batch ──

    async def test_list_by_batch_roundtrip_fields_fidelity(self, db_session, project):
        """list_by_batch 字段往返保真：entity_type / action / name / payload（写入序）."""
        repo = SQLExtractStagingRepository(db_session)
        char_payload = {"id": "c1", "name": "角色甲", "personality": "沉稳"}
        world_payload = {"id": "w1", "name": "秘境", "nested": {"k": [1, 2]}}
        await repo.add_many(
            _pid(project),
            BATCH,
            "character",
            [
                _entry("character", "create", char_payload),
                _entry("world_setting", "update", world_payload),
            ],
        )

        items = await repo.list_by_batch(_pid(project), BATCH)

        assert len(items) == 2
        assert [(i.entity_type, i.action) for i in items] == [
            ("character", "create"),
            ("world_setting", "update"),
        ]
        assert [i.name for i in items] == ["角色甲", "秘境"]
        # payload 逐字段保真（含嵌套结构）
        assert items[0].payload == char_payload
        assert items[1].payload == world_payload

    async def test_list_by_batch_miss_returns_empty(self, db_session, project):
        """未命中批次 → 空列表（其他批次写入不影响本批读取）."""
        repo = SQLExtractStagingRepository(db_session)
        await repo.add_many(
            _pid(project), BATCH, "character", [_entry("character", "create", {"name": "x"})]
        )

        assert await repo.list_by_batch(_pid(project), "ext-unknown") == []

    # ── delete_by_batch ──

    async def test_delete_by_batch_returns_count_and_is_idempotent(self, db_session, project):
        """delete_by_batch 返回删除行数；重复删除 → 0（幂等，不报错）."""
        repo = SQLExtractStagingRepository(db_session)
        await repo.add_many(
            _pid(project),
            BATCH,
            "character",
            [
                _entry("character", "create", {"name": "甲"}),
                _entry("character", "update", {"name": "乙"}),
            ],
        )

        deleted = await repo.delete_by_batch(_pid(project), BATCH)

        assert deleted == 2
        assert await _count_rows(db_session, project.id) == 0
        assert await repo.list_by_batch(_pid(project), BATCH) == []
        # 幂等：重复删除 → 0
        assert await repo.delete_by_batch(_pid(project), BATCH) == 0

    # ── 项目隔离 ──

    async def test_project_isolation(self, db_session, project):
        """同一 batch_id 下不同项目互不可见 / 互不删除."""
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)

        repo = SQLExtractStagingRepository(db_session)
        await repo.add_many(
            _pid(project), BATCH, "character", [_entry("character", "create", {"name": "甲"})]
        )
        await repo.add_many(
            _pid(other), BATCH, "character", [_entry("character", "create", {"name": "乙"})]
        )

        # 读取隔离：各见各的
        mine = await repo.list_by_batch(_pid(project), BATCH)
        theirs = await repo.list_by_batch(_pid(other), BATCH)
        assert [i.name for i in mine] == ["甲"]
        assert [i.name for i in theirs] == ["乙"]

        # 删除隔离：删本项目不影响其他项目
        assert await repo.delete_by_batch(_pid(project), BATCH) == 1
        assert await repo.list_by_batch(_pid(project), BATCH) == []
        assert [i.name for i in await repo.list_by_batch(_pid(other), BATCH)] == ["乙"]
