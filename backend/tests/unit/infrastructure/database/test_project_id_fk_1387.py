"""#1387 RED 契约：`String(36) project_id` 子表归一为 `INTEGER + FK(projects.id) ON DELETE CASCADE`.

依据: ADR-063（决策）· issue #1387（#1371 的「方案 B」跟踪单）· #327（int + FK CASCADE 先例）·
`sqlite-schema-migration` skill（FK-safe table-rebuild / FK pragma 事务陷阱 / AUTOCOMMIT 原子性）。

三层契约：

1. **模型层（反射）**：8 张子表的 `project_id` 必须是 `Integer` +
   `FK(projects.id) ON DELETE CASCADE`；
   `agent_stage_results.execution_id` 必须补 `ON DELETE CASCADE`（否则阻断级联链）；
   反向守护：metadata 中**不得**再存在「`project_id` 为 String 且无 FK」的表。
2. **DB 行为层（有牙）**：插不存在的 `project_id` → DB 拒绝；**绕过仓储层** `DELETE FROM projects`
   → 全部子表由 DB 级联清空（方案 A 的显式清理不参与，只有真 FK 能满足）。
3. **迁移层**：旧库（VARCHAR(36) 形态）经 `run_project_id_fk_migration()` → 列类型归一 + FK 建立 +
   存量值转换 + 孤儿隔离到 `<table>__orphan_1387`（不静默删除）+ NULL 语义保留 + 幂等重跑。
"""

from __future__ import annotations

import importlib
import pkgutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import Integer, String, event, func, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import inkflow.infrastructure.database.models as models_pkg  # Base.metadata 注册
from inkflow.core import database as db_module
from inkflow.core.database import Base, apply_sqlite_pragma
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.models.semantic_summary import SummaryScope
from inkflow.infrastructure.database.models.agent import AgentExecutionORM, AgentStageResultORM
from inkflow.infrastructure.database.models.agent_run import AgentRunORM, DraftORM
from inkflow.infrastructure.database.models.planner_session import PlannerSessionORM
from inkflow.infrastructure.database.models.preference import MemoryEventORM, ProjectPreferenceORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.semantic_summary import SemanticSummaryORM
from inkflow.infrastructure.database.models.writing_plan import WritingPlanORM
from inkflow.infrastructure.database.repositories.project_repo import SQLiteProjectRepository

# (表名, project_id 是否可空) —— ADR-063；semantic_summaries 的 scope=user 行为 NULL
PROJECT_FK_CHILD_TABLES: tuple[tuple[str, bool], ...] = (
    ("agent_executions", False),
    ("agent_runs", False),
    ("drafts", False),
    ("memory_events", False),
    ("planner_sessions", False),
    ("project_preferences", False),
    ("semantic_summaries", True),
    ("writing_plans", False),
)

QUARANTINE_SUFFIX = "__orphan_1387"

CHILD_MODELS = (
    (AgentExecutionORM, "agent_executions"),
    (AgentRunORM, "agent_runs"),
    (DraftORM, "drafts"),
    (MemoryEventORM, "memory_events"),
    (PlannerSessionORM, "planner_sessions"),
    (ProjectPreferenceORM, "project_preferences"),
    (SemanticSummaryORM, "semantic_summaries"),
    (WritingPlanORM, "writing_plans"),
)


# ── 1. 模型层（反射契约） ────────────────────────────────────────────────────


def test_project_id_columns_are_integer_fk_cascade_1387() -> None:
    """8 张子表的 project_id：Integer + FK(projects.id) ON DELETE CASCADE + 保持可空性."""
    for table_name, nullable in PROJECT_FK_CHILD_TABLES:
        table = Base.metadata.tables[table_name]
        col = table.columns["project_id"]
        assert isinstance(col.type, Integer), (
            f"{table_name}.project_id 类型应为 Integer，实际 {col.type!r}"
        )
        fks = list(col.foreign_keys)
        assert len(fks) == 1, f"{table_name}.project_id 应恰有 1 个 FK，实际 {len(fks)}"
        fk = fks[0]
        assert fk.target_fullname == "projects.id", (
            f"{table_name}.project_id FK 目标应为 projects.id，实际 {fk.target_fullname}"
        )
        assert fk.ondelete == "CASCADE", (
            f"{table_name}.project_id FK ondelete 应为 CASCADE，实际 {fk.ondelete!r}"
        )
        assert col.nullable is nullable, (
            f"{table_name}.project_id 可空性应保持 {nullable}，实际 {col.nullable}"
        )


