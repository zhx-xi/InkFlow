"""#1387 / ADR-063：8 张 String(36) ``project_id`` 子表归一为 INTEGER + FK CASCADE。

抽为独立模块的原因：``core/database.py`` 有 900 行护栏（#307），
与 ``migrations_uuid`` / ``migrations_chapter`` 同族。

迁移形态（ADR-054 惯例：``create_all`` 管新库 + ``ensure_*`` 修旧库）：

- 旧库 ``project_id`` 是 ``VARCHAR(36)``（存 ``str(uuid.UUID(int=projects.id))``）
  → SQLite 无法 ``ALTER`` 加 FK，走官方 table-rebuild：建 ``_<t>_new`` → 迁数据
  → ``DROP``/``RENAME`` → 重建索引（镜像 #831 ``_rebuild_characters_without_group_id``）；
- 孤儿行（uuid 不可解析 / ``.int`` 越界 / ``projects`` 无此 id）复制到
  ``<table>__orphan_1387`` 备份表后从主表移除，绝不静默删数据
  （#1409 判定层/数据层分离，迁移只做物理搬运 + 报告）；
- ``agent_stage_results.execution_id`` 补 ``ON DELETE CASCADE``（原 FK 无 ondelete
  → RESTRICT 会截断 projects → agent_executions → agent_stage_results 级联链），
  其 FK 指向本批会重建的 agent_executions，故最后处理。
"""

from __future__ import annotations

import re
import uuid
from contextlib import suppress

from loguru import logger
from sqlalchemy import Connection

# (表名, project_id 是否可空) × 8 张表（ADR-063；顺序即重建顺序）
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

_STAGE_RESULTS_TABLE = "agent_stage_results"
_ORPHAN_SUFFIX = "__orphan_1387"
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63

_PROJECT_ID_COLUMN_RE = re.compile(r'^\s*"?project_id"?\s')
_EXECUTION_ID_COLUMN_RE = re.compile(r'^\s*"?execution_id"?\s')
_EXECUTION_FK_RE = re.compile(
    r"FOREIGN\s+KEY\s*\(\s*\"?execution_id\"?\s*\)",
    re.IGNORECASE,
)


def _table_sql(conn: Connection, table: str) -> str | None:
    """读取表的原始 ``sqlite_master.sql``（表不存在 → None，全新库交给 create_all）."""
    row = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def _has_target_fk(conn: Connection, table: str, parent: str, child: str) -> bool:
    """幂等守卫：表是否已声明 ``child → parent`` 且 ``ON DELETE CASCADE`` 的 FK."""
    rows = conn.exec_driver_sql(f"PRAGMA foreign_key_list({table})").fetchall()
    for row in rows:
        # PRAGMA 列序: (id, seq, table, from, to, on_update, on_delete, match)
        if str(row[2]) == parent and str(row[3]) == child and str(row[6]).upper() == "CASCADE":
            return True
    return False


def _sql_top_level_segments(create_sql: str) -> list[str]:
    """按顶层逗号拆分 ``CREATE TABLE`` 主体为列/约束段（括号嵌套感知）."""
    start = create_sql.index("(")
    end = create_sql.rindex(")")
    body = create_sql[start + 1 : end]
    segments: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            segments.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        segments.append("".join(current).strip())
    return [seg for seg in segments if seg]


def _replace_project_id_segment(
    segments: list[str],
    table: str,
    *,
    nullable: bool,
) -> list[str]:
    """仅替换 ``project_id`` 列定义段，其余列/约束段保持字节不变."""
    target = (
        "project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE"
        if nullable
        else "project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE"
    )
    replaced = False
    new_segments: list[str] = []
    for segment in segments:
        if _PROJECT_ID_COLUMN_RE.match(segment):
            new_segments.append(target)
            replaced = True
        else:
            new_segments.append(segment)
    if not replaced:
        raise RuntimeError(f"{table} 表 DDL 缺 project_id 列定义段，无法安全重建")
    return new_segments


