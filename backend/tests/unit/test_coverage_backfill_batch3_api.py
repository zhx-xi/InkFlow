"""Batch 3 coverage backfill: API assembly helpers and draft factories."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.api._chat_auth import get_conversation_service
from inkflow.api.deps_draft import make_outline_bindder, make_volume_ensurer
from inkflow.core.database import Base

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


async def _seed_project(db, project_id: int = 1, name: str = "project") -> None:
    from inkflow.infrastructure.database.models.project import ProjectORM

    db.add(ProjectORM(id=project_id, name=name))
    await db.commit()


async def test_conversation_service_get_hit_and_miss(db_session) -> None:
    """Public conversation auth service returns domain entities or None."""
    from inkflow.infrastructure.database.models.conversation import ConversationORM

    await _seed_project(db_session)
    conversation = ConversationORM(
        project_id=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        delete_permission="ask_once",
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)

    service = get_conversation_service(db_session)
    found = await service.get(uuid.UUID(int=conversation.id))
    missing = await service.get(uuid.UUID(int=999_999))

    assert found is not None
    assert found.id == uuid.UUID(int=conversation.id)
    assert found.delete_permission == "ask_once"
    assert found.created_at.tzinfo is not None
    assert missing is None


async def test_outline_bindder_binds_existing_outline(db_session) -> None:
    """Public bindder writes the chapter row id for an existing outline."""
    from inkflow.infrastructure.database.models.chapter import ChapterORM
    from inkflow.infrastructure.database.models.outline import OutlineORM

    await _seed_project(db_session)
    chapter = ChapterORM(project_id=1, title="Chapter")
    outline = OutlineORM(project_id=1, name="Outline", level="chapter")
    db_session.add_all([chapter, outline])
    await db_session.commit()
    await db_session.refresh(chapter)
    await db_session.refresh(outline)

    bindder = make_outline_bindder(db_session)
    await bindder(str(uuid.UUID(int=outline.id)), str(uuid.UUID(int=chapter.id)))
    await db_session.refresh(outline)

    assert outline.chapter_id == chapter.id


async def test_outline_bindder_overflow_is_noop(db_session) -> None:
    """Public bindder ignores UUID values outside SQLite INTEGER range."""
    bindder = make_outline_bindder(db_session)

    overflow = await bindder(str(uuid.UUID(int=2**63)), str(uuid.UUID(int=1)))
    missing = await bindder(str(uuid.UUID(int=999_999)), str(uuid.UUID(int=1)))

    assert overflow is None
    assert missing is None


async def test_volume_ensurer_creates_reuses_and_rejects_invalid_shapes(db_session) -> None:
    """Public volume ensurer is idempotent and returns None for invalid inputs."""
    from inkflow.infrastructure.database.models.chapter import VolumeORM
    from inkflow.infrastructure.database.models.outline import OutlineORM

    await _seed_project(db_session)
    volume_outline = OutlineORM(project_id=1, name="Volume One", level="volume")
    db_session.add(volume_outline)
    await db_session.commit()
    await db_session.refresh(volume_outline)
    chapter_outline = OutlineORM(
        project_id=1,
        name="Chapter One",
        level="chapter",
        parent_id=volume_outline.id,
    )
    blank_parent = OutlineORM(project_id=1, name="   ", level="volume")
    db_session.add_all([chapter_outline, blank_parent])
    await db_session.commit()
    await db_session.refresh(chapter_outline)
    await db_session.refresh(blank_parent)
    blank_child = OutlineORM(
        project_id=1,
        name="Chapter Two",
        level="chapter",
        parent_id=blank_parent.id,
    )
    db_session.add(blank_child)
    await db_session.commit()
    await db_session.refresh(blank_child)

    ensurer = make_volume_ensurer(db_session)
    created = await ensurer(uuid.UUID(int=1), uuid.UUID(int=chapter_outline.id))
    reused = await ensurer(uuid.UUID(int=1), uuid.UUID(int=chapter_outline.id))
    missing_outline = await ensurer(uuid.UUID(int=1), uuid.UUID(int=999_999))
    cross_project = await ensurer(uuid.UUID(int=2), uuid.UUID(int=chapter_outline.id))
    blank_title = await ensurer(uuid.UUID(int=1), uuid.UUID(int=blank_child.id))
    malformed = await ensurer(uuid.UUID(int=1), "not-a-uuid")  # type: ignore[arg-type]  # public guard

    assert created is not None
    assert reused == created
    assert missing_outline is None
    assert cross_project is None
    assert blank_title is None
    assert malformed is None
    stored = await db_session.get(VolumeORM, created.int)
    assert stored is not None
    assert stored.title == "Volume One"