def test_agent_stage_results_execution_fk_is_cascade_1387() -> None:
    """agent_stage_results.execution_id 必须补 ON DELETE CASCADE
    （否则整条级联链被 RESTRICT 阻断）."""
    table = Base.metadata.tables["agent_stage_results"]
    fks = list(table.columns["execution_id"].foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.target_fullname == "agent_executions.id"
    assert fk.ondelete == "CASCADE", (
        f"agent_stage_results.execution_id FK ondelete 应为 CASCADE，实际 {fk.ondelete!r}"
    )


def test_no_string_project_id_without_fk_1387() -> None:
    """反向守护（替代 #1371 的 STRING_PID_CHILD_TABLES 登记表）：
    metadata 中不得再存在「project_id 为 String 且无 FK」的表 —— 新增此类表立即 FAIL."""
    for mod in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"{models_pkg.__name__}.{mod.name}")

    offenders = sorted(
        table_name
        for table_name, table in Base.metadata.tables.items()
        if "project_id" in table.columns
        and not table.columns["project_id"].foreign_keys
        and isinstance(table.columns["project_id"].type, String)
    )
    assert offenders == [], (
        f"以下表的 project_id 仍是 String 且无 FK（应为 INTEGER + FK(projects.id)）: {offenders}"
    )


async def test_agent_status_exposes_uuid_project_id_1387() -> None:
    """ADR-063：ORM project_id 已归一为 int，get_status 必须回吐 uuid **字符串**（API 契约不变）.

    RED：直接回吐 ORM 值 → project_id 变成 int 1（CLI 会打印 1 而非项目 UUID）。
    """
    from types import SimpleNamespace

    from inkflow.domain.services.agent_service import AgentService

    row = SimpleNamespace(
        id="exec-1",
        pipeline="builtin:write_chapter",
        project_id=1,  # ORM 列（INTEGER）的值形态
        status="completed",
        stages=[],
        relations=None,
        trace=None,
        final_output="",
        total_duration_ms=0,
        error="",
        hitl_payload=None,
    )
    store = SimpleNamespace(get_execution=AsyncMock(return_value=row))
    svc = object.__new__(AgentService)
    svc._store = store  # type: ignore[attr-defined]  # 测试装配：只验 get_status 的映射

    result = await svc.get_status("exec-1")

    assert result is not None
    assert result["project_id"] == str(uuid.UUID(int=1)), (
        f"get_status 必须回吐 uuid 字符串，实际 {result['project_id']!r}"
    )


async def test_read_paths_treat_out_of_range_project_id_as_absent_1387(
    db_session: AsyncSession,
) -> None:
    """ADR-060 D9：越界（真 uuid4）project_id 的**读取**语义 = 不存在（空结果），不得抛异常.

    RED：读路径误用 require_int_pk（越界 → ValueError）→ API 由 200+空列表 退化为 500。
    """
    from inkflow.infrastructure.database.repositories.agent_run_repo import (
        SQLiteAgentRunRepository,
    )
    from inkflow.infrastructure.database.repositories.draft_repo import SQLiteDraftRepository
    from inkflow.infrastructure.database.repositories.memory_event_repo import (
        SQLiteMemoryEventRepository,
    )
    from inkflow.infrastructure.database.repositories.preference_repo import (
        SQLitePreferenceRepository,
    )
    from inkflow.infrastructure.database.repositories.semantic_summary_repo import (
        SQLiteSemanticSummaryRepository,
    )

    foreign = uuid.uuid4()  # 128 位真随机 → .int 超出 int64

    assert await SQLiteAgentRunRepository(db_session).list(project_id=foreign) == ([], 0)
    assert await SQLiteDraftRepository(db_session).list(project_id=foreign) == ([], 0)
    assert await SQLiteMemoryEventRepository(db_session).list_by_project(foreign) == ([], 0)
    assert await SQLiteMemoryEventRepository(db_session).count_by_project(foreign) == 0
    assert await SQLitePreferenceRepository(db_session).list_by_project(foreign) == ([], 0)
    assert await SQLitePreferenceRepository(db_session).count_by_project(foreign) == 0
    assert (
        await SQLiteSemanticSummaryRepository(db_session).get(SummaryScope.PROJECT, foreign) is None
    )
    assert await SQLiteSemanticSummaryRepository(db_session).delete_by_project(foreign) == 0


