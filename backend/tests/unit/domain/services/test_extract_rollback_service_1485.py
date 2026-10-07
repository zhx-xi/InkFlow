"""#1485 服务层「按批次回滚」真对象契约（function-coverage 硬零点守护）。

`WorldService.rollback_batch` / `CharacterService.rollback_batch` 是
`repo.delete_by_batch` 的薄透传。**必须用真 SQLite 仓储 + 真服务调用**——桩对象里的
调用不计入函数覆盖，CI `coverage-function` 会把「新方法零调用」判 FAIL。

依据: specs/f14-extraction/spec.md §5.8.5（#1485）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.character import Character
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.services.character_service import CharacterService
from inkflow.domain.services.world_service import WorldService
from inkflow.infrastructure.database.models.project import (
    ProjectORM,  # create_all 前注册 ORM
)
from inkflow.infrastructure.database.repositories.character_repo import SQLiteCharacterRepository
from inkflow.infrastructure.database.repositories.world_repo import SQLiteWorldRepository


def _now() -> datetime:
    """当前 UTC 时间。"""
    return datetime.now(UTC)


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite（启用 FK 级联）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _pragma(dbapi_connection, connection_record):
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
    p = ProjectORM(name="回滚验证项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


class TestWorldServiceRollbackBatch:
    """世界观服务层整批回滚（真仓储）。"""

    async def test_delegates_to_repo_and_is_idempotent(self, db_session, project) -> None:
        """rollback_batch 委托仓储按批次删除：删本批、留下他批、重复调用幂等。"""
        repo = SQLiteWorldRepository(db_session)
        svc = WorldService(repository=repo)
        pid = uuid.UUID(int=project.id)
        root = await repo.add(
            WorldSetting(
                id=uuid.uuid4(), project_id=pid, name="根", created_at=_now(), updated_at=_now()
            )
        )
        await repo.add(
            WorldSetting(
                id=uuid.uuid4(),
                project_id=pid,
                name="甲",
                parent_id=root.id,
                batch_id="ext-w1",
                created_at=_now(),
                updated_at=_now(),
            )
        )
        keep = await repo.add(
            WorldSetting(
                id=uuid.uuid4(),
                project_id=pid,
                name="乙",
                parent_id=root.id,
                batch_id="ext-w2",
                created_at=_now(),
                updated_at=_now(),
            )
        )

        assert await svc.rollback_batch(pid, "ext-w1") == 1
        assert await svc.rollback_batch(pid, "ext-w1") == 0, "重复回滚必须幂等"
        assert await repo.get(keep.id) is not None, "他批条目不得受影响"


class TestCharacterServiceRollbackBatch:
    """角色服务层整批回滚（真仓储）。"""

    async def test_delegates_to_repo_and_is_idempotent(self, db_session, project) -> None:
        """rollback_batch 委托仓储按批次删除角色：删本批、重复调用幂等。"""
        repo = SQLiteCharacterRepository(db_session)
        svc = CharacterService(repository=repo)
        pid = uuid.UUID(int=project.id)
        await repo.add(
            Character(
                id=uuid.uuid4(),
                project_id=pid,
                name="林晚",
                batch_id="ext-c1",
                created_at=_now(),
                updated_at=_now(),
            )
        )
        keep = await repo.add(
            Character(
                id=uuid.uuid4(),
                project_id=pid,
                name="沈砚",
                batch_id="ext-c2",
                created_at=_now(),
                updated_at=_now(),
            )
        )

        assert await svc.rollback_batch(pid, "ext-c1") == 1
        assert await svc.rollback_batch(pid, "ext-c1") == 0, "重复回滚必须幂等"
        assert await repo.get(keep.id) is not None, "他批角色不得受影响"
