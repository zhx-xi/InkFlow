"""#988 草稿来源大纲节点绑定 — drafts.source_outline_id 列迁移 RED 契约测试（真同步 SQLite 轨）.

被测模块（当前未实现，用例体 lazy import → ImportError = 收集失败形态，规则 1c 混合轨）:
    from inkflow.core.database import ensure_drafts_source_outline_id_column

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
ensure_drafts_source_outline_id_column(conn):
- PRAGMA table_info(drafts) → 无 source_outline_id 列
  → ALTER TABLE drafts ADD COLUMN source_outline_id VARCHAR(36)
- 表不存在（全新环境 / CI 测试 mock create_tables 场景）→ no-op 不抛错
- 幂等：二次调用不抛错且列集合不变

镜像先例: tests/unit/core/test_drafts_volume_migration.py（#976 volume_id 列迁移）。
RED 预期: inkflow.core.database 尚无 ensure_drafts_source_outline_id_column →
用例体 lazy import ImportError（FAILED 形态，非收集 ERROR，规则 1c 混合轨）。

接线契约（GREEN 必实现，本文件不重复断言，由 app 启动路径真实执行覆盖）:
- core/database.py 新增本函数 + api/app.py create_tables 后 run_sync 接线
- DraftORM 增 source_outline_id 列（String(36) nullable=True，镜像 volume_id 列形态）

本文件不声明 pytestmark.asyncio（真同步 SQLite 轨，镜像 volume 迁移测试）。
"""

from __future__ import annotations

from sqlalchemy import create_engine, text


def _cols(conn, table: str) -> set[str]:
    """返回表当前列名集合（迁移断言用，镜像 test_drafts_volume_migration._cols）。"""
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


class TestDraftsSourceOutlineMigration:
    """#988: ensure_drafts_source_outline_id_column 迁移契约（加列 + 幂等 + no-op）。"""

    def test_ensure_drafts_source_outline_id_column_migration(self) -> None:
        """【R】缺列库跑迁移 → PRAGMA 含 source_outline_id；幂等二跑不抛且列集合不变。

        表不存在 no-op。

        RED 预期（对照当前实现）: inkflow.core.database 无
        ensure_drafts_source_outline_id_column → 用例体 lazy import ImportError（FAILED 形态）。
        GREEN 必实现: ensure_drafts_source_outline_id_column(conn)——PRAGMA
        table_info(drafts) → 无 source_outline_id → ALTER TABLE ADD COLUMN
        source_outline_id VARCHAR(36)；表不存在（全新环境）→ no-op。
        """
        from inkflow.core.database import (  # RED: ImportError
            ensure_drafts_source_outline_id_column,
        )

        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE drafts (id VARCHAR(36) PRIMARY KEY, project_id VARCHAR(36), "
                    "chapter_id VARCHAR(36), agent_run_id VARCHAR(36), content TEXT, summary TEXT, "
                    "status VARCHAR(20), created_at DATETIME, confirmed_at DATETIME, "
                    "volume_id VARCHAR(36))"
                )
            )
            conn.commit()

            ensure_drafts_source_outline_id_column(conn)
            conn.commit()
            cols = _cols(conn, "drafts")
            assert "source_outline_id" in cols

            # 幂等：二次调用不抛错且列集合不变
            ensure_drafts_source_outline_id_column(conn)
            conn.commit()
            assert _cols(conn, "drafts") == cols

        # 表不存在（全新环境）→ no-op 不抛错
        fresh = create_engine("sqlite:///:memory:")
        with fresh.connect() as conn:
            ensure_drafts_source_outline_id_column(conn)
            assert _cols(conn, "drafts") == set()