def _replace_execution_fk_segment(segments: list[str]) -> list[str]:
    """把 agent_stage_results 的 execution_id 表级 FK 段替换为 ON DELETE CASCADE."""
    target = "FOREIGN KEY(execution_id) REFERENCES agent_executions(id) ON DELETE CASCADE"
    replaced = False
    new_segments: list[str] = []
    for segment in segments:
        if _EXECUTION_ID_COLUMN_RE.match(segment):
            new_segments.append(segment)
        elif _EXECUTION_FK_RE.search(segment):
            new_segments.append(target)
            replaced = True
        else:
            new_segments.append(segment)
    if not replaced:
        raise RuntimeError(
            "agent_stage_results 表 DDL 缺 execution_id FK 约束段（预期表级 "
            "FOREIGN KEY(execution_id) REFERENCES agent_executions），无法安全重建"
        )
    return new_segments


def _valid_project_ids(conn: Connection) -> set[int]:
    """当前 ``projects.id`` 集合（孤儿判定的权威父键面）."""
    return {int(row[0]) for row in conn.exec_driver_sql("SELECT id FROM projects").fetchall()}


def _out_of_int64(value: int) -> bool:
    return value < _INT64_MIN or value >= _INT64_MAX


def _normalize_project_pk(raw: object) -> int | None:
    """旧列文本 ``str(uuid)`` → int；不可解析/越界 → None（孤儿判据）."""
    if isinstance(raw, int):
        return None if _out_of_int64(raw) else raw
    try:
        parsed = uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None
    return None if _out_of_int64(parsed.int) else parsed.int


def _orphan_rowids(conn: Connection, table: str) -> list[int]:
    """孤儿行的 rowid 列表：不可解析 / int 越界 / 指向不存在的 projects.id."""
    valid_ids = _valid_project_ids(conn)
    rows = conn.exec_driver_sql(
        f"SELECT rowid, project_id FROM {table} WHERE project_id IS NOT NULL"
    ).fetchall()
    orphans: list[int] = []
    for rowid, raw in rows:
        normalized = _normalize_project_pk(raw)
        if normalized is None or normalized not in valid_ids:
            orphans.append(int(rowid))
    return orphans


def _quarantine_orphans(conn: Connection, table: str, orphan_rowids: list[int]) -> None:
    """把孤儿行复制到 ``<table>__orphan_1387``（旧形态），不静默删除数据."""
    rowids = ",".join(str(rowid) for rowid in orphan_rowids)
    quarantine = f"{table}{_ORPHAN_SUFFIX}"
    conn.exec_driver_sql(
        f"CREATE TABLE IF NOT EXISTS {quarantine} AS "
        f"SELECT * FROM {table} WHERE rowid IN ({rowids})"
    )
    logger.warning(
        "ADR-063 迁移：{} 发现 {} 行孤儿 project_id，已隔离到 {}（待人工确认清理）",
        table,
        len(orphan_rowids),
        quarantine,
    )


def _copy_rows(conn: Connection, table: str, orphan_rowids: list[int], *, convert: bool) -> None:
    """复制存活行到 ``_<table>_new``；convert=True 时把 project_id 文本转 int."""
    cols = [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()]
    col_list = ", ".join(cols)
    where = ""
    if orphan_rowids:
        rowids = ",".join(str(rowid) for rowid in orphan_rowids)
        where = f" WHERE rowid NOT IN ({rowids})"
    rows = conn.exec_driver_sql(f"SELECT {col_list} FROM {table}{where}").fetchall()

    converted: list[tuple[object, ...]] = []
    project_idx = cols.index("project_id") if convert else -1
    for row in rows:
        values = list(row)
        if convert:
            raw = values[project_idx]
            values[project_idx] = None if raw is None else uuid.UUID(str(raw)).int
        converted.append(tuple(values))

    if not converted:
        return
    placeholders = ", ".join("?" for _ in cols)
    conn.exec_driver_sql(
        f"INSERT INTO _{table}_new ({col_list}) VALUES ({placeholders})",
        converted,
    )


