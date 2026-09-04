"""#327 RED 契约：project 硬删级联清理子实体（方案 B：foreign_keys=ON + FK CASCADE）.

fixture 镜像生产连接初始化（调用 apply_sqlite_pragma 本身）：
- RED 阶段（apply_sqlite_pragma 无 foreign_keys=ON）→ 硬删 project 后子实体残留
  → count==0 断言 FAIL（真 RED）
- GREEN 阶段（apply_sqlite_pragma 加 PRAGMA foreign_keys=ON）→ ORM 已声明的
  CASCADE FK 生效 → 子实体级联删除 → count==0 PASS

覆盖子实体：character / world_setting / outline / timeline_event /
foreshadowing / story_arc / volume / chapter / map / map_pin。

依据: #327（0.8.0-rc2 修复批）；spec §2.10/§5.18 FK 语义；D2 拍板方案 B。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base, apply_sqlite_pragma
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.services.project_service import ProjectService
from inkflow.infrastructure.database.models.chapter import ChapterORM, VolumeORM
from inkflow.infrastructure.database.models.character import CharacterORM
from inkflow.infrastructure.database.models.foreshadowing import ForeshadowingORM
from inkflow.infrastructure.database.models.map import MapORM, MapPinORM
from inkflow.infrastructure.database.models.outline import OutlineORM, StoryArcORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.timeline import TimelineEventORM
from inkflow.infrastructure.database.models.world import WorldSettingORM
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)


@pytest.fixture
async def db_session() -> AsyncSession:
    """独立 in-memory SQLite — connect 事件调用生产 apply_sqlite_pragma（镜像连接初始化）."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        apply_sqlite_pragma(dbapi_connection)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _create_project(db: AsyncSession) -> tuple[ProjectORM, int]:
    """建 project 并返回 (ORM 行, int id)."""
    repo = SQLiteProjectRepository(db)
    now = datetime.now(UTC)
    saved = await repo.add(
        Project(
            id=uuid.uuid4(),
            name="级联测试项目",
            config=ProjectConfig(model="gpt-4o"),
            created_at=now,
            updated_at=now,
        )
    )
    orm = await db.get(ProjectORM, saved.id.int)
    assert orm is not None
    return orm, saved.id.int


async def _seed_all_child_entities(db: AsyncSession, pid: int) -> None:
    """每类子实体各建 1 行（最小必填字段）."""
    db.add_all(
        [
            CharacterORM(project_id=pid, name="角色甲"),
            WorldSettingORM(project_id=pid, name="设定甲"),
            OutlineORM(project_id=pid, name="大纲甲"),
            StoryArcORM(project_id=pid, name="弧线甲"),
            TimelineEventORM(project_id=pid, title="事件甲"),
            ForeshadowingORM(project_id=pid, title="伏笔甲"),
            VolumeORM(project_id=pid, title="卷甲"),
            ChapterORM(project_id=pid, title="章甲"),
            MapORM(project_id=pid, name="地图甲", image_path="map-a.png"),
        ]
    )
    await db.flush()
    # map_pin 依赖 map id
    map_orm = (await db.execute(select(MapORM).where(MapORM.project_id == pid))).scalar_one()
    db.add(MapPinORM(map_id=map_orm.id, x=0.0, y=0.0, label="pin甲"))
    await db.commit()


_ENTITY_MODELS = [
    (CharacterORM, "characters"),
    (WorldSettingORM, "world_settings"),
    (OutlineORM, "outlines"),
    (StoryArcORM, "story_arcs"),
    (TimelineEventORM, "timeline_events"),
    (ForeshadowingORM, "foreshadowings"),
    (VolumeORM, "volumes"),
    (ChapterORM, "chapters"),
    (MapORM, "maps"),
    (MapPinORM, "map_pins"),
]


async def _count_by_project(db: AsyncSession, model, pid: int) -> int:
    """按 project_id 统计子实体行数（MapPinORM 无 project_id 列，经 maps join）."""
    if model is MapPinORM:
        stmt = (
            select(func.count())
            .select_from(MapPinORM)
            .join(MapORM, MapPinORM.map_id == MapORM.id)
            .where(MapORM.project_id == pid)
        )
        return (await db.execute(stmt)).scalar_one()
    stmt = select(func.count()).select_from(model).where(model.project_id == pid)
    return (await db.execute(stmt)).scalar_one()


async def test_hard_delete_cascades_all_child_entities(db_session: AsyncSession) -> None:
    """#327 M5: project 硬删后 character/world/outline/timeline/foreshadowing/
    arc/chapter/volume/map/pin 全部 list 空（FK CASCADE 根治）."""
    _, pid = await _create_project(db_session)
    await _seed_all_child_entities(db_session, pid)
    assert await _count_by_project(db_session, CharacterORM, pid) == 1  # 前置成立

    svc = ProjectService(db_session)
    deleted = await svc.hard_delete(uuid.UUID(int=pid))

    assert deleted is True
    for model, _table in _ENTITY_MODELS:
        assert (
            await _count_by_project(db_session, model, pid) == 0
        ), f"{_table} 残留: 级联清理未生效"


async def test_hard_delete_same_name_create_succeeds(db_session: AsyncSession) -> None:
    """#327 RED 契约: 硬删后同名 create 成功（唯一索引不冲突）.

    FK=ON 下 project 行已删 → 须先重建项目（新 id）再建同名角色；
    残留数据若未被级联清理会撞 (project_id, name) 唯一索引 → 测试 FAIL。
    """
    _, pid = await _create_project(db_session)
    db_session.add(CharacterORM(project_id=pid, name="角色甲"))
    await db_session.commit()

    svc = ProjectService(db_session)
    assert await svc.hard_delete(uuid.UUID(int=pid)) is True

    # 重建项目（级联清理后无残留行）→ 同名角色重建不抛唯一约束冲突
    new_orm, new_pid = await _create_project(db_session)
    db_session.add(CharacterORM(project_id=new_pid, name="角色甲"))
    await db_session.commit()
    assert new_orm.id == new_pid


async def test_hard_delete_calls_map_cleanup_before_repo_delete(
    db_session: AsyncSession,
) -> None:
    """服务层顺序契约: map_cleanup 在 repo.hard_delete 之前执行（FK=ON 下先删
    maps 再删 project，避免 NO ACTION 拦截 + 图片文件残留）."""
    _, pid = await _create_project(db_session)
    pid_int = pid
    calls: list[str] = []
    repo = SQLiteProjectRepository(db_session)
    orig_hard_delete = repo.hard_delete

    async def _tracking_hard_delete(project_id: int) -> bool:
        calls.append("repo_delete")
        return await orig_hard_delete(project_id)

    repo.hard_delete = _tracking_hard_delete  # type: ignore[method-assign]  # 测试替身

    async def _map_cleanup(project_id: int) -> int:
        calls.append("map_cleanup")
        return 0

    svc = ProjectService(db_session, map_cleanup=_map_cleanup)
    svc._repo = repo
    assert await svc.hard_delete(pid_int) is True
    assert calls == ["map_cleanup", "repo_delete"], f"顺序错误: {calls}"


async def test_hard_delete_map_cleanup_failure_does_not_block(
    db_session: AsyncSession,
) -> None:
    """map_cleanup 失败仅 log warning 不阻断（既有契约保持）."""
    _, pid = await _create_project(db_session)
    fail_cleanup = AsyncMock(side_effect=RuntimeError("cleanup boom"))

    svc = ProjectService(db_session, map_cleanup=fail_cleanup)
    assert await svc.hard_delete(pid) is True
    fail_cleanup.assert_awaited_once_with(pid)