async def test_write_path_rejects_non_local_project_ids_1387(db_session: AsyncSession) -> None:
    """ADR-063/ADR-060 D9 写路径契约：非法文本 / 裸 int / 越界 uuid 一律响亮失败（不写垃圾 FK）."""
    from inkflow.infrastructure.agent import ExecutionStore

    store = ExecutionStore(db_session)
    with pytest.raises(ValueError):
        await store.create_execution(pipeline="builtin:write_chapter", project_id="not-a-uuid")
    with pytest.raises(TypeError):
        await store.create_execution(
            pipeline="builtin:write_chapter",
            project_id=1,  # type: ignore[arg-type]  # 故意传裸 int：断言 ADR-060 D9 契约拒绝
        )
    with pytest.raises(ValueError):
        await store.create_execution(pipeline="builtin:write_chapter", project_id=uuid.uuid4())


async def test_read_path_treats_malformed_project_id_as_absent_1387(
    db_session: AsyncSession,
) -> None:
    """读路径非法 project_id（非 uuid 文本 / 裸 int）→ 空结果，不抛异常（ADR-060 D9）."""
    from inkflow.infrastructure.database.repositories.draft_repo import SQLiteDraftRepository

    repo = SQLiteDraftRepository(db_session)
    assert await repo.list(project_id="not-a-uuid") == ([], 0)
    assert await repo.list(project_id=1) == ([], 0)  # type: ignore[arg-type]  # 裸 int：读口不炸


def test_project_id_fk_migration_is_wired_1387() -> None:
    """接线守护（AST，禁 substring）：lifespan 调 runner，runner 转接 ensure helper.

    ⚠️ `ensure_project_id_fk_children` **不在** `core/database.py` re-export（该文件受 900 行
    护栏约束：896 + 多注册一符号即超限）→ D3 wiring 门禁的 registered 集合不含它，
    故这条接线守护由契约侧承接。
    """
    import ast
    import importlib.util
    import inspect
    from pathlib import Path

    spec = importlib.util.find_spec("inkflow.api.app")
    assert spec is not None and spec.origin is not None
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    lifespan = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
        ),
        None,
    )
    assert lifespan is not None, "lifespan 函数未找到（门禁形态失效）"
    called = {node.id for node in ast.walk(lifespan) if isinstance(node, ast.Name)}
    called |= {node.attr for node in ast.walk(lifespan) if isinstance(node, ast.Attribute)}
    assert "run_project_id_fk_migration" in called, "lifespan 未接线 run_project_id_fk_migration"

    runner_tree = ast.parse(inspect.getsource(db_module.run_project_id_fk_migration))
    forwarded = {
        node.id
        for node in ast.walk(runner_tree)
        if isinstance(node, ast.Name) and node.id.startswith("ensure_")
    }
    assert "ensure_project_id_fk_children" in forwarded, (
        "runner 未转接 ensure_project_id_fk_children（存量库将静默不迁移）"
    )


