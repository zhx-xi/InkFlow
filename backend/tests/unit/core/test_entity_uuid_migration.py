"""#1134 / ADR-060 批 2: uuid 身份列迁移 RED 契约测试。

契约（ADR-060 D1/D7/D8）:
  - 26 张 int PK 表各新增 `uuid` TEXT 可空列
  - 回填: uuid = uuid5(NS, "<table>:<id>")  —— 确定性（同库重跑一致）
  - 唯一性用 **CREATE UNIQUE INDEX**（非列级 UNIQUE 约束 —— 否则回滚路径死掉）
  - 幂等: 重复执行不报错、不覆盖已有 uuid 值
  - 回滚: DROP INDEX 先于 DROP COLUMN（顺序不可颠倒）
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from inkflow.core.database import (
    ENTITY_UUID_TABLES,
    Base,
    ensure_entity_uuid_columns,
    rollback_entity_uuid_columns,
)
from inkflow.core.uuid_gen import UUID_NAMESPACE
from inkflow.infrastructure.database import (
    models as _models,  # noqa: F401  # 导入即触发 Base.metadata 注册，名称不直接使用
)


@pytest.fixture
def sync_conn():
    """已建全部表的内存库；**剥离 uuid 列**模拟「升级前旧库」。

    与 tests/unit/core 现有 sync_conn（空库）不同：本批迁移需 ALTER 已存在表。
    """
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        for t in ENTITY_UUID_TABLES:
            cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({t})")).fetchall()}
            if "uuid" in cols:
                conn.execute(text(f"DROP INDEX IF EXISTS ix_{t}_uuid"))
                conn.execute(text(f"ALTER TABLE {t} DROP COLUMN uuid"))
        yield conn
    engine.dispose()


def _cols(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def _indexes(conn, table: str) -> dict[str, str]:
    rows = conn.execute(
        text(f"SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='{table}'")
    ).fetchall()
    return {r[0]: (r[1] or "") for r in rows}


def _add_project(conn, name: str) -> None:
    """插一条合法 project 行（用 ORM 构造，自动带列默认值）。"""
    from inkflow.infrastructure.database.models.project import ProjectORM

    conn.execute(ProjectORM.__table__.insert().values(name=name))


class TestTableCoverage:
    def test_table_count_is_26(self) -> None:
        assert len(ENTITY_UUID_TABLES) == 26

    def test_contains_core_tables(self) -> None:
        for t in ("projects", "chapters", "characters", "world_settings", "knowledge_relations"):
            assert t in ENTITY_UUID_TABLES

    def test_excludes_str_pk_tables(self) -> None:
        """B2-改: 9 张 str PK 表不在本批范围（保留形态）。"""
        for t in ("agent_runs", "drafts", "agent_executions", "memory_events"):
            assert t not in ENTITY_UUID_TABLES

    def test_all_tables_registered_in_metadata(self) -> None:
        """守护: 26 张表必须都已注册 Base.metadata。

        回归背景（批 2 实测）：models/__init__.py 曾漏导出 agent_template，
        导致该表仅在「恰好有人 import 它」时才注册——真机由
        api/routers/agent_templates.py 间接 import 而掩盖，新库 create_all
        静默缺表。本断言让该脆弱点无法再悄悄回归。
        """
        missing = [t for t in ENTITY_UUID_TABLES if t not in Base.metadata.tables]
        assert missing == [], f"未注册到 Base.metadata: {missing}"


class TestColumnAdded:
    def test_uuid_column_added(self, sync_conn) -> None:
        ensure_entity_uuid_columns(sync_conn)
        for t in ENTITY_UUID_TABLES:
            assert "uuid" in _cols(sync_conn, t), f"{t} 缺 uuid 列"

    def test_uuid_column_is_nullable(self, sync_conn) -> None:
        """本地阶段保持可空（ADR-060 D7）。"""
        ensure_entity_uuid_columns(sync_conn)
        rows = sync_conn.execute(text("PRAGMA table_info(projects)")).fetchall()
        uuid_col = next(r for r in rows if r[1] == "uuid")
        assert uuid_col[3] == 0  # notnull == 0


class TestBackfill:
    def test_existing_rows_backfilled(self, sync_conn) -> None:
        _add_project(sync_conn, "p1")
        _add_project(sync_conn, "p2")
        ensure_entity_uuid_columns(sync_conn)
        rows = sync_conn.execute(text("SELECT id, uuid FROM projects ORDER BY id")).fetchall()
        assert len(rows) == 2
        assert all(r[1] for r in rows), "回填后 uuid 不应为空"

    def test_backfill_is_deterministic(self, sync_conn) -> None:
        """同库重跑结果一致（回滚再升级不换 id）。"""
        _add_project(sync_conn, "p1")
        ensure_entity_uuid_columns(sync_conn)
        first = sync_conn.execute(text("SELECT id, uuid FROM projects")).fetchall()
        ensure_entity_uuid_columns(sync_conn)
        second = sync_conn.execute(text("SELECT id, uuid FROM projects")).fetchall()
        assert first == second

    def test_backfill_matches_uuid5_formula(self, sync_conn) -> None:
        _add_project(sync_conn, "p1")
        ensure_entity_uuid_columns(sync_conn)
        row = sync_conn.execute(text("SELECT id, uuid FROM projects")).fetchone()
        expected = str(uuid.uuid5(UUID_NAMESPACE, f"projects:{row[0]}"))
        assert row[1] == expected

    def test_idempotent_does_not_overwrite(self, sync_conn) -> None:
        """已有 uuid 值绝不覆盖（幂等铁律）。"""
        _add_project(sync_conn, "p1")
        ensure_entity_uuid_columns(sync_conn)
        sync_conn.execute(text("UPDATE projects SET uuid = 'manual-value'"))
        ensure_entity_uuid_columns(sync_conn)
        got = sync_conn.execute(text("SELECT uuid FROM projects")).scalar()
        assert got == "manual-value"

    def test_partial_null_rows_get_filled(self, sync_conn) -> None:
        """只回填 NULL 行（渐进回填）。"""
        _add_project(sync_conn, "p1")
        _add_project(sync_conn, "p2")
        ensure_entity_uuid_columns(sync_conn)
        sync_conn.execute(text("UPDATE projects SET uuid = NULL WHERE id = 2"))
        ensure_entity_uuid_columns(sync_conn)
        assert sync_conn.execute(text("SELECT uuid FROM projects WHERE id=2")).scalar()


class TestUniqueIndex:
    def test_unique_index_created(self, sync_conn) -> None:
        ensure_entity_uuid_columns(sync_conn)
        for t in ENTITY_UUID_TABLES:
            idx = _indexes(sync_conn, t)
            assert any("uuid" in name for name in idx), f"{t} 缺 uuid 唯一索引"

    def test_index_is_unique(self, sync_conn) -> None:
        ensure_entity_uuid_columns(sync_conn)
        idx = _indexes(sync_conn, "projects")
        uuid_idx_sql = next(sql for name, sql in idx.items() if "uuid" in name)
        assert "UNIQUE" in uuid_idx_sql.upper()

    def test_duplicate_uuid_rejected(self, sync_conn) -> None:
        _add_project(sync_conn, "p1")
        _add_project(sync_conn, "p2")
        ensure_entity_uuid_columns(sync_conn)
        with pytest.raises(IntegrityError):
            sync_conn.execute(text("UPDATE projects SET uuid = 'dup'"))
            sync_conn.execute(text("UPDATE projects SET uuid = 'dup'"))

    def test_multiple_nulls_allowed(self, sync_conn) -> None:
        """可空列 + 唯一索引：多个 NULL 合法（实测行为）。"""
        ensure_entity_uuid_columns(sync_conn)
        _add_project(sync_conn, "a")
        _add_project(sync_conn, "b")
        sync_conn.execute(text("UPDATE projects SET uuid = NULL"))


class TestRollback:
    def test_rollback_removes_column(self, sync_conn) -> None:
        ensure_entity_uuid_columns(sync_conn)
        rollback_entity_uuid_columns(sync_conn)
        for t in ENTITY_UUID_TABLES:
            assert "uuid" not in _cols(sync_conn, t), f"{t} 回滚后仍有 uuid 列"

    def test_rollback_is_idempotent(self, sync_conn) -> None:
        rollback_entity_uuid_columns(sync_conn)  # 未升级也可回滚
        rollback_entity_uuid_columns(sync_conn)

    def test_upgrade_rollback_upgrade_roundtrip(self, sync_conn) -> None:
        """回滚再升级 → uuid 值不变（确定性回填的验收点）。"""
        _add_project(sync_conn, "p1")
        ensure_entity_uuid_columns(sync_conn)
        before = sync_conn.execute(text("SELECT uuid FROM projects")).scalar()
        rollback_entity_uuid_columns(sync_conn)
        ensure_entity_uuid_columns(sync_conn)
        after = sync_conn.execute(text("SELECT uuid FROM projects")).scalar()
        assert before == after


class TestMissingTableNoOp:
    """表不存在（全新环境）→ no-op，不抛错（等 create_all 建表）。"""

    def test_upgrade_on_empty_db_is_noop(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            ensure_entity_uuid_columns(conn)  # 无任何表

    def test_rollback_on_empty_db_is_noop(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            rollback_entity_uuid_columns(conn)  # 无任何表

    def test_upgrade_skips_absent_table_only(self, sync_conn) -> None:
        """部分表存在时：存在的补列，缺失的跳过（不抛错）。"""
        sync_conn.execute(text("DROP TABLE character_groups"))
        ensure_entity_uuid_columns(sync_conn)
        assert "uuid" in _cols(sync_conn, "projects")
        assert _cols(sync_conn, "character_groups") == set()
