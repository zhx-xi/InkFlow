"""#849 世界观根单例 DB 级部分唯一索引 RED 契约测试.

锁定契约（当前实现无 (project_id) WHERE parent_id IS NULL 部分唯一索引 → 应 FAIL）:
1. 同项目并发创建两个根（parent_id=NULL）→ 第二个被 DB 约束拒绝（防竞态双建根）
2. ensure_world_root_unique_index 旧库补索引幂等迁移
3. ensure_world_root_unique_index 新库（已含索引）no-op
4. ensure_world_root_unique_index 无 world_settings 表 no-op

依据: issue #849 + specs/f10-world-settings/spec.md §7（并发双建根行）+
specs/f35-world-tree/spec.md §2.1 规则 6（DB 兜底）.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

# 索引名固定常量（与 ORM __table_args__ / ensure_* 迁移保持一致）
ROOT_INDEX = "uq_world_settings_root_per_project"


def _index_names(conn) -> set[str]:
    """返回 world_settings 当前索引名集合. """
    return {
        row[1]
        for row in conn.execute(text("PRAGMA index_list(world_settings)")).fetchall()
    }


def test_world_root_unique_index_rejects_double_root() -> None:
    """同项目并发创建两个根 → 第二个被部分唯一索引拒绝（DB 兜底）.

    当前实现 FAIL：仅 (project_id, parent_id, name) 全唯一，NULL 不冲突 → 双根成功.
    """
    from inkflow.infrastructure.database.models.world import WorldSettingORM

    engine = create_engine("sqlite:///:memory:")
    WorldSettingORM.__table__.create(engine)
    insert = text(
        "INSERT INTO world_settings "
        "(project_id, name, parent_id, category, content, extra, created_at, updated_at) "
        "VALUES (:pid, :name, NULL, '', '', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    with engine.begin() as conn:
        conn.execute(insert, {"pid": 1, "name": "根A"})
        # 第二个根（同项目 parent_id=NULL）→ 部分唯一索引拒绝
        with pytest.raises(IntegrityError):
            conn.execute(insert, {"pid": 1, "name": "根B"})


def test_ensure_world_root_unique_index_old_db_adds_index() -> None:
    """旧库（world_settings 存在但无根单例索引）→ 补建部分唯一索引（幂等）.

    当前实现 FAIL：ensure_world_root_unique_index 函数未实现（ImportError）.
    """
    from inkflow.core.database import ensure_world_root_unique_index

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE world_settings (id INTEGER PRIMARY KEY, "
                "project_id INTEGER, name TEXT, parent_id INTEGER)"
            )
        )
        conn.commit()
        assert ROOT_INDEX not in _index_names(conn)

        ensure_world_root_unique_index(conn)
        conn.commit()

        assert ROOT_INDEX in _index_names(conn)
        # 索引确实按 (project_id) WHERE parent_id IS NULL 建出
        sql = conn.execute(
            text(f"SELECT sql FROM sqlite_master WHERE type='index' AND name='{ROOT_INDEX}'")
        ).scalar_one()
        assert "WHERE parent_id IS NULL" in sql


def test_ensure_world_root_unique_index_fresh_schema_noop() -> None:
    """新库（world_settings 已含根单例索引）→ no-op 不抛错.

    当前实现 FAIL：ensure_world_root_unique_index 函数未实现（ImportError）.
    """
    from inkflow.core.database import ensure_world_root_unique_index

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE world_settings (id INTEGER PRIMARY KEY, "
                "project_id INTEGER, name TEXT, parent_id INTEGER)"
            )
        )
        conn.execute(
            text(
                f"CREATE UNIQUE INDEX {ROOT_INDEX} ON world_settings (project_id) "
                "WHERE parent_id IS NULL"
            )
        )
        conn.commit()

        ensure_world_root_unique_index(conn)  # no-op 不抛错
        assert ROOT_INDEX in _index_names(conn)


def test_ensure_world_root_unique_index_missing_table_noop() -> None:
    """无 world_settings 表 → no-op 不抛错（等 create_all 建新表自动含索引）.

    当前实现 FAIL：ensure_world_root_unique_index 函数未实现（ImportError）.
    """
    from inkflow.core.database import ensure_world_root_unique_index

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        ensure_world_root_unique_index(conn)  # no-op 不抛错