# ── DB 会话 fixture（镜像生产连接初始化：apply_sqlite_pragma → FK=ON） ──────


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
        apply_sqlite_pragma(dbapi_connection)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _create_project(db: AsyncSession) -> int:
    now = datetime.now(UTC)
    saved = await SQLiteProjectRepository(db).add(
        Project(
            id=uuid.uuid4(),
            name="FK 测试项目",
            config=ProjectConfig(model="gpt-4o"),
            created_at=now,
            updated_at=now,
        )
    )
    return saved.id.int


async def _seed_project_children(db: AsyncSession, pid: int) -> str:
    """每张子表各建 1 行（project_id 传 int），返回 execution id（flush 后 id 才可得）."""
    execution = AgentExecutionORM(pipeline="builtin:write_chapter", project_id=pid)
    db.add_all(
        [
            execution,
            AgentRunORM(project_id=pid),
            DraftORM(project_id=pid, content="草稿甲"),
            MemoryEventORM(project_id=pid, event_type="edit"),
            PlannerSessionORM(project_id=pid, one_liner="一句话甲"),
            ProjectPreferenceORM(
                project_id=pid, category="addressing", pattern="她", value="角色甲"
            ),
            SemanticSummaryORM(
                scope="project",
                project_id=pid,
                content="总结甲",
                anchor_hash="hash-a",
                model="gpt-4o",
            ),
            WritingPlanORM(project_id=pid, title="计划甲"),
        ]
    )
    await db.flush()
    return execution.id


async def _count_by_pid(db: AsyncSession, model, pid: int) -> int:
    stmt = select(func.count()).select_from(model).where(model.project_id == pid)
    return (await db.execute(stmt)).scalar_one()


async def _count_stage_results_for(db: AsyncSession, pid: int) -> int:
    stmt = (
        select(func.count())
        .select_from(AgentStageResultORM)
        .where(
            AgentStageResultORM.execution_id.in_(
                select(AgentExecutionORM.id).where(AgentExecutionORM.project_id == pid)
            )
        )
    )
    return (await db.execute(stmt)).scalar_one()


# ── 2. DB 行为层 ────────────────────────────────────────────────────────────


async def test_insert_unknown_project_id_rejected_1387(db_session: AsyncSession) -> None:
    """插不存在的 project_id → DB 层 FK 拒绝（不再靠应用层自觉）."""
    db_session.add(AgentRunORM(project_id=987_654_321))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_raw_project_delete_cascades_children_1387(db_session: AsyncSession) -> None:
    """有牙断言：**绕过仓储层**直接删 projects 行 → 8 张子表 + agent_stage_results 全清.

    方案 A 的 `_purge_string_pid_children` 不参与本路径 —— 只有 DB 级 FK CASCADE 能满足。
    """
    pid = await _create_project(db_session)
    execution_id = await _seed_project_children(db_session, pid)
    db_session.add(
        AgentStageResultORM(execution_id=execution_id, stage_id="outline", status="completed")
    )
    await db_session.commit()

    for model, table_name in CHILD_MODELS:
        assert await _count_by_pid(db_session, model, pid) == 1, f"{table_name} 前置不成立"
    assert await _count_stage_results_for(db_session, pid) == 1, "前置不成立"

    # 绕过 repo/service：直接 DELETE projects 行
    await db_session.execute(sa_delete(ProjectORM).where(ProjectORM.id == pid))
    await db_session.commit()

    for model, table_name in CHILD_MODELS:
        assert await _count_by_pid(db_session, model, pid) == 0, f"{table_name} 未被 DB 级联清理"
    assert await _count_stage_results_for(db_session, pid) == 0, "agent_stage_results 未被级联清理"


# ── 3. 迁移层（旧库 VARCHAR(36) → INTEGER + FK） ────────────────────────────

