"""#495 角色关系数据面统一 —— 迁移 helper 契约（ensure_character_relations_merged_into_knowledge）.

RED 状态说明（TDD RED 阶段预期形态）：helper **尚不存在**，本文件顶层的
``from inkflow.core.database import ensure_character_relations_merged_into_knowledge``
在**收集期即 ImportError** → 文件内全部用例以「收集错误」形态 FAIL（等价 RED）。
实现落地（core/database.py 新增 helper + api/app.py lifespan 接线）后转 GREEN。

契约（设计定稿 .hermes/plans/w9d3-design.md §2，签名固定为单个同步 Connection）：

- R1 数据保全迁移：``character_relations`` 行 → ``knowledge_relations``
  （六元组 project_id/'character'/from_character_id/'character'/to_character_id/
  relation_type），``description``/``created_at``/``updated_at`` 保留原值、
  ``source`` 置 'manual'；**INSERT OR IGNORE**——同六元组键已在 kr 表
  （Q1=A 双轨期图谱页建的同行）→ 保留 kr 既有版本；随后 DROP TABLE 删专表
- R2 幂等：迁移后再跑 no-op（表已不在），kr 行数不变
- R3 表不存在（新库/create_all 后已无该表）→ no-op 不抛
- R4 kr 表不存在（防御）→ no-op 不抛，且**不删** character_relations（数据安全优先）
- R5 链上顺序（load-bearing）：``ensure_character_drop_is_deleted`` 先物理清除
  v1.1 前旧库的 is_deleted 软删行，merge 在后 → 软删行不得迁入 kr
- R6 lifespan wiring：新 helper ∈ lifespan **实际调用名集**（AST 提取，禁 substring）

⚠️ 任务书/设计文档 §R1 行数算术自相矛盾：「character_relations 3 行」与「kr 表共
4 行 = 3 迁入 + 1 既有」不能同时成立（3 行中 1 行同键被 IGNORE → 只迁入 2 行）。
本文件按 INSERT OR IGNORE 真实语义取 4 行 character_relations（3 个独立键 + 1 个
与 kr 既有行同键）→ 迁入 3 + 既有 1 = 4 行，与任务书断言的 kr 行数一致；差异已上报。

依据: issue #495 + .hermes/plans/w9d3-design.md §2/§3/§6。
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, text

from inkflow.core.database import (
    ensure_character_drop_is_deleted,
    ensure_character_relations_merged_into_knowledge,
)

# 显式时间戳常量：raw SQL 写入（sqlite3 不能绑定 datetime 对象，写字符串，
# ORM 侧 DateTime 结果处理器再解析回 datetime）
_TS_OLD = "2025-12-31 00:00:00"
_TS_CR = "2026-01-01 00:00:00"

_PROJECTS_DDL = "CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
_CHARACTERS_DDL = (
    "CREATE TABLE characters ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, name TEXT NOT NULL)"
)
_CR_DDL = (
    "CREATE TABLE character_relations ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
    "from_character_id INTEGER NOT NULL, to_character_id INTEGER NOT NULL, "
    "relation_type TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', "
    "created_at DATETIME, updated_at DATETIME)"
)
_KR_DDL = (
    "CREATE TABLE knowledge_relations ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
    "source_type TEXT NOT NULL, source_id INTEGER NOT NULL, "
    "target_type TEXT NOT NULL, target_id INTEGER NOT NULL, "
    "relation_type TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', "
    "source TEXT NOT NULL DEFAULT 'manual', "
    "created_at DATETIME, updated_at DATETIME, "
    "UNIQUE (project_id, source_type, source_id, target_type, target_id, relation_type))"
)


def _tables(conn) -> set[str]:
    """sqlite_master 表名集合."""
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    return {row[0] for row in rows}


def _kr_pair_rows(conn, project_id: int = 1) -> list[tuple]:
    """kr 表 character↔character 子空间行（六元组 + description + source + created_at）."""
    rows = conn.execute(
        text(
            "SELECT source_type, source_id, target_type, target_id, relation_type, "
            "description, source, created_at FROM knowledge_relations "
            "WHERE project_id = :p AND source_type = 'character' AND target_type = 'character'"
        ),
        {"p": project_id},
    ).fetchall()
    return [tuple(row) for row in rows]


def _seed_projects_characters(conn) -> None:
    """projects 1 行 + characters 2 行（迁移链 fixture 保真基线）."""
    conn.execute(text(_PROJECTS_DDL))
    conn.execute(text("INSERT INTO projects (id, name) VALUES (1, '蜀山')"))
    conn.execute(text(_CHARACTERS_DDL))
    conn.execute(
        text("INSERT INTO characters (id, project_id, name) VALUES (1, 1, '玄明'), (2, 1, '宁晚')")
    )


def _seed_legacy_db(conn) -> None:
    """R1 旧库：character_relations 4 行（3 独立键 + 1 与 kr 既有行同键冲突）+ kr 预置 1 行."""
    _seed_projects_characters(conn)
    conn.execute(text(_CR_DDL))
    conn.execute(
        text(
            "INSERT INTO character_relations "
            "(project_id, from_character_id, to_character_id, relation_type, description, "
            " created_at, updated_at) VALUES "
            "(1, 1, 2, '师妹', '同门师妹', :ts, :ts), "
            "(1, 1, 2, '师徒', '授业恩师', :ts, :ts), "
            "(1, 2, 1, '宿敌', '旧怨', :ts, :ts), "
            "(1, 2, 1, '同门', '同门之谊', :ts, :ts)"
        ),
        {"ts": _TS_CR},
    )
    conn.execute(text(_KR_DDL))
    # 双轨期图谱页建的同行（同六元组键 project_id/character/1/character/2/师妹）
    conn.execute(
        text(
            "INSERT INTO knowledge_relations "
            "(project_id, source_type, source_id, target_type, target_id, relation_type, "
            " description, source, created_at, updated_at) "
            "VALUES (1, 'character', 1, 'character', 2, '师妹', '图谱页建的师妹', 'manual', "
            " :ts, :ts)"
        ),
        {"ts": _TS_OLD},
    )


def test_r1_migrates_rows_preserves_data_and_drops_legacy_table() -> None:
    """R1：3 行迁入 + 1 行既有保留（同键 IGNORE）+ 专表删除 + 六元组/description/created_at 正确."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _seed_legacy_db(conn)
        conn.commit()

        ensure_character_relations_merged_into_knowledge(conn)
        conn.commit()

        rows = _kr_pair_rows(conn)
        assert len(rows) == 4, f"应 4 行（3 迁入 + 1 既有），实为 {rows}"

        # 迁入行六元组 + description/时间戳保全
        migrated = {(r[1], r[3], r[4]): r for r in rows}  # (source_id, target_id, type) → 行
        assert migrated[(1, 2, "师徒")] == (
            "character",
            1,
            "character",
            2,
            "师徒",
            "授业恩师",
            "manual",
            _TS_CR,
        )
        assert migrated[(2, 1, "宿敌")][5] == "旧怨"
        assert migrated[(2, 1, "同门")][5] == "同门之谊"

        # 同键冲突行：保留 kr 既有版本（description/created_at 均为 kr 版本，
        # 而非 character_relations 版本）
        conflict = migrated[(1, 2, "师妹")]
        assert conflict[5] == "图谱页建的师妹", "同键冲突行必须保留 kr 既有 description"
        assert conflict[7] == _TS_OLD, "同键冲突行必须保留 kr 既有 created_at"

        assert "character_relations" not in _tables(conn), "数据保全后必须 DROP 专表"


