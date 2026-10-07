"""#1485 batch_id 列迁移三形态 + 按批次删除仓储契约（RED）。

被测（GREEN 才实现）:
- ``inkflow.core.migrations_extraction_batch.ensure_world_settings_batch_id_column``
- ``inkflow.core.migrations_extraction_batch.ensure_characters_batch_id_column``
  三形态：旧库补列 / 新库 no-op / 无表 no-op（真 SQLite 同步轨）
- ``SQLiteWorldRepository.delete_by_batch`` / ``SQLiteCharacterRepository.delete_by_batch``
  真 DB：只删该批次、跨批次与跨项目隔离、幂等

依据: specs/f14-extraction/spec.md §5.8.5 + §8（#1485）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.character import Character
from inkflow.domain.models.world import WorldSetting
from inkflow.infrastructure.database.models.project import (
    ProjectORM,  # create_all 前注册 ORM
)
from inkflow.infrastructure.database.repositories.character_repo import SQLiteCharacterRepository
from inkflow.infrastructure.database.repositories.world_repo import SQLiteWorldRepository


def _now() -> datetime:
    return datetime.now(UTC)


# ── 迁移三形态（同步 SQLite，镜像 test_world_categories_kind_migration.py）────


def test_ensure_world_settings_batch_id_old_db_adds_column() -> None:
    """旧库（world_settings 存在但无 batch_id 列）→ ALTER 补列。"""
    from sqlalchemy import create_engine

    from inkflow.core.migrations_extraction_batch import ensure_world_settings_batch_id_column

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE world_settings "
                "(id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT)"
            )
        )
        conn.execute(text("INSERT INTO world_settings (project_id, name) VALUES (1, '甲')"))
        conn.commit()

        ensure_world_settings_batch_id_column(conn)
        conn.commit()

        names = {row[1] for row in conn.execute(text("PRAGMA table_info(world_settings)"))}
        assert "batch_id" in names
        # 存量行回填为 NULL（不做回填，历史条目无批次归属）
        assert conn.execute(text("SELECT batch_id FROM world_settings")).scalar() is None
    engine.dispose()


def test_ensure_world_settings_batch_id_new_db_noop() -> None:
    """新库已含该列 → 重复调用幂等 no-op。"""
    from sqlalchemy import create_engine

    from inkflow.core.migrations_extraction_batch import ensure_world_settings_batch_id_column

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE world_settings "
                "(id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, batch_id TEXT)"
            )
        )
        conn.commit()
        ensure_world_settings_batch_id_column(conn)
        conn.commit()
        names = {row[1] for row in conn.execute(text("PRAGMA table_info(world_settings)"))}
        assert "batch_id" in names
    engine.dispose()


def test_ensure_world_settings_batch_id_missing_table_noop() -> None:
    """无表（全新环境 create_all 尚未跑）→ no-op 不抛。"""
    from sqlalchemy import create_engine

    from inkflow.core.migrations_extraction_batch import ensure_world_settings_batch_id_column

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        ensure_world_settings_batch_id_column(conn)
        conn.commit()
    engine.dispose()


def test_ensure_characters_batch_id_old_db_adds_column() -> None:
    """旧库（characters 存在但无 batch_id 列）→ ALTER 补列。"""
    from sqlalchemy import create_engine

    from inkflow.core.migrations_extraction_batch import ensure_characters_batch_id_column

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text("CREATE TABLE characters (id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT)")
        )
        conn.execute(text("INSERT INTO characters (project_id, name) VALUES (1, '林晚')"))
        conn.commit()

        ensure_characters_batch_id_column(conn)
        conn.commit()

        names = {row[1] for row in conn.execute(text("PRAGMA table_info(characters)"))}
        assert "batch_id" in names
    engine.dispose()


def test_ensure_characters_batch_id_new_db_noop() -> None:
    """新库已含该列 → 幂等 no-op。"""
    from sqlalchemy import create_engine

    from inkflow.core.migrations_extraction_batch import ensure_characters_batch_id_column

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE characters "
                "(id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT, batch_id TEXT)"
            )
        )
        conn.commit()
        ensure_characters_batch_id_column(conn)
        conn.commit()
        names = {row[1] for row in conn.execute(text("PRAGMA table_info(characters)"))}
        assert "batch_id" in names
    engine.dispose()


def test_ensure_characters_batch_id_missing_table_noop() -> None:
    """无表 → no-op 不抛。"""
    from sqlalchemy import create_engine

    from inkflow.core.migrations_extraction_batch import ensure_characters_batch_id_column

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        ensure_characters_batch_id_column(conn)
        conn.commit()
    engine.dispose()


# ── delete_by_batch（真 DB 异步轨）──────────────────────────────────────────


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite（启用 FK 级联）。"""
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
    """一个基础项目（FK 依赖）。"""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest.fixture
