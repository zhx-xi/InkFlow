"""#495：character_relations 行并入 knowledge_relations（幂等）。

从 ``core/database.py`` 抽出（该文件已达 900 行护栏上限，按 check_file_length.py
「超限文件优先拆分」规则独立成模块，镜像 migrations_chapter.py 先例）；
``core/database.py`` 保留同名 re-export，api/app.py 的 lifespan 接线与
既有测试 import 路径无需改动。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


def ensure_character_relations_merged_into_knowledge(conn: Connection) -> None:
    """#495 将 character_relations 行迁入 knowledge_relations 并删除专表.

    六元组转换：``(project_id, from, to, relation_type)`` →
    ``(project_id, 'character', from, 'character', to, relation_type)``；
    ``description``/``created_at``/``updated_at`` 保留原值，``source`` 置 'manual'。

    幂等与安全边界：
    - ``character_relations`` 缺失（新库 / 已迁移库）→ no-op；
    - ``knowledge_relations`` 缺失（防御）→ no-op，且**绝不删旧表**（数据安全优先）；
    - ``INSERT OR IGNORE``：同六元组键已存在于 kr（F48 Q1=A 双轨期图谱页建过
      同键角色关系）→ 保留 kr 既有版本，与既有图谱聚合「knowledge 优先」去重
      语义一致；
    - 数据保全后才 ``DROP TABLE character_relations``。

    🔴 链上顺序（load-bearing）：必须在 ``ensure_character_drop_is_deleted``
    **之后**运行——v1.1 前的旧库 character_relations 含 is_deleted 软删行，
    先由该 helper 物理清除软删行并摘列，本迁移才只搬活行（否则软删关系被复活）。
    """
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).fetchall()
    tables = {row[0] for row in rows}
    if "character_relations" not in tables or "knowledge_relations" not in tables:
        return
    conn.execute(
        text(
            "INSERT OR IGNORE INTO knowledge_relations "
            "(project_id, source_type, source_id, target_type, target_id, "
            " relation_type, description, source, created_at, updated_at) "
            "SELECT project_id, 'character', from_character_id, 'character', "
            "to_character_id, relation_type, description, 'manual', created_at, updated_at "
            "FROM character_relations"
        )
    )
    conn.execute(text("DROP TABLE character_relations"))