def test_r2_helper_is_idempotent() -> None:
    """R2：R1 迁移后再调 helper → 不抛、kr 行数不变（表已不在 → no-op）."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _seed_legacy_db(conn)
        conn.commit()
        ensure_character_relations_merged_into_knowledge(conn)
        conn.commit()
        before = _kr_pair_rows(conn)

        ensure_character_relations_merged_into_knowledge(conn)  # no-op 不抛
        conn.commit()

        assert len(_kr_pair_rows(conn)) == len(before) == 4


def test_r3_missing_legacy_table_is_noop() -> None:
    """R3：新库（create_all 后已无 character_relations）→ no-op 不抛."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _seed_projects_characters(conn)
        conn.execute(text(_KR_DDL))
        conn.commit()

        ensure_character_relations_merged_into_knowledge(conn)  # no-op 不抛
        conn.commit()

        assert _kr_pair_rows(conn) == []
        assert "character_relations" not in _tables(conn)


def test_r4_missing_knowledge_table_is_noop_without_data_loss() -> None:
    """R4：kr 表不存在（防御路径）→ no-op 不抛，且旧表/行原样保留（不搬就绝不删）."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _seed_projects_characters(conn)
        conn.execute(text(_CR_DDL))
        conn.execute(
            text(
                "INSERT INTO character_relations "
                "(project_id, from_character_id, to_character_id, relation_type, description) "
                "VALUES (1, 1, 2, '师妹', '同门师妹')"
            )
        )
        conn.commit()

        ensure_character_relations_merged_into_knowledge(conn)  # no-op 不抛
        conn.commit()

        assert "character_relations" in _tables(conn), "kr 表缺失时不得删旧表（数据保全）"
        kept = conn.execute(text("SELECT COUNT(*) FROM character_relations")).scalar_one()
        assert int(kept) == 1


def test_r5_soft_deleted_rows_not_migrated_chain_order() -> None:
    """R5：链上顺序契约——先 ensure_character_drop_is_deleted（物理清软删行）再 merge，
    软删行不得迁入 kr（否则旧库 v1.1 前数据会被错误复活）."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        _seed_projects_characters(conn)
        conn.execute(
            text(
                "CREATE TABLE character_relations ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "from_character_id INTEGER NOT NULL, to_character_id INTEGER NOT NULL, "
                "relation_type TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', "
                "created_at DATETIME, updated_at DATETIME, "
                "is_deleted BOOLEAN NOT NULL DEFAULT 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO character_relations "
                "(project_id, from_character_id, to_character_id, relation_type, description, "
                " created_at, updated_at, is_deleted) VALUES "
                "(1, 1, 2, '师妹', '健在关系', :ts, :ts, 0), "
                "(1, 2, 1, '宿敌', '已删关系', :ts, :ts, 1)"
            ),
            {"ts": _TS_CR},
        )
        conn.execute(text(_KR_DDL))
        conn.commit()

        ensure_character_drop_is_deleted(conn)  # 链上前置：清软删行 + 删 is_deleted 列
        ensure_character_relations_merged_into_knowledge(conn)
        conn.commit()

        rows = _kr_pair_rows(conn)
        assert len(rows) == 1, f"软删行不得迁入，实为 {rows}"
        assert rows[0][4] == "师妹" and rows[0][5] == "健在关系"
        assert "character_relations" not in _tables(conn)


