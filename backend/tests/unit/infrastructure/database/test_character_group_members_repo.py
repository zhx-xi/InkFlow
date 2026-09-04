"""角色分组 N:M 关联表仓储测试 — in-memory SQLite（#701 RED 契约）.

覆盖 contract-701 §3 新增的关联表方法（int 入参，与既有一致）:
- add_group_member / remove_group_member：幂等插入 / 移除关联行
- list_members_by_group：按分组查角色（N 端）
- list_groups_by_character：按角色查分组（M 端）
- 分组硬删 → 关联行移除（角色本身保留）
- 角色 hard_delete → 关联行级联移除（分组本身保留）

注: fixture 显式开启 PRAGMA foreign_keys=ON（镜像 test_character_repo.py 的
db_session fixture），FK CASCADE 语义才生效。驱动 SQLiteCharacterRepository。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.character import Character, CharacterGroup
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.character_repo import SQLiteCharacterRepository


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
    """一个基础项目（角色/分组的 FK 依赖）."""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _now() -> datetime:
    """当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _char(project: ProjectORM, name: str, **kw) -> Character:
    """构造待持久化的角色领域对象（group_ids 数组，N:M #701）."""
    return Character(
        id=uuid.uuid4(),
        project_id=uuid.UUID(int=project.id),
        name=name,
        created_at=_now(),
        updated_at=_now(),
        **kw,
    )


def _group(project: ProjectORM, name: str, **kw) -> CharacterGroup:
    """构造待持久化的分组领域对象."""
    return CharacterGroup(
        id=uuid.uuid4(),
        project_id=uuid.UUID(int=project.id),
        name=name,
        created_at=_now(),
        updated_at=_now(),
        **kw,
    )


@pytest.mark.integration
class TestCharacterGroupMembers:
    """角色分组 N:M 关联表 — add/remove/list 双向查询 CRUD."""

    async def test_add_group_member_and_list_members_by_group(self, db_session, project):
        """add_group_member 后，list_members_by_group 返回该分组的全部角色（N 端）."""
        repo = SQLiteCharacterRepository(db_session)
        g = await repo.add_group(_group(project, "主角团"))
        c1 = await repo.add(_char(project, "林尘"))
        c2 = await repo.add(_char(project, "阿澈"))

        await repo.add_group_member(c1.id.int, g.id.int)
        await repo.add_group_member(c2.id.int, g.id.int)

        members = await repo.list_members_by_group(g.id.int)
        assert {m.id for m in members} == {c1.id, c2.id}

    async def test_add_group_member_is_idempotent(self, db_session, project):
        """同一 (character_id, group_id) 重复插入不报错（幂等），成员不重复."""
        repo = SQLiteCharacterRepository(db_session)
        g = await repo.add_group(_group(project, "主角团"))
        c = await repo.add(_char(project, "林尘"))

        await repo.add_group_member(c.id.int, g.id.int)
        await repo.add_group_member(c.id.int, g.id.int)

        members = await repo.list_members_by_group(g.id.int)
        assert [m.id for m in members] == [c.id]

    async def test_remove_group_member(self, db_session, project):
        """remove_group_member 移除单个关联，其余成员保留."""
        repo = SQLiteCharacterRepository(db_session)
        g = await repo.add_group(_group(project, "主角团"))
        c1 = await repo.add(_char(project, "林尘"))
        c2 = await repo.add(_char(project, "阿澈"))
        await repo.add_group_member(c1.id.int, g.id.int)
        await repo.add_group_member(c2.id.int, g.id.int)

        await repo.remove_group_member(c1.id.int, g.id.int)

        members = await repo.list_members_by_group(g.id.int)
        assert [m.id for m in members] == [c2.id]

    async def test_list_groups_by_character(self, db_session, project):
        """list_groups_by_character 返回角色所属的全部分组（M 端，N:M）."""
        repo = SQLiteCharacterRepository(db_session)
        g1 = await repo.add_group(_group(project, "主角团"))
        g2 = await repo.add_group(_group(project, "青云宗"))
        c = await repo.add(_char(project, "林尘"))
        await repo.add_group_member(c.id.int, g1.id.int)
        await repo.add_group_member(c.id.int, g2.id.int)

        groups = await repo.list_groups_by_character(c.id.int)
        assert {gr.id for gr in groups} == {g1.id, g2.id}
        assert all(gr.project_id == uuid.UUID(int=project.id) for gr in groups)

    async def test_list_unknown_ids_return_empty(self, db_session, project):
        """不存在的分组/角色 → 空列表."""
        repo = SQLiteCharacterRepository(db_session)
        assert await repo.list_members_by_group(99999) == []
        assert await repo.list_groups_by_character(99999) == []

    async def test_add_character_with_group_ids_creates_memberships(self, db_session, project):
        """add(character) 带 group_ids → 关联行落库（list_members_by_group 可查）."""
        repo = SQLiteCharacterRepository(db_session)
        g = await repo.add_group(_group(project, "主角团"))
        c = await repo.add(_char(project, "林尘", group_ids=[g.id]))

        assert c.group_ids == [g.id]
        members = await repo.list_members_by_group(g.id.int)
        assert [m.id for m in members] == [c.id]

    async def test_hard_delete_group_removes_memberships(self, db_session, project):
        """分组硬删 → 该分组关联行移除（角色本身保留，角色分组清空）."""
        repo = SQLiteCharacterRepository(db_session)
        g = await repo.add_group(_group(project, "主角团"))
        c = await repo.add(_char(project, "林尘", group_ids=[g.id]))

        assert await repo.hard_delete_group(g.id.int) is True

        assert await repo.list_members_by_group(g.id.int) == []
        assert await repo.list_groups_by_character(c.id.int) == []
        assert await repo.get(c.id.int) is not None  # 角色本身保留

    async def test_hard_delete_character_cascades_memberships(self, db_session, project):
        """角色 hard_delete → 其关联行级联移除（分组本身保留）."""
        repo = SQLiteCharacterRepository(db_session)
        g = await repo.add_group(_group(project, "主角团"))
        c = await repo.add(_char(project, "林尘", group_ids=[g.id]))

        assert await repo.hard_delete(c.id.int) is True

        assert await repo.list_members_by_group(g.id.int) == []
        assert await repo.get_group(g.id.int) is not None  # 分组本身保留
