"""SQLiteAuditRepository 集成测试 — in-memory SQLite（F15 软删集合补充查询，spec §8.2/§9）.

覆盖 AuditRepositoryProtocol.list_deleted 全部场景（spec §9 仓储测试）:
- 三类软删实体命中（角色/分组/事件，is_deleted=1）→ (软删角色 ids, 软删分组 ids,
  软删事件 ids) 三元组
- 活动数据（is_deleted=0）排除
- project_id 过滤（跨项目软删不可见）
- 空项目 → 空三元组
- 无软删行 → 三个空列表
- 软删后 restore（is_deleted 置回 0）的行不再出现
- 只读断言（查询不修改数据）

依据: specs/f15-audit-service/spec.md §5.1 注/§8.2/§9。

注: fixture 显式开启 PRAGMA foreign_keys=ON（SQLite 默认关闭），FK 语义生效
（同 F12/F13/F14 测试惯例）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.infrastructure.database.models.character import CharacterGroupORM, CharacterORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.timeline import TimelineEventORM
from inkflow.infrastructure.database.repositories.audit_repo import SQLiteAuditRepository


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（启用 FK 级联）。"""
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
    """一个基础项目（软删实体行的 FK 依赖）。"""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest.fixture
async def other_project(db_session):
    """另一个项目（project_id 过滤测试用）。"""
    p = ProjectORM(name="另一项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def _add(db_session, obj):
    """插入一行并刷新（拿到自增主键）。"""
    db_session.add(obj)
    await db_session.commit()
    await db_session.refresh(obj)
    return obj


def _repo(db_session) -> SQLiteAuditRepository:
    """构造被测仓储（AuditRepositoryProtocol 实现）。"""
    return SQLiteAuditRepository(db_session)


async def test_list_deleted_returns_soft_deleted_ids_of_all_three_types(db_session, project):
    """三类软删实体（is_deleted=1）分别落入三元组的对应列表。"""
    deleted_char = await _add(
        db_session, CharacterORM(project_id=project.id, name="软删角色", is_deleted=True)
    )
    deleted_group = await _add(
        db_session, CharacterGroupORM(project_id=project.id, name="软删分组", is_deleted=True)
    )
    deleted_event = await _add(
        db_session, TimelineEventORM(project_id=project.id, title="软删事件", is_deleted=True)
    )

    deleted_chars, deleted_groups, deleted_events = await _repo(db_session).list_deleted(project.id)

    assert deleted_chars == [deleted_char.id]
    assert deleted_groups == [deleted_group.id]
    assert deleted_events == [deleted_event.id]


async def test_active_rows_excluded(db_session, project):
    """活动数据（is_deleted=0）不返回。"""
    await _add(db_session, CharacterORM(project_id=project.id, name="活动角色"))
    await _add(db_session, CharacterGroupORM(project_id=project.id, name="活动分组"))
    await _add(db_session, TimelineEventORM(project_id=project.id, title="活动事件"))

    assert await _repo(db_session).list_deleted(project.id) == ([], [], [])


async def test_project_id_filtering(db_session, project, other_project):
    """跨项目软删不可见 — 只返回本项目三类软删集合。"""
    await _add(
        db_session, CharacterORM(project_id=project.id, name="本项目的软删角色", is_deleted=True)
    )
    await _add(
        db_session,
        CharacterORM(project_id=other_project.id, name="他项目的软删角色", is_deleted=True),
    )
    await _add(
        db_session,
        CharacterGroupORM(project_id=other_project.id, name="他项目的软删分组", is_deleted=True),
    )
    await _add(
        db_session,
        TimelineEventORM(project_id=other_project.id, title="他项目的软删事件", is_deleted=True),
    )

    deleted_chars, deleted_groups, deleted_events = await _repo(db_session).list_deleted(project.id)

    assert len(deleted_chars) == 1  # 仅本项目软删角色
    assert deleted_groups == []
    assert deleted_events == []
    # 反向视角: 他项目视角看到的是他项目自己的软删行
    other_chars, other_groups, other_events = await _repo(db_session).list_deleted(other_project.id)
    assert len(other_chars) == 1
    assert len(other_groups) == 1
    assert len(other_events) == 1


async def test_empty_project_returns_empty_triplet(db_session, project):
    """空项目（无任何行）→ 空三元组。"""
    assert await _repo(db_session).list_deleted(project.id) == ([], [], [])


async def test_no_soft_deleted_rows_returns_empty_lists(db_session, project):
    """项目仅有活动数据、无软删行 → 三个空列表。"""
    await _add(db_session, CharacterORM(project_id=project.id, name="活动角色"))
    await _add(db_session, CharacterGroupORM(project_id=project.id, name="活动分组"))
    await _add(db_session, TimelineEventORM(project_id=project.id, title="活动事件"))

    deleted_chars, deleted_groups, deleted_events = await _repo(db_session).list_deleted(project.id)

    assert deleted_chars == []
    assert deleted_groups == []
    assert deleted_events == []


async def test_restored_rows_no_longer_returned(db_session, project):
    """软删后 restore（is_deleted 置回 0）的行不再出现在软删集合。"""
    deleted_char = await _add(
        db_session, CharacterORM(project_id=project.id, name="已恢复角色", is_deleted=True)
    )
    repo = _repo(db_session)

    deleted_chars, _, _ = await repo.list_deleted(project.id)
    assert deleted_chars == [deleted_char.id]

    deleted_char.is_deleted = False
    await db_session.commit()

    deleted_chars, _, _ = await repo.list_deleted(project.id)
    assert deleted_chars == []


async def test_list_deleted_is_read_only(db_session, project):
    """只读断言 — 查询不修改任何数据（行数不变、软删标记不变）。"""
    await _add(db_session, CharacterORM(project_id=project.id, name="只读角色", is_deleted=True))

    before = (await db_session.execute(select(func.count()).select_from(CharacterORM))).scalar_one()
    await _repo(db_session).list_deleted(project.id)
    after = (await db_session.execute(select(func.count()).select_from(CharacterORM))).scalar_one()

    assert before == after == 1
    row = (await db_session.execute(select(CharacterORM))).scalar_one()
    assert row.is_deleted is True