def _lifespan_source() -> str:
    """lifespan 源文件文本（AST/顺序断言共用）."""
    spec = importlib.util.find_spec("inkflow.api.app")
    assert spec is not None and spec.origin is not None
    return Path(spec.origin).read_text(encoding="utf-8")


def _lifespan_called_names() -> set[str]:
    """AST 精确提取 lifespan 函数体引用的名字集合（禁 substring 匹配）."""
    tree = ast.parse(_lifespan_source())
    lifespan_node = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
        ),
        None,
    )
    assert lifespan_node is not None, "lifespan 函数未找到（门禁形态失效，非迁移缺陷）"
    names: set[str] = set()
    for node in ast.walk(lifespan_node):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def test_r6_lifespan_wires_merge_helper_after_drop_is_deleted() -> None:
    """R6：新 helper ∈ lifespan 实际调用名集（AST），且接线位置晚于
    ensure_character_drop_is_deleted（链上顺序 load-bearing）."""
    called = _lifespan_called_names()

    # 提取器健全性护栏：今天已接线的邻居必须在集合里（防恒真断言）
    assert "ensure_character_drop_is_deleted" in called, "提取器异常（lifespan 提取为空）"

    assert "ensure_character_relations_merged_into_knowledge" in called, (
        "#495: 新迁移 helper 未接线到 lifespan —— 存量库静默不迁移"
    )

    source = _lifespan_source()
    merge_at = source.index("run_sync(ensure_character_relations_merged_into_knowledge)")
    drop_at = source.index("run_sync(ensure_character_drop_is_deleted)")
    assert merge_at > drop_at, (
        "merge 必须排在 ensure_character_drop_is_deleted 之后（软删行先清除）"
    )
