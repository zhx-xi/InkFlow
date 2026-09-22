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

import importlib
import pkgutil
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import String, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import inkflow.infrastructure.database.models as models_pkg
from inkflow.core.database import Base, apply_sqlite_pragma
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.services.project_service import ProjectService
from inkflow.infrastructure.database.models.agent import AgentExecutionORM, AgentStageResultORM
from inkflow.infrastructure.database.models.agent_run import AgentRunORM, DraftORM
from inkflow.infrastructure.database.models.chapter import ChapterORM, VolumeORM
from inkflow.infrastructure.database.models.character import CharacterORM
from inkflow.infrastructure.database.models.foreshadowing import ForeshadowingORM
from inkflow.infrastructure.database.models.map import MapORM, MapPinORM
from inkflow.infrastructure.database.models.outline import OutlineORM, StoryArcORM
from inkflow.infrastructure.database.models.planner_session import PlannerSessionORM
from inkflow.infrastructure.database.models.preference import MemoryEventORM, ProjectPreferenceORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.semantic_summary import SemanticSummaryORM
from inkflow.infrastructure.database.models.timeline import TimelineEventORM
from inkflow.infrastructure.database.models.world import WorldSettingORM
from inkflow.infrastructure.database.models.writing_plan import WritingPlanORM
from inkflow.infrastructure.database.repositories.project_repo import (
    STRING_PID_CHILD_TABLES,
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
        assert await _count_by_project(db_session, model, pid) == 0, (
            f"{_table} 残留: 级联清理未生效"
        )


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
    fail_cleanup.assert_awaited_once_with(uuid.UUID(int=pid))


# ===== #1371：无 FK 子表族（String(36) project_id）显式清理 =====
#
# projects.id 是 int；下表 project_id 是 String(36) 存 str(uuid) → 列类型不匹配，无法加 FK
# → #327 的 DB 级 CASCADE 覆盖不到，项目硬删后整族残留（实测 8 张表全部残留）。
# agent_stage_results 无 project_id 列，经 execution_id（FK 无 ondelete → RESTRICT）挂在
# agent_executions 下：不按 execution_id 先清，则删 agent_executions 被 FK 拦截。

_STRING_PID_CHILD_MODELS = [
    (AgentExecutionORM, "agent_executions"),
    (AgentRunORM, "agent_runs"),
    (DraftORM, "drafts"),
    (MemoryEventORM, "memory_events"),
    (PlannerSessionORM, "planner_sessions"),
    (ProjectPreferenceORM, "project_preferences"),
    (SemanticSummaryORM, "semantic_summaries"),
    (WritingPlanORM, "writing_plans"),
]


async def _seed_string_pid_children(db: AsyncSession, pid_str: str) -> str:
    """每张无 FK 子表各建 1 行（project_id 存 str(uuid)），返回 execution id."""
    execution = AgentExecutionORM(pipeline="builtin:write_chapter", project_id=pid_str)
    db.add_all(
        [
            execution,
            AgentRunORM(project_id=pid_str),
            DraftORM(project_id=pid_str, content="草稿甲"),
            MemoryEventORM(project_id=pid_str, event_type="edit"),
            PlannerSessionORM(project_id=pid_str, one_liner="一句话甲"),
            ProjectPreferenceORM(
                project_id=pid_str, category="addressing", pattern="她", value="角色甲"
            ),
            SemanticSummaryORM(
                scope="project",
                project_id=pid_str,
                content="总结甲",
                anchor_hash="hash-a",
                model="gpt-4o",
            ),
            WritingPlanORM(project_id=pid_str, title="计划甲"),
        ]
    )
    await db.flush()
    db.add(AgentStageResultORM(execution_id=execution.id, stage_id="outline", status="completed"))
    await db.commit()
    return execution.id


async def _count_string_pid(db: AsyncSession, model, pid_str: str) -> int:
    """按 project_id（字符串）统计无 FK 子表行数."""
    stmt = select(func.count()).select_from(model).where(model.project_id == pid_str)
    return (await db.execute(stmt)).scalar_one()


async def _count_stage_results_for(db: AsyncSession, pid_str: str) -> int:
    """统计归属该项目的 agent_stage_results（经 executions 子查询）."""
    stmt = (
        select(func.count())
        .select_from(AgentStageResultORM)
        .where(
            AgentStageResultORM.execution_id.in_(
                select(AgentExecutionORM.id).where(AgentExecutionORM.project_id == pid_str)
            )
        )
    )
    return (await db.execute(stmt)).scalar_one()


async def test_hard_delete_clears_string_pid_child_family_1371(
    db_session: AsyncSession,
) -> None:
    """#1371 主契约：硬删项目后 8 张无 FK 子表 + agent_stage_results 全清.

    RED（无显式清理）→ 行数仍为 1 → FAIL；GREEN（按 project_id 显式清理）→ 0 → PASS。
    """
    _, pid = await _create_project(db_session)
    pid_str = str(uuid.UUID(int=pid))
    await _seed_string_pid_children(db_session, pid_str)
    for model, table in _STRING_PID_CHILD_MODELS:
        assert await _count_string_pid(db_session, model, pid_str) == 1, f"{table} 前置不成立"
    assert await _count_stage_results_for(db_session, pid_str) == 1  # 前置成立

    assert await ProjectService(db_session).hard_delete(uuid.UUID(int=pid)) is True

    for model, table in _STRING_PID_CHILD_MODELS:
        assert await _count_string_pid(db_session, model, pid_str) == 0, f"{table} 残留孤儿行"
    assert await _count_stage_results_for(db_session, pid_str) == 0, "agent_stage_results 残留"


async def test_hard_delete_keeps_other_project_string_pid_children_1371(
    db_session: AsyncSession,
) -> None:
    """反向断言：只清目标项目 —— 另一项目的同族行必须全部存活（不得误删）."""
    _, pid = await _create_project(db_session)
    _, other_pid = await _create_project(db_session)
    pid_str, other_str = str(uuid.UUID(int=pid)), str(uuid.UUID(int=other_pid))
    await _seed_string_pid_children(db_session, pid_str)
    await _seed_string_pid_children(db_session, other_str)

    assert await ProjectService(db_session).hard_delete(uuid.UUID(int=pid)) is True

    for model, table in _STRING_PID_CHILD_MODELS:
        assert await _count_string_pid(db_session, model, other_str) == 1, f"{table} 误删他项目行"
    assert await _count_stage_results_for(db_session, other_str) == 1, "他项目 stage_result 被误删"


async def test_hard_delete_keeps_user_scope_summary_1371(db_session: AsyncSession) -> None:
    """用户级语义总结（scope=user，project_id=NULL）不属于任何项目 → 不得被清理."""
    _, pid = await _create_project(db_session)
    pid_str = str(uuid.UUID(int=pid))
    await _seed_string_pid_children(db_session, pid_str)
    db_session.add(
        SemanticSummaryORM(
            scope="user",
            project_id=None,
            content="用户级总结",
            anchor_hash="hash-user",
            model="gpt-4o",
        )
    )
    await db_session.commit()

    assert await ProjectService(db_session).hard_delete(uuid.UUID(int=pid)) is True

    stmt = (
        select(func.count())
        .select_from(SemanticSummaryORM)
        .where(SemanticSummaryORM.project_id.is_(None))
    )
    assert (await db_session.execute(stmt)).scalar_one() == 1, "用户级总结被误删"


async def test_soft_delete_and_restore_keep_string_pid_children_1371(
    db_session: AsyncSession,
) -> None:
    """既有语义不破：软删/恢复不动无 FK 子表行（仅硬删清理）."""
    _, pid = await _create_project(db_session)
    pid_str = str(uuid.UUID(int=pid))
    await _seed_string_pid_children(db_session, pid_str)
    svc = ProjectService(db_session)

    assert await svc.soft_delete(uuid.UUID(int=pid)) is True
    for model, table in _STRING_PID_CHILD_MODELS:
        assert await _count_string_pid(db_session, model, pid_str) == 1, f"软删动了 {table}"

    assert await svc.restore(uuid.UUID(int=pid)) is not None
    for model, table in _STRING_PID_CHILD_MODELS:
        assert await _count_string_pid(db_session, model, pid_str) == 1, f"恢复动了 {table}"


def test_string_pid_child_registry_matches_metadata_1371() -> None:
    """漂移守护：metadata 中所有「String 类型 project_id 且无 FK」的表必须登记在
    STRING_PID_CHILD_TABLES —— 新增此类表却未纳入清理时本断言立即 FAIL."""
    for mod in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"{models_pkg.__name__}.{mod.name}")

    discovered = {
        tname
        for tname, tb in Base.metadata.tables.items()
        if "project_id" in tb.columns
        and not tb.columns["project_id"].foreign_keys
        and isinstance(tb.columns["project_id"].type, String)
    }
    registered = set(STRING_PID_CHILD_TABLES)
    assert discovered == registered, (
        f"未登记（漏清理）: {sorted(discovered - registered)}；"
        f"已登记但 metadata 不存在: {sorted(registered - discovered)}"
    )
