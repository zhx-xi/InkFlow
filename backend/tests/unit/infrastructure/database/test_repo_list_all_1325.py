"""#1325：给三个 repo 的 `list_all` 补真 SQLite 覆盖。

为什么必须有：`coverage-function` 门禁（CI `Function-coverage gate`）报
`new uncalled functions: [character_repo.list_all, foreshadowing_repo.list_all,
outline_repo.list_all]` —— 这三个方法此前**只被 mock 的 service 层"调用"**，
真实现从未执行 ⇒ 零函数覆盖。门禁禁止豁免，正解 = 真库用例。

本文件独立自包含（不 import 既有测试文件的 fixture —— pytest fixture 跨文件不可见），
fixture 形态照抄 `test_outline_repo.py:37-63`（独立 in-memory SQLite + FK ON）。

断言语义（三处一致）：
- 返回项目内**全部**行（不分页——与 `list()` 默认 limit=50 形成对照，这是 #1325 的修复面）
- 排序：character/outline 按 name ASC；foreshadowing 按 title ASC
- 空项目 → 空列表；`require_uuid_pk` 守卫：超 int64 范围的 UUID → `[]`（不抛 OverflowError）
- 跨项目隔离：别的项目的行不得出现
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.infrastructure.database.models.character import CharacterORM
from inkflow.infrastructure.database.models.foreshadowing import ForeshadowingORM
from inkflow.infrastructure.database.models.outline import OutlineORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.character_repo import SQLiteCharacterRepository
from inkflow.infrastructure.database.repositories.foreshadowing_repo import (
    SQLiteForeshadowingRepository,
)
from inkflow.infrastructure.database.repositories.outline_repo import SQLiteOutlineRepository


def _now() -> datetime:
    """Current UTC time (timezone-aware)."""
    return datetime.now(UTC)


@pytest.fixture
async def db_session():
    """Independent in-memory SQLite per test (FK cascade enabled)."""
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


async def _project(db_session, name: str) -> ProjectORM:
    """Insert a project row and return it (refreshed, so `.id` is populated)."""
    p = ProjectORM(name=name)
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


# ── 25 行：项目内 < NAME_ASC_ROWS > 条实体（刻意超过 list() 默认 limit=50 的一半，
#    用于证明「全量方法不截断」；不多造 50+ 行以免测试变慢）────────────────────


@pytest.mark.integration
class TestCharacterListAll1325:
    """#1325：SQLiteCharacterRepository.list_all —— 全量 + name ASC + 项目隔离."""

    async def test_returns_all_rows_sorted_by_name_asc(self, db_session):
        """Three characters inserted out of order -> returned name ASC (all of them)."""
        proj = await _project(db_session, "P-all")
        for nm in ("C角色", "A角色", "B角色"):
            db_session.add(
                CharacterORM(project_id=proj.id, name=nm, created_at=_now(), updated_at=_now())
            )
        await db_session.commit()

        repo = SQLiteCharacterRepository(db_session)
        rows = await repo.list_all(uuid.UUID(int=proj.id))

        assert [c.name for c in rows] == ["A角色", "B角色", "C角色"]

    async def test_full_list_is_not_truncated_by_paged_default(self, db_session):
        """60 rows -> list_all returns 60 while paged list() caps at its default 50.

        This is exactly the #1325 defect: the graph aggregation used ``list()``
        and silently lost everything past row 50.
        """
        proj = await _project(db_session, "P-many")
        for i in range(60):
            db_session.add(
                CharacterORM(
                    project_id=proj.id,
                    name=f"角色{i:03d}",
                    created_at=_now(),
                    updated_at=_now(),
                )
            )
        await db_session.commit()

        repo = SQLiteCharacterRepository(db_session)
        pid = uuid.UUID(int=proj.id)

        full = await repo.list_all(pid)
        paged, total = await repo.list(pid)

        assert len(full) == 60  # 全量不截断
        assert total == 60
        assert len(paged) == 50  # 分页默认 limit=50（旧实现的数据源）

    async def test_empty_project_returns_empty(self, db_session):
        """No characters -> empty list (not None)."""
        proj = await _project(db_session, "P-empty")
        repo = SQLiteCharacterRepository(db_session)

        assert await repo.list_all(uuid.UUID(int=proj.id)) == []

    async def test_other_project_rows_excluded(self, db_session):
        """Rows of another project must not leak in."""
        p1 = await _project(db_session, "P1")
        p2 = await _project(db_session, "P2")
        db_session.add(
            CharacterORM(project_id=p1.id, name="本项目的", created_at=_now(), updated_at=_now())
        )
        db_session.add(
            CharacterORM(project_id=p2.id, name="别人的", created_at=_now(), updated_at=_now())
        )
        await db_session.commit()

        repo = SQLiteCharacterRepository(db_session)
        rows = await repo.list_all(uuid.UUID(int=p1.id))

        assert [c.name for c in rows] == ["本项目的"]

    async def test_out_of_int64_range_uuid_returns_empty(self, db_session):
        """uuid 128-bit int 超出 SQLite INTEGER 64 位 -> [] (guard, no OverflowError)."""
        repo = SQLiteCharacterRepository(db_session)

        assert await repo.list_all(uuid.uuid4()) == []
        assert await repo.list_all(uuid.UUID(int=2**63)) == []


