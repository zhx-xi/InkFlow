"""#1134 / ADR-060 批 2：实体 uuid 身份列迁移（26 张 int PK 表）。

抽为独立模块的原因：``core/database.py`` 有 900 行护栏（#307），
与 migrations_chapter / migrations_project / migrations_character_relation 同族。
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from inkflow.core.uuid_gen import derive_uuid_for_row

# 26 张 int PK 表（ADR-060 D1）。9 张 str PK 表不在范围（B2-改：保留形态）。
ENTITY_UUID_TABLES: tuple[str, ...] = (
    "agent_stage_results",
    "agents",
    "agent_templates",
    "audit_logs",
    "volumes",
    "chapters",
    "characters",
    "character_groups",
    "chat_messages",
    "chapter_summaries",
    "conversations",
    "extraction_runs",
    "foreshadowings",
    "knowledge_relations",
    "maps",
    "map_pins",
    "outlines",
    "plot_points",
    "story_arcs",
    "projects",
    "provider_configs",
    "sessions",
    "session_logs",
    "timeline_events",
    "world_settings",
    "world_categories",
)


def _uuid_index_name(table: str) -> str:
    return f"ix_{table}_uuid"


def ensure_entity_uuid_columns(conn: Connection) -> None:
    """#1134/ADR-060 D7：为 26 张 int PK 表补 uuid 身份列（幂等）。

    步骤（每表）：
      ① PRAGMA 检列 → 缺则 ``ALTER TABLE ADD COLUMN uuid TEXT``（可空，非阻塞）
      ② 回填 NULL 行：``uuid = uuid5(NS, "<table>:<id>")``（确定性，ADR-060 D8）
      ③ ``CREATE UNIQUE INDEX IF NOT EXISTS`` 加唯一约束

    🔴 唯一性必须用 **CREATE UNIQUE INDEX**，禁用列级 ``UNIQUE`` 约束——
    实测列级约束会让 ``DROP COLUMN`` 永久失败（``cannot drop UNIQUE column``），
    回滚路径死掉（ADR-060 D7）。

    表不存在（全新环境）→ no-op，等 ``create_all`` 建新表（ORM 已含 uuid 列）。
    """
    for table in ENTITY_UUID_TABLES:
        cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        names = {row[1] for row in cols}
        if not names:
            continue  # 表不存在（全新环境）→ create_all 负责
        if "uuid" not in names:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN uuid TEXT"))
        # 回填仅 NULL 行（渐进回填；已有值绝不覆盖）
        rows = conn.execute(text(f"SELECT id FROM {table} WHERE uuid IS NULL")).fetchall()
        for (local_id,) in rows:
            conn.execute(
                text(f"UPDATE {table} SET uuid = :v WHERE id = :i"),
                {"v": str(derive_uuid_for_row(table, local_id)), "i": local_id},
            )
        conn.execute(
            text(f"CREATE UNIQUE INDEX IF NOT EXISTS {_uuid_index_name(table)} ON {table} (uuid)")
        )


def rollback_entity_uuid_columns(conn: Connection) -> None:
    """#1134/ADR-060 D7：回滚 uuid 列（幂等）。

    🔴 **顺序不可颠倒**：必须先 ``DROP INDEX`` 再 ``DROP COLUMN``——
    实测索引存在时直接 DROP COLUMN 报
    ``error in index ... after drop column``（ADR-060 D7）。
    """
    for table in ENTITY_UUID_TABLES:
        cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        names = {row[1] for row in cols}
        if not names:
            continue
        conn.execute(text(f"DROP INDEX IF EXISTS {_uuid_index_name(table)}"))
        if "uuid" in names:
            conn.execute(text(f"ALTER TABLE {table} DROP COLUMN uuid"))
