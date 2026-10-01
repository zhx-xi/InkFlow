"""#1350：foreshadowings.first_chapter_id 结构化列迁移契约（RED→GREEN）。

背景：#1324 让伏笔列表**渲染** location（位置自由文本，原文照显），但「第几章出现」
没有结构保证——存量 94 条 location 形态高度不一（'第1-3章 梦境与觉醒' 是范围；
'开篇梦境及醒来' 无章号；'井边检查陶罐与傍晚补罐' 纯场景），无法稳定解析出单值章号。

#1350 方案 A（本契约）：新增可空结构化列 ``first_chapter_id``（FK ``chapters.id``），
只对**新提取**的伏笔写入；**存量数据零回填**（解析回填 = 伪结构，方案 B 已否决）。

本测试钉住 ``ensure_foreshadowings_first_chapter_id_column`` 四形态：
- 旧库（foreshadowings 存在但无 first_chapter_id + 2 行存量）→ ALTER 补列，
  ⚠️ 且**存量 2 行的 first_chapter_id 必须仍为 NULL**（零回填断言，issue N3）
- 幂等：连续两次调用不抛错、列不重复、存量行不被改写
- 新库（create_all 已含列）→ no-op，列集不变
- 表不存在（全新环境）→ no-op 且不隐式建表

RED 形态：``ensure_foreshadowings_first_chapter_id_column`` 不存在 → 顶部 import
收集期 ImportError（cannot import name，exit 2）。
"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from inkflow.core.database import ensure_foreshadowings_first_chapter_id_column

# 旧库形态：#1350 之前（无 first_chapter_id 列），携带 2 行真实形态存量
# （一条范围文本、一条纯场景文本——正是无法解析回填的证据）。
OLD_SCHEMA = """
CREATE TABLE chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    title VARCHAR(500) NOT NULL
);
CREATE TABLE foreshadowings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    title VARCHAR(100) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 50,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    location VARCHAR(200) NOT NULL DEFAULT '',
    event_id INTEGER,
    resolved_at DATETIME,
    extra JSON NOT NULL DEFAULT '{}',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
INSERT INTO foreshadowings (project_id, title, location, created_at, updated_at)
VALUES
    (1, '伏笔甲', '第1-3章 梦境与觉醒', '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
    (1, '伏笔乙', '井边检查陶罐与傍晚补罐', '2026-01-02 00:00:00', '2026-01-02 00:00:00');
"""

# 新库形态：create_all 已按 ORM 建出带 first_chapter_id 的表。
NEW_SCHEMA = OLD_SCHEMA.replace(
    "    event_id INTEGER,\n",
    "    event_id INTEGER,\n    first_chapter_id INTEGER REFERENCES chapters(id),\n",
)


def _columns(conn, table: str) -> set[str]:
    """PRAGMA table_info 列名集合（镜像既有迁移契约测试助手）。"""
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def _tables(conn) -> set[str]:
    """sqlite_master 全部表名。"""
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    return {row[0] for row in rows}


def test_old_db_adds_column_and_keeps_legacy_rows_null(tmp_path):
    """旧库：补 first_chapter_id 列；存量行保持 NULL（零回填，N3）。"""
    db = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        for stmt in OLD_SCHEMA.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    with engine.connect() as conn:
        assert "first_chapter_id" not in _columns(conn, "foreshadowings")

        ensure_foreshadowings_first_chapter_id_column(conn)
        assert "first_chapter_id" in _columns(conn, "foreshadowings")

        # 零回填：存量 2 行仍为 NULL（不解析 location 文本）
        rows = conn.execute(
            text("SELECT first_chapter_id FROM foreshadowings ORDER BY id")
        ).fetchall()
        assert [r[0] for r in rows] == [None, None]

        # 存量 location 文本原样保留（字段不删，issue 任务 7）
        locs = conn.execute(text("SELECT location FROM foreshadowings ORDER BY id")).fetchall()
        assert [r[0] for r in locs] == ["第1-3章 梦境与觉醒", "井边检查陶罐与傍晚补罐"]
    engine.dispose()


def test_old_db_idempotent_second_call(tmp_path):
    """幂等：连续两次调用不抛错、列不重复、存量行仍 NULL。"""
    db = tmp_path / "idem.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        for stmt in OLD_SCHEMA.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    with engine.connect() as conn:
        ensure_foreshadowings_first_chapter_id_column(conn)
        after_first = _columns(conn, "foreshadowings")
        ensure_foreshadowings_first_chapter_id_column(conn)
        assert _columns(conn, "foreshadowings") == after_first
        rows = conn.execute(text("SELECT first_chapter_id FROM foreshadowings")).fetchall()
        assert [r[0] for r in rows] == [None, None]
    engine.dispose()


def test_new_db_noop(tmp_path):
    """新库：create_all 已含列 → no-op，列集不变。"""
    db = tmp_path / "new.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        for stmt in NEW_SCHEMA.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    with engine.connect() as conn:
        before = _columns(conn, "foreshadowings")
        assert "first_chapter_id" in before

        ensure_foreshadowings_first_chapter_id_column(conn)
        assert _columns(conn, "foreshadowings") == before
    engine.dispose()


def test_missing_table_noop(tmp_path):
    """表不存在（全新环境）→ no-op 不抛错，也不隐式建表（等 create_all）。"""
    db = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        ensure_foreshadowings_first_chapter_id_column(conn)  # 不应抛错
        assert _tables(conn) == set()
    engine.dispose()