# (表名, 额外 NOT NULL 列定义, 额外列取值) —— 旧库表结构保真（最小但非空列齐备）
_LEGACY_EXTRA: tuple[tuple[str, str, str, str], ...] = (
    ("agent_executions", "pipeline", "VARCHAR(100) NOT NULL", "builtin:write_chapter"),
    ("agent_runs", "mode", "VARCHAR(20) NOT NULL", "agentic"),
    ("drafts", "content", "TEXT NOT NULL", "草稿甲"),
    ("memory_events", "event_type", "VARCHAR(30) NOT NULL", "edit"),
    ("planner_sessions", "one_liner", "VARCHAR(500) NOT NULL", "一句话甲"),
    ("project_preferences", "category", "VARCHAR(50) NOT NULL", "addressing"),
    ("semantic_summaries", "scope", "VARCHAR(20) NOT NULL", "project"),
    ("writing_plans", "title", "VARCHAR(200) NOT NULL", "计划甲"),
)


def _build_legacy_db(path: Path) -> None:
    """旧库形态：8 张子表 project_id 为 VARCHAR(36)（存 str(UUID(int=id))）、无 FK；
    agent_stage_results.execution_id 有 FK 但无 ondelete（RESTRICT）。

    每表 3 行：project 1 / project 2（有效）+ 不存在项目（孤儿）；
    semantic_summaries 额外 1 行 project_id=NULL（scope=user，非孤儿，必须保留）。
    """
    con = sqlite3.connect(str(path), isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute(
            "CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        con.execute("INSERT INTO projects (id, name) VALUES (1, '项目甲'), (2, '项目乙')")
        for table_name, extra_col, extra_def, extra_val in _LEGACY_EXTRA:
            con.execute(
                f"CREATE TABLE {table_name} ("
                f"id VARCHAR(36) NOT NULL PRIMARY KEY, "
                f"project_id VARCHAR(36)"
                f"{'' if table_name == 'semantic_summaries' else ' NOT NULL'}, "
                f"{extra_col} {extra_def})"
            )
            for suffix, pid in (
                ("valid-1", str(uuid.UUID(int=1))),
                ("valid-2", str(uuid.UUID(int=2))),
                ("orphan", str(uuid.UUID(int=999))),
            ):
                con.execute(
                    f"INSERT INTO {table_name} (id, project_id, {extra_col}) VALUES (?, ?, ?)",
                    (f"{table_name}-{suffix}", pid, extra_val),
                )
        con.execute(
            "INSERT INTO semantic_summaries (id, project_id, scope) "
            "VALUES ('user-summary', NULL, 'user')"
        )
        con.execute(
            "CREATE TABLE agent_stage_results ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "execution_id VARCHAR(36) NOT NULL, stage_id VARCHAR(50) NOT NULL, "
            "FOREIGN KEY(execution_id) REFERENCES agent_executions(id))"
        )
        con.execute(
            "INSERT INTO agent_stage_results (execution_id, stage_id) "
            "VALUES ('agent_executions-valid-1', 'outline')"
        )
    finally:
        con.close()


@pytest.fixture
async def legacy_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """指向旧库文件的 async engine（monkeypatch 模块级 engine，使迁移走真实调用形态）."""
    db_path = tmp_path / "legacy_1387.db"
    _build_legacy_db(db_path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setattr(db_module, "engine", engine)
    yield db_path, engine
    await engine.dispose()


def _read(db_path: Path, sql: str) -> list[tuple]:
    con = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        return [tuple(row) for row in con.execute(sql)]
    finally:
        con.close()


def _fk_list(db_path: Path, table: str) -> list[tuple[str, str, str]]:
    return [
        (row[2], row[3], row[6])  # (父表, 子列, on_delete)
        for row in _read(db_path, f"PRAGMA foreign_key_list({table})")
    ]


def _project_id_type(db_path: Path, table: str) -> str:
    for row in _read(db_path, f"PRAGMA table_info({table})"):
        if row[1] == "project_id":
            return str(row[2]).upper()
    return ""


def _count(db_path: Path, sql: str) -> int:
    rows = _read(db_path, sql)
    assert rows
    return int(rows[0][0])


async def _run_migration() -> None:
    runner = getattr(db_module, "run_project_id_fk_migration", None)
    assert runner is not None, (
        "core/database.py 必须 re-export run_project_id_fk_migration（ADR-063 迁移入口）"
    )
    await runner()


async def test_migration_converts_column_and_adds_cascade_fk_1387(legacy_engine) -> None:
    db_path, engine = legacy_engine
    assert _project_id_type(db_path, "drafts") == "VARCHAR(36)"  # 前置：旧形态
    assert _fk_list(db_path, "drafts") == []

    await _run_migration()
    await engine.dispose()

    for table_name, _nullable in PROJECT_FK_CHILD_TABLES:
        assert _project_id_type(db_path, table_name) == "INTEGER", (
            f"{table_name}.project_id 未转为 INTEGER"
        )
        assert ("projects", "project_id", "CASCADE") in _fk_list(db_path, table_name), (
            f"{table_name}.project_id 未建立 FK(projects.id) ON DELETE CASCADE"
        )
    assert ("agent_executions", "execution_id", "CASCADE") in _fk_list(
        db_path, "agent_stage_results"
    ), "agent_stage_results.execution_id 未补 ON DELETE CASCADE"

    # 存量值转换：str(UUID(int=1)) → 1
    for table_name, _nullable in PROJECT_FK_CHILD_TABLES:
        assert _count(db_path, f"SELECT COUNT(*) FROM {table_name} WHERE project_id = 1") == 1, (
            f"{table_name} 有效行未转换为 int project_id=1"
        )
        assert _count(db_path, f"SELECT COUNT(*) FROM {table_name} WHERE project_id = 2") == 1, (
            f"{table_name} 有效行未转换为 int project_id=2"
        )

    # semantic_summaries 的 scope=user 行（project_id=NULL）必须保留
    assert (
        _count(db_path, "SELECT COUNT(*) FROM semantic_summaries WHERE project_id IS NULL") == 1
    ), "scope=user（NULL）行未保留"

    assert _count(db_path, "SELECT COUNT(*) FROM agent_stage_results") == 1

    con = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        con.close()


async def test_migration_quarantines_orphans_without_deleting_1387(legacy_engine) -> None:
    """孤儿行（指向不存在项目）→ 复制到 <table>__orphan_1387 后从主表移除（不静默删除）."""
    db_path, engine = legacy_engine
    await _run_migration()
    await engine.dispose()

    for table_name, _nullable in PROJECT_FK_CHILD_TABLES:
        quarantine = f"{table_name}{QUARANTINE_SUFFIX}"
        assert (
            _count(
                db_path,
                f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{quarantine}'",
            )
            == 1
        ), f"{table_name}: 存在孤儿行但未创建隔离表 {quarantine}"
        assert _count(db_path, f"SELECT COUNT(*) FROM {quarantine}") == 1, (
            f"{table_name}: 隔离表未保留孤儿行"
        )
        assert _count(db_path, f"SELECT COUNT(*) FROM {table_name} WHERE project_id = 999") == 0, (
            f"{table_name}: 孤儿行未从主表移除"
        )


async def test_migration_idempotent_second_run_1387(legacy_engine) -> None:
    """连续两次启动（跑两次迁移）：不报错、不重复写、隔离表不重复累积."""
    db_path, engine = legacy_engine
    await _run_migration()
    await _run_migration()  # 第二次不得抛错
    await engine.dispose()

    for table_name, _nullable in PROJECT_FK_CHILD_TABLES:
        quarantine = f"{table_name}{QUARANTINE_SUFFIX}"
        assert _count(db_path, f"SELECT COUNT(*) FROM {quarantine}") == 1, (
            f"{table_name}: 二次迁移重复累积孤儿行"
        )
        # 2 行有效（project 1/2）；semantic_summaries 另有 1 行 scope=user（NULL）
        expected = 3 if table_name == "semantic_summaries" else 2
        assert _count(db_path, f"SELECT COUNT(*) FROM {table_name}") == expected, (
            f"{table_name}: 二次迁移后主表行数异常"
        )
        assert _project_id_type(db_path, table_name) == "INTEGER"