async def other_project(db_session):
    """第二个项目（跨项目隔离断言用）。"""
    p = ProjectORM(name="另一个项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _pid(project) -> uuid.UUID:
    return uuid.UUID(int=project.id)


class TestWorldDeleteByBatch:
    """world_settings 按批次删除。"""

    async def test_deletes_only_target_batch(self, db_session, project, other_project) -> None:
        repo = SQLiteWorldRepository(db_session)
        pid = _pid(project)
        root = await repo.add(
            WorldSetting(
                id=uuid.uuid4(), project_id=pid, name="根", created_at=_now(), updated_at=_now()
            )
        )
        keep = await repo.add(
            WorldSetting(
                id=uuid.uuid4(),
                project_id=pid,
                name="乙",
                parent_id=root.id,
                category="",
                batch_id="ext-b",
                created_at=_now(),
                updated_at=_now(),
            )
        )
        target = await repo.add(
            WorldSetting(
                id=uuid.uuid4(),
                project_id=pid,
                name="甲",
                parent_id=root.id,
                category="",
                batch_id="ext-a",
                created_at=_now(),
                updated_at=_now(),
            )
        )

        deleted = await repo.delete_by_batch(pid, "ext-a")

        assert deleted == 1
        assert await repo.get(target.id) is None
        assert await repo.get(keep.id) is not None
        assert await repo.get(root.id) is not None, "无 batch_id 的存量条目不受影响"

    async def test_idempotent_and_project_scoped(self, db_session, project, other_project) -> None:
        repo = SQLiteWorldRepository(db_session)
        pid = _pid(project)
        other_pid = _pid(other_project)
        mine = await repo.add(
            WorldSetting(
                id=uuid.uuid4(),
                project_id=pid,
                name="甲",
                batch_id="ext-x",
                created_at=_now(),
                updated_at=_now(),
            )
        )
        theirs = await repo.add(
            WorldSetting(
                id=uuid.uuid4(),
                project_id=other_pid,
                name="乙",
                batch_id="ext-x",
                created_at=_now(),
                updated_at=_now(),
            )
        )

        assert await repo.delete_by_batch(pid, "ext-x") == 1
        assert await repo.delete_by_batch(pid, "ext-x") == 0, "重复回滚必须幂等"
        assert await repo.get(mine.id) is None
        assert await repo.get(theirs.id) is not None, "跨项目同名批次不得误删"


class TestCharacterDeleteByBatch:
    """characters 按批次删除。"""

    async def test_deletes_only_target_batch(self, db_session, project) -> None:
        repo = SQLiteCharacterRepository(db_session)
        pid = _pid(project)
        target = await repo.add(
            Character(
                id=uuid.uuid4(),
                project_id=pid,
                name="林晚",
                batch_id="ext-c",
                created_at=_now(),
                updated_at=_now(),
            )
        )
        keep = await repo.add(
            Character(
                id=uuid.uuid4(),
                project_id=pid,
                name="沈砚",
                batch_id="ext-d",
                created_at=_now(),
                updated_at=_now(),
            )
        )

        assert await repo.delete_by_batch(pid, "ext-c") == 1
        assert await repo.get(target.id) is None
        assert await repo.get(keep.id) is not None

    async def test_no_match_returns_zero(self, db_session, project) -> None:
        repo = SQLiteCharacterRepository(db_session)
        assert await repo.delete_by_batch(_pid(project), "ext-none") == 0
