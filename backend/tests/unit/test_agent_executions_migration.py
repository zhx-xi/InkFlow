"""#354 后续：agent_executions.hitl_payload 列迁移契约测试（2026-08-14）。

背景：E2E 全量真实 LLM（e2e-pipeline-ai B1-1/B1-2/B1-3）暴露「生成失败: HTTP 500」——
根因 sqlite3.OperationalError: no such column: agent_executions.hitl_payload。
#161 Supervisor HITL 在 ORM（models/agent.py AgentExecutionORM）新增 hitl_payload 字段，
但 app.py lifespan 的幂等迁移链（ensure_provider_builtin_key_column 等）**缺该列的迁移**——
既有库（create_all 不重建表）无此列 → execute 写执行记录即 500。

本测试钉住迁移函数（对齐 ensure_map_columns 等先例）：
- 旧库（agent_executions 表存在但无 hitl_payload 列）→ 调用后列存在（ALTER TABLE 补列）
- 新库（create_all 已含列）→ 幂等 no-op
- 表不存在 → no-op 不抛错（全新环境等 create_all 建新表）
"""

import sqlite3

from inkflow.core.database import ensure_agent_executions_hitl_payload_column


def _make_old_db(path: str) -> None:
    """构造「旧 schema」库：agent_executions 表存在但无 hitl_payload 列。"""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE agent_executions (
            id VARCHAR(36) PRIMARY KEY,
            pipeline VARCHAR(100) NOT NULL,
            project_id VARCHAR(36) NOT NULL,
            chapter_id VARCHAR(36),
            status VARCHAR(20) NOT NULL,
            stages TEXT NOT NULL,
            final_output TEXT NOT NULL,
            error TEXT NOT NULL,
            total_duration_ms INTEGER NOT NULL,
            created_at DATETIME NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def _columns(path: str, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    conn.close()
    return {row[1] for row in rows}


def test_old_db_gets_hitl_payload_column(tmp_path):
    """旧库：agent_executions 无 hitl_payload → 迁移后补列（幂等可重跑）。"""
    db = tmp_path / "old.db"
    _make_old_db(str(db))
    conn = sqlite3.connect(str(db))
    assert "hitl_payload" not in _columns(str(db), "agent_executions")

    ensure_agent_executions_hitl_payload_column(conn)
    assert "hitl_payload" in _columns(str(db), "agent_executions")

    # 幂等：再跑一次不抛错、列不重复（set 无重复概念，断言列集恒为单元素）
    ensure_agent_executions_hitl_payload_column(conn)
    conn.close()
    assert "hitl_payload" in _columns(str(db), "agent_executions")


def test_new_db_noop(tmp_path):
    """新库：create_all 已含 hitl_payload → no-op 不改变列集。"""
    db = tmp_path / "new.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE agent_executions (
            id VARCHAR(36) PRIMARY KEY,
            pipeline VARCHAR(100) NOT NULL,
            project_id VARCHAR(36) NOT NULL,
            chapter_id VARCHAR(36),
            status VARCHAR(20) NOT NULL,
            stages TEXT NOT NULL,
            final_output TEXT NOT NULL,
            error TEXT NOT NULL,
            total_duration_ms INTEGER NOT NULL,
            hitl_payload TEXT,
            created_at DATETIME NOT NULL
        )
        """
    )
    conn.commit()
    before = _columns(str(db), "agent_executions")

    ensure_agent_executions_hitl_payload_column(conn)
    conn.close()
    assert _columns(str(db), "agent_executions") == before


def test_missing_table_noop(tmp_path):
    """表不存在（全新环境）→ no-op 不抛错，等 create_all 建新表。"""
    db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db))

    ensure_agent_executions_hitl_payload_column(conn)  # 不应抛错
    conn.close()
    # 未建任何表（函数不应隐式建表）
    conn = sqlite3.connect(str(db))
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    assert tables == []