def _rebuild_table(
    conn: Connection,
    table: str,
    new_segments: list[str],
    orphan_rowids: list[int],
    *,
    convert: bool,
) -> None:
    """建 ``_<table>_new`` → 迁数 → DROP/RENAME → 重建非 autoindex 索引."""
    index_rows = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL "
        "AND name NOT LIKE 'sqlite_autoindex%'",
        (table,),
    ).fetchall()

    conn.exec_driver_sql(f"DROP TABLE IF EXISTS _{table}_new")
    conn.exec_driver_sql(f"CREATE TABLE _{table}_new ({', '.join(new_segments)})")
    _copy_rows(conn, table, orphan_rowids, convert=convert)
    conn.exec_driver_sql(f"DROP TABLE {table}")
    conn.exec_driver_sql(f"ALTER TABLE _{table}_new RENAME TO {table}")
    for (index_sql,) in index_rows:
        if index_sql:
            conn.exec_driver_sql(str(index_sql))


def _ensure_project_id_table(conn: Connection, table: str, nullable: bool) -> None:
    """单张 project_id 子表的幂等重建（表不存在/已带目标 FK → skip）."""
    create_sql = _table_sql(conn, table)
    if create_sql is None:
        return
    if _has_target_fk(conn, table, "projects", "project_id"):
        return
    new_segments = _replace_project_id_segment(
        _sql_top_level_segments(create_sql),
        table,
        nullable=nullable,
    )
    orphan_rowids = _orphan_rowids(conn, table)
    if orphan_rowids:
        _quarantine_orphans(conn, table, orphan_rowids)
    else:
        logger.debug("ADR-063 迁移：{} 无孤儿 project_id 行", table)
    _rebuild_table(conn, table, new_segments, orphan_rowids, convert=True)


def _ensure_stage_results_fk(conn: Connection) -> None:
    """agent_stage_results.execution_id 补 ON DELETE CASCADE（最后处理）."""
    create_sql = _table_sql(conn, _STAGE_RESULTS_TABLE)
    if create_sql is None:
        return
    if _has_target_fk(conn, _STAGE_RESULTS_TABLE, "agent_executions", "execution_id"):
        return
    new_segments = _replace_execution_fk_segment(_sql_top_level_segments(create_sql))
    _rebuild_table(conn, _STAGE_RESULTS_TABLE, new_segments, [], convert=False)


def ensure_project_id_fk_children(conn: Connection) -> None:
    """#1387 / ADR-063：8 张 project_id 子表归一 + agent_stage_results FK 补 CASCADE（幂等）.

    重建顺序：先 8 张 project_id 子表，``agent_stage_results`` 最后（其 FK 指向本批
    会重建的 ``agent_executions``）。第二次调用命中目标 FK 守卫 → 整体 no-op。
    """
    for table, nullable in PROJECT_FK_CHILD_TABLES:
        _ensure_project_id_table(conn, table, nullable)
    _ensure_stage_results_fk(conn)


async def run_project_id_fk_migration() -> None:
    """在 FK=OFF（AUTOCOMMIT）独立连接上执行 ADR-063 子表重建（幂等、原子）.

    镜像 ``run_character_group_members_migration``：app lifespan 的主迁移链在
    ``engine.begin()``（FK=ON）事务内运行，事务内 ``PRAGMA foreign_keys`` 是 no-op，
    且 DROP 会沿 FK CASCADE 清空关联表。故本函数在独立 AUTOCOMMIT 连接上先关闭 FK、
    整段 ``BEGIN``/``COMMIT`` 原子化，再恢复 FK=ON；调用方须在其它写事务提交后调用。
    """
    # 延迟导入：避免 core.database ↔ 本模块循环导入；同时读取调用时的模块全局
    # （测试/运行时会 monkeypatch ``inkflow.core.database.engine``）。
    from inkflow.core import database as db_module

    async with db_module.engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            await conn.exec_driver_sql("BEGIN")
            try:
                await conn.run_sync(ensure_project_id_fk_children)
            except Exception:
                with suppress(Exception):
                    await conn.exec_driver_sql("ROLLBACK")
                raise
            await conn.exec_driver_sql("COMMIT")
        finally:
            with suppress(Exception):
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
