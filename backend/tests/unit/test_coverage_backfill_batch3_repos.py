"""Batch 3 coverage backfill: repository public methods on real SQLite."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.chat_message import ChatMessage
from inkflow.infrastructure.database.repositories.chat_message_repo import (
    SQLiteChatMessageRepository,
)
from inkflow.infrastructure.database.repositories.map_repo import SQLiteMapRepository

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db_session():
    import inkflow.infrastructure.database.models  # noqa: F401  # register all ORM models

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_project(db, project_id: int, name: str) -> None:
    from inkflow.infrastructure.database.models.project import ProjectORM

    db.add(ProjectORM(id=project_id, name=name))
    await db.commit()


def _message(
    *,
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    content: str,
    created_at: datetime | None = None,
) -> ChatMessage:
    return ChatMessage(
        id=uuid.uuid4(),
        project_id=project_id,
        conversation_id=conversation_id,
        role="user",
        content=content,
        created_at=created_at or datetime.now(UTC),
    )


async def test_chat_repo_list_by_project_accepts_uuid_and_int(db_session) -> None:
    """Public project listing accepts UUID and integer project identifiers."""
    await _seed_project(db_session, 1, "one")
    await _seed_project(db_session, 2, "two")
    repo = SQLiteChatMessageRepository(db_session)
    await repo.create_conversation(uuid.UUID(int=1))
    await repo.create_conversation(uuid.UUID(int=2))
    expected = await repo.add(
        _message(project_id=uuid.UUID(int=1), conversation_id=uuid.UUID(int=1), content="one")
    )
    await repo.add(
        _message(project_id=uuid.UUID(int=2), conversation_id=uuid.UUID(int=2), content="two")
    )

    uuid_items, uuid_total = await repo.list_by_project(uuid.UUID(int=1))
    int_items, int_total = await repo.list_by_project(1)

    assert uuid_total == int_total == 1
    assert [item.id for item in uuid_items] == [expected.id]
    assert [item.id for item in int_items] == [expected.id]


async def test_chat_repo_delete_restore_missing_paths(db_session) -> None:
    """Public delete/restore methods report false/None for absent rows."""
    repo = SQLiteChatMessageRepository(db_session)

    assert await repo.force_delete_message(999_999) is False
    assert await repo.restore_message(999_999) is None
    assert await repo.force_delete_conversation(uuid.UUID(int=999_999)) is False


async def test_chat_repo_update_delete_permission_hit_and_miss(db_session) -> None:
    """Public delete-permission update returns a dict on hit and None on miss."""
    await _seed_project(db_session, 1, "one")
    repo = SQLiteChatMessageRepository(db_session)
    conversation = await repo.create_conversation(uuid.UUID(int=1))

    updated = await repo.update_delete_permission(
        conversation_id=conversation.id,
        delete_permission="ask_once",
    )
    missing = await repo.update_delete_permission(
        conversation_id=uuid.UUID(int=999_999),
        delete_permission="manual",
    )

    assert updated == {
        "conversation_id": str(conversation.id),
        "delete_permission": "ask_once",
    }
    assert missing is None


async def test_map_repo_clear_ref_pins_and_root_locations(db_session) -> None:
    """Public map cleanup methods clear ref/root links and return row counts."""
    from inkflow.infrastructure.database.models.map import MapORM, MapPinORM
    from inkflow.infrastructure.database.models.project import ProjectORM
    from inkflow.infrastructure.database.models.world import WorldSettingORM

    project = ProjectORM(id=1, name="one")
    root_location = WorldSettingORM(id=1, project_id=1, name="root")
    db_session.add_all([project, root_location])
    await db_session.commit()
    world_map = MapORM(
        id=1,
        project_id=1,
        name="map",
        image_path="maps/x.png",
        root_location_id=1,
    )
    pin = MapPinORM(
        id=1,
        map_id=1,
        location_id=1,
        type="role",
        ref_id=42,
        x=1.0,
        y=2.0,
        label="pin",
    )
    db_session.add_all([world_map, pin])
    await db_session.commit()

    repo = SQLiteMapRepository(db_session)
    assert await repo.clear_ref_pins("role", [42]) == 1
    assert await repo.clear_map_root_locations([1]) == 1

    stored_pin = (
        await db_session.execute(select(MapPinORM).where(MapPinORM.id == 1))
    ).scalar_one()
    stored_map = (
        await db_session.execute(select(MapORM).where(MapORM.id == 1))
    ).scalar_one()
    assert stored_pin.ref_id is None
    assert stored_map.root_location_id is None