@pytest.mark.integration
class TestOutlineListAll1325:
    """#1325：SQLiteOutlineRepository.list_all —— 全量 + name ASC + 项目隔离."""

    async def test_returns_all_rows_sorted_by_name_asc(self, db_session):
        """Out-of-order inserts -> name ASC."""
        proj = await _project(db_session, "O-all")
        for nm in ("卷三", "卷一", "卷二"):
            db_session.add(
                OutlineORM(project_id=proj.id, name=nm, created_at=_now(), updated_at=_now())
            )
        await db_session.commit()

        repo = SQLiteOutlineRepository(db_session)
        rows = await repo.list_all(uuid.UUID(int=proj.id))

        assert [o.name for o in rows] == ["卷一", "卷三", "卷二"]

    async def test_empty_and_project_isolation(self, db_session):
        """Empty project -> []; other project rows excluded."""
        p1 = await _project(db_session, "O1")
        p2 = await _project(db_session, "O2")
        db_session.add(
            OutlineORM(project_id=p2.id, name="别人的大纲", created_at=_now(), updated_at=_now())
        )
        await db_session.commit()
        repo = SQLiteOutlineRepository(db_session)

        assert await repo.list_all(uuid.UUID(int=p1.id)) == []
        assert len(await repo.list_all(uuid.UUID(int=p2.id))) == 1

    async def test_out_of_int64_range_uuid_returns_empty(self, db_session):
        """Out-of-int64 UUID -> [] (guard)."""
        repo = SQLiteOutlineRepository(db_session)

        assert await repo.list_all(uuid.uuid4()) == []


@pytest.mark.integration
class TestForeshadowingListAll1325:
    """#1325：SQLiteForeshadowingRepository.list_all —— 全量 + title ASC + 项目隔离."""

    async def test_returns_all_rows_sorted_by_title_asc(self, db_session):
        """Out-of-order inserts -> title ASC."""
        proj = await _project(db_session, "F-all")
        for title in ("丙伏笔", "甲伏笔", "乙伏笔"):
            db_session.add(
                ForeshadowingORM(
                    project_id=proj.id, title=title, created_at=_now(), updated_at=_now()
                )
            )
        await db_session.commit()

        repo = SQLiteForeshadowingRepository(db_session)
        rows = await repo.list_all(uuid.UUID(int=proj.id))

        assert [f.title for f in rows] == ["丙伏笔", "乙伏笔", "甲伏笔"]

    async def test_empty_and_project_isolation(self, db_session):
        """Empty project -> []; other project rows excluded."""
        p1 = await _project(db_session, "F1")
        p2 = await _project(db_session, "F2")
        db_session.add(
            ForeshadowingORM(project_id=p2.id, title="别人的", created_at=_now(), updated_at=_now())
        )
        await db_session.commit()
        repo = SQLiteForeshadowingRepository(db_session)

        assert await repo.list_all(uuid.UUID(int=p1.id)) == []
        assert len(await repo.list_all(uuid.UUID(int=p2.id))) == 1

    async def test_out_of_int64_range_uuid_returns_empty(self, db_session):
        """Out-of-int64 UUID -> [] (guard)."""
        repo = SQLiteForeshadowingRepository(db_session)

        assert await repo.list_all(uuid.uuid4()) == []
