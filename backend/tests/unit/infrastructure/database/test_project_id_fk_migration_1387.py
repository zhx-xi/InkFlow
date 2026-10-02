"""#1387 同步层契约：`ensure_project_id_fk_children` 的表重建 / 孤儿隔离 / 守卫（sync 连接直调）.

**为何另开 sync 轨**：生产入口是 `run_project_id_fk_migration()`（async + `conn.run_sync`），
而 SQLAlchemy 的 `run_sync` 在 **greenlet** 内执行 helper → coverage 记不到 helper 体内的行
（实测同一 legacy 库：sync 直调记录 136/166 行，经 run_sync 只记录 ~40 行）→ 该迁移在 CI
union 里几乎零归因、把 coverage-backend 顶到线下。本文件用 sync 引擎直调 helper（镜像
`test_agent_trace.py` 的 `ensure_*` 单测形态），把**行为契约**与**覆盖率归因**一并补齐。

覆盖的契约面（ADR-063）：
- 旧形态（VARCHAR(36) 无 FK）→ table-rebuild 为 INTEGER + `FK(projects.id) ON DELETE CASCADE`；
- 半迁移形态（列已是 INTEGER 但无 FK）也能升级（不崩）；
- 存量值 `str(uuid.UUID(int=id))` → int 转换；`scope=user` 的 NULL 行保留；
- 孤儿行（不可解析 / 越界 / 指向不存在项目）复制到 `<table>__orphan_1387` 后从主表移除；
- 表带非 autoindex 索引 → 重建后索引一并恢复；
- 幂等：二次调用 no-op；
- 守卫：DDL 不符预期（缺 `project_id` 列段 / 缺 `execution_id` FK 段）→ 响亮 refuse，不静默重建。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

from inkflow.core import database as db_module
from inkflow.core.migrations_project_id_fk import (
    PROJECT_FK_CHILD_TABLES,
    ensure_project_id_fk_children,
)

QUARANTINE_SUFFIX = "__orphan_1387"

# (表名, project_id 列类型, 额外 NOT NULL 列定义, 额外列取值)
_LEGACY_SPEC: tuple[tuple[str, str, str, str], ...] = (
    ("agent_executions", "VARCHAR(36)", "pipeline VARCHAR(100) NOT NULL", "builtin:write_chapter"),
    ("agent_runs", "VARCHAR(36)", "mode VARCHAR(20) NOT NULL", "agentic"),
    ("drafts", "INTEGER", "content TEXT NOT NULL", "草稿甲"),
    ("memory_events", "VARCHAR(36)", "event_type VARCHAR(30) NOT NULL", "edit"),
    ("planner_sessions", "VARCHAR(36)", "one_liner VARCHAR(500) NOT NULL", "一句话甲"),
    ("project_preferences", "VARCHAR(36)", "category VARCHAR(50) NOT NULL", "addressing"),
    ("semantic_summaries", "VARCHAR(36)", "scope VARCHAR(20) NOT NULL", "project"),
    ("writing_plans", "VARCHAR(36)", "title VARCHAR(200) NOT NULL", "计划甲"),
)

_STAGE_RESULTS_DDL = (
    "CREATE TABLE agent_stage_results ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "execution_id VARCHAR(36) NOT NULL, stage_id VARCHAR(50) NOT NULL, "
    "FOREIGN KEY(execution_id) REFERENCES agent_executions(id))"
)


def _legacy_db(path: Path) -> None:
    """旧库（含三种形态）：普通 VARCHAR 表 / INTEGER-无-FK 半迁移表 / 全孤儿表 + 索引."""
    con = sqlite3.connect(str(path), isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute(
            "CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        con.execute("INSERT INTO projects (id, name) VALUES (1, '项目甲'), (2, '项目乙')")
        for table, col_type, extra_def, extra_val in _LEGACY_SPEC:
            nullable = "" if table == "semantic_summaries" else " NOT NULL"
            con.execute(
                f"CREATE TABLE {table} ("
                f"id VARCHAR(36) NOT NULL PRIMARY KEY, "
                f"project_id {col_type}{nullable}, {extra_def})"
            )
            if table == "drafts":
                # 半迁移形态：列已是 INTEGER 但无 FK（历史手工改库 / 中断迁移残局）
                con.execute(
                    "INSERT INTO drafts (id, project_id, content) VALUES "
                    "('drafts-a', 1, '草稿甲'), ('drafts-b', 2, '草稿乙')"
                )
                continue
            if table == "memory_events":
                # 全孤儿表 → 新表零行（覆盖 _copy_rows 早退分支）
                con.execute(
                    "INSERT INTO memory_events (id, project_id, event_type) VALUES "
                    "('me-orphan-1', ?, 'edit'), ('me-orphan-2', ?, 'edit')",
                    (str(uuid.UUID(int=999)), str(uuid.UUID(int=1000))),
                )
                continue
            con.execute(
                f"INSERT INTO {table} (id, project_id, {extra_def.split()[0]}) VALUES (?, ?, ?)",
                (f"{table}-valid", str(uuid.UUID(int=1)), extra_val),
            )
        # 不可解析的 project_id 文本 → 孤儿（覆盖解析失败分支）
        con.execute(
            "INSERT INTO agent_runs (id, project_id, mode) VALUES "
            "('ar-bad', 'not-a-uuid', 'agentic')"
        )
        # 越界 128 位 uuid → 孤儿
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute(
            "INSERT INTO agent_runs (id, project_id, mode) VALUES ('ar-big', ?, 'agentic')",
            (str(uuid.uuid4()),),
        )
        con.execute("PRAGMA foreign_keys=ON")
        # scope=user（project_id NULL）必须保留
        con.execute(
            "INSERT INTO semantic_summaries (id, project_id, scope) VALUES ('user-1', NULL, 'user')"
        )
        # 非 autoindex 索引 → 重建后须恢复（同表两条 → 覆盖索引重建循环的回边）
        con.execute("CREATE INDEX ix_planner_sessions_project_id ON planner_sessions(project_id)")
        con.execute("CREATE INDEX ix_agent_runs_project_id ON agent_runs(project_id)")
        con.execute("CREATE INDEX ix_agent_runs_mode ON agent_runs(mode)")
        con.execute(_STAGE_RESULTS_DDL)
        con.execute(
            "INSERT INTO agent_stage_results (execution_id, stage_id) "
            "VALUES ('agent_executions-valid', 'outline')"
        )
    finally:
        con.close()


def _read(path: Path, sql: str) -> list[tuple]:
    con = sqlite3.connect(str(path), isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        return [tuple(row) for row in con.execute(sql)]
    finally:
        con.close()


def _scalar(path: Path, sql: str) -> int:
    rows = _read(path, sql)
    assert rows
    return int(rows[0][0])


def _project_id_type(path: Path, table: str) -> str:
    for row in _read(path, f"PRAGMA table_info({table})"):
        if row[1] == "project_id":
            return str(row[2]).upper()
    return ""


def _fk_list(path: Path, table: str) -> list[tuple[str, str, str]]:
    return [(row[2], row[3], row[6]) for row in _read(path, f"PRAGMA foreign_key_list({table})")]


def _migrate(path: Path) -> None:
    engine = sqlalchemy.create_engine(f"sqlite:///{path.as_posix()}")
    try:
        with engine.connect() as conn:
            ensure_project_id_fk_children(conn)
            conn.commit()
    finally:
        engine.dispose()


# ── 表不存在（全新库）→ 整体 no-op ──────────────────────────────────────────


def test_noop_when_tables_absent_1387(tmp_path: Path) -> None:
    """全新库（表由 create_all 负责）→ helper 不建表、不抛错."""
    db = tmp_path / "fresh.db"
    sqlite3.connect(str(db)).close()

    _migrate(db)

    assert _read(db, "SELECT name FROM sqlite_master WHERE type='table'") == []


# ── 主契约：旧形态升级 + 孤儿隔离 + 索引恢复 ────────────────────────────────


def test_upgrades_legacy_shape_quarantines_orphans_and_keeps_data_1387(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    _legacy_db(db)

    _migrate(db)

    for table, _nullable in PROJECT_FK_CHILD_TABLES:
        assert _project_id_type(db, table) == "INTEGER", f"{table}.project_id 未归一为 INTEGER"
        assert ("projects", "project_id", "CASCADE") in _fk_list(db, table), (
            f"{table} 未建立 FK(projects.id) ON DELETE CASCADE"
        )
    assert ("agent_executions", "execution_id", "CASCADE") in _fk_list(db, "agent_stage_results")

    # 存量值转换（VARCHAR 形态 + INTEGER 半迁移形态）
    assert _scalar(db, "SELECT COUNT(*) FROM planner_sessions WHERE project_id = 1") == 1
    assert _scalar(db, "SELECT COUNT(*) FROM drafts WHERE project_id = 1") == 1
    assert _scalar(db, "SELECT COUNT(*) FROM drafts WHERE project_id = 2") == 1

    # 孤儿（不可解析 / 越界 / 指向不存在项目）隔离保留，主表移除
    assert _scalar(db, "SELECT COUNT(*) FROM agent_runs WHERE project_id = 1") == 1
    assert _scalar(db, "SELECT COUNT(*) FROM agent_runs") == 1
    assert _scalar(db, "SELECT COUNT(*) FROM agent_runs__orphan_1387") == 2
    assert _scalar(db, "SELECT COUNT(*) FROM memory_events") == 0
    assert _scalar(db, "SELECT COUNT(*) FROM memory_events__orphan_1387") == 2

    # scope=user（NULL）行保留
    assert _scalar(db, "SELECT COUNT(*) FROM semantic_summaries WHERE project_id IS NULL") == 1

    # 索引恢复（同表两条独立索引，覆盖重建循环回边）
    for index_name in (
        "ix_planner_sessions_project_id",
        "ix_agent_runs_project_id",
        "ix_agent_runs_mode",
    ):
        assert (
            _scalar(
                db,
                f"SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='{index_name}'",
            )
            == 1
        )

    # agent_stage_results 行保留
    assert _scalar(db, "SELECT COUNT(*) FROM agent_stage_results") == 1

    # 全库无悬挂 FK
    assert _read(db, "PRAGMA foreign_key_check") == []


def test_second_call_is_noop_1387(tmp_path: Path) -> None:
    """幂等：连续两次升级不报错、不重复隔离、行数不变."""
    db = tmp_path / "legacy.db"
    _legacy_db(db)

    _migrate(db)
    _migrate(db)

    assert _scalar(db, "SELECT COUNT(*) FROM agent_runs__orphan_1387") == 2
    assert _scalar(db, "SELECT COUNT(*) FROM agent_runs") == 1
    assert _scalar(db, "SELECT COUNT(*) FROM drafts") == 2


# ── 守卫：DDL 不符预期 → 响亮 refuse（不静默重建） ──────────────────────────


def test_refuses_table_without_project_id_column_1387(tmp_path: Path) -> None:
    """缺 `project_id` 列段的表 → RuntimeError（拒绝按错误形状重建）."""
    db = tmp_path / "odd.db"
    con = sqlite3.connect(str(db), isolation_level=None)
    try:
        con.execute(
            "CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        con.execute("CREATE TABLE drafts (id VARCHAR(36) NOT NULL PRIMARY KEY, content TEXT)")
    finally:
        con.close()

    engine = sqlalchemy.create_engine(f"sqlite:///{db.as_posix()}")
    try:
        with engine.connect() as conn, pytest.raises(RuntimeError, match="缺 project_id"):
            ensure_project_id_fk_children(conn)
    finally:
        engine.dispose()


def test_refuses_stage_results_without_fk_clause_1387(tmp_path: Path) -> None:
    """agent_stage_results 缺 `execution_id` FK 约束段 → RuntimeError."""
    db = tmp_path / "odd2.db"
    con = sqlite3.connect(str(db), isolation_level=None)
    try:
        con.execute(
            "CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        con.execute(
            "CREATE TABLE agent_stage_results ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, execution_id VARCHAR(36) NOT NULL, "
            "stage_id VARCHAR(50) NOT NULL)"
        )
    finally:
        con.close()

    engine = sqlalchemy.create_engine(f"sqlite:///{db.as_posix()}")
    try:
        with engine.connect() as conn, pytest.raises(RuntimeError, match="缺 execution_id FK"):
            ensure_project_id_fk_children(conn)
    finally:
        engine.dispose()


# ── async runner：异常 → ROLLBACK + 原样上抛（原子性契约） ─────────────────


async def test_runner_rolls_back_and_reraises_on_error_1387(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """runner 内 helper 抛错 → ROLLBACK 且异常上抛（不留半成品事务）."""

    def _boom(_conn) -> None:  # 测试替身：模拟迁移体中途失败
        raise RuntimeError("migration boom")

    monkeypatch.setattr(
        "inkflow.core.migrations_project_id_fk.ensure_project_id_fk_children", _boom
    )
    db = tmp_path / "runner.db"
    sqlite3.connect(str(db)).close()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db.as_posix()}")
    monkeypatch.setattr(db_module, "engine", engine)
    try:
        with pytest.raises(RuntimeError, match="migration boom"):
            await db_module.run_project_id_fk_migration()
    finally:
        await engine.dispose()
