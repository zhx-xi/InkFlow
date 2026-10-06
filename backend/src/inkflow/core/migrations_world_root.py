"""#1481 存量项目补根幂等迁移（自 `core/database.py` 拆出，900 行护栏）.

`ensure_world_root_for_projects`：为**每个无根的非删除项目**补默认根「世界观总纲」，
让「每项目恒有且仅有一个根」（specs/f35-world-tree §2.1 规则 7 / §5.7）对既有库成立。
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from inkflow.domain.models.world import DEFAULT_WORLD_ROOT_NAME


def ensure_world_root_for_projects(conn: Connection) -> None:
    """#1481：为每个无根的非删除项目补默认根条目（幂等，conn.run_sync 调用）.

    语义（specs/f35-world-tree §5.7）：
    - **只 INSERT**（`INSERT ... SELECT`），不 UPDATE/DELETE 任何既有行（数据保全）；
    - **幂等判据** = 该项目下不存在 `parent_id IS NULL` 的行 ⇒ 重复执行不重复建、
      不产生第二根、不改既有根（含既有根名）；
    - **软删项目跳过**（`is_deleted = 1`）——不为回收站项目建根；
    - 表/列缺失（全新环境或极旧库）→ 按缺失列自适应（`extra` / `created_at` /
      `updated_at` 等列不存在时不写入），`parent_id` 或 `projects` 表缺失则 no-op。

    调用点须在 `ensure_world_root_unique_index` 之后（根单例索引已就位）与
    `ensure_entity_uuid_columns` 之前（新行 `uuid` 身份列由后者回填）——见 api/app.py。

    Args:
        conn: 同步连接（`conn.run_sync` 传入）.
    """
    ws_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(world_settings)")).fetchall()}
    if "parent_id" not in ws_cols:
        return  # 表不存在（全新环境）/ parent_id 列未就位 → no-op
    proj_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(projects)")).fetchall()}
    if not proj_cols:
        return
    # 列存在性自适应：v0.11 旧库 world_settings 无 extra/created_at/updated_at
    # （create_all 只建缺失表、不补缺失列），硬编码列名会让 SQLite 在 prepare 阶段报
    # "no column named extra"（即便 projects 为空也会失败）。
    columns = ["project_id", "name", "parent_id"]
    exprs = ["p.id", ":root_name", "NULL"]
    for col in ("category", "content"):
        if col in ws_cols:
            columns.append(col)
            exprs.append("''")
    if "extra" in ws_cols:
        columns.append("extra")
        exprs.append("'{}'")
    for col in ("created_at", "updated_at"):
        if col in ws_cols:
            columns.append(col)
            exprs.append("CURRENT_TIMESTAMP")
    sql = (
        f"INSERT INTO world_settings ({', '.join(columns)}) "
        f"SELECT {', '.join(exprs)} FROM projects p "
        "WHERE NOT EXISTS (SELECT 1 FROM world_settings w "
        "WHERE w.project_id = p.id AND w.parent_id IS NULL) "
    )
    # 旧库 projects 表可能尚未补 is_deleted 列（ensure_project_columns 之前）——同上自适应
    if "is_deleted" in proj_cols:
        sql += "AND p.is_deleted = 0"
    conn.execute(text(sql), {"root_name": DEFAULT_WORLD_ROOT_NAME})
