"""#1410 多纪元正式化 — 迁移契约（三形态 / 幂等 / 回填 / 接线门禁）。

【规格依据】specs/f12-timeline/spec.md §2.1（三列）+ §2.8 E7/E9（v1.4）+ ADR-065 §4。

【本契约钉住五件事】
1. 三列 ``era`` / ``era_value`` / ``era_scale`` 落 ``timeline_events``：
   空库由 ``create_all`` 建（ORM 已含），旧库由 ``ensure_timeline_era_columns`` 补
2. 迁移**幂等**：表不存在 → no-op / 有表缺列 → 补齐 / 有表有列 → no-op；
   连续两次调用不报错、不重复写
3. **存量回填**：``extra.era`` / ``extra.era_value`` 一次性投影进正式列；
   ``era_scale`` 由 ``ADD COLUMN ... DEFAULT 1.0`` 对既有行填充
4. **不覆盖**：正式列已有值时不被 ``extra`` 旧值覆盖（回填只对空列生效 + 一次性 marker）
5. **接线门禁**：``lifespan`` 实际调用 ``ensure_timeline_era_columns``
   （AST 精确提取，禁 substring —— ``ensure_timeline_era`` 是 ``ensure_timeline_era_columns``
   的前缀子串，文本包含判断会假绿）

【RED 预期】``inkflow.core.migrations_timeline_era`` 尚不存在 →
收集期 ``ModuleNotFoundError``（预期 RED 形态，非 SyntaxError）；GREEN 后逐条断言。
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text

import inkflow.infrastructure.database.models  # noqa: F401  # Base.metadata 注册
from inkflow.core import database as db_module
from inkflow.core.migrations_timeline_era import ensure_timeline_era_columns

# ⚠️ 接线门禁**只读源码路径、不导入 app**：父包 ``inkflow.api.__init__`` 会
# ``from inkflow.api.app import app``，任何触发该导入的手法（``find_spec`` 或
# ``import_module``）都会把「本文件能否 collect」绑到 app 的完整导入链上 ——
# 在 ``--cov=<单模块>`` 等非常规导入顺序下会与 coverage/pydantic 交互而炸
# （实测：AttributeError / KeyError: 'pydantic.root_model'）。纯文件读取 + AST
# 与导入状态完全解耦，门禁语义不变（提取 lifespan 函数体引用的名字）。
_APP_SOURCE = Path(__file__).resolve().parents[3] / "src" / "inkflow" / "api" / "app.py"

ERA_COLUMNS = {"era", "era_value", "era_scale"}

_WIRED_NAME = "ensure_timeline_era_columns"


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def _tables(conn) -> set[str]:
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    return {row[0] for row in rows}


def _legacy_table(conn) -> None:
    """建 v1.3 形态「有表缺列」：``timeline_events`` 无三列，纪元由 ``extra`` 承载。"""
    conn.execute(
        text(
            "CREATE TABLE timeline_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "project_id INTEGER NOT NULL, "
            "title TEXT NOT NULL, "
            "extra TEXT NOT NULL DEFAULT '{}')"
        )
    )
    conn.execute(
        text("INSERT INTO timeline_events (project_id, title, extra) VALUES (1, '事件甲', :e)"),
        {"e": '{"era": "示例历", "era_value": 317.5}'},
    )
    conn.execute(
        text("INSERT INTO timeline_events (project_id, title, extra) VALUES (1, '事件乙', '{}')")
    )
    conn.execute(
        text("INSERT INTO timeline_events (project_id, title, extra) VALUES (1, '事件丙', :e)"),
        {"e": '{"tags": ["甲"]}'},  # 有 extra 但无纪元键
    )


def _orm_insert(conn, **values: object) -> None:
    """经 ORM 表对象插入（SQLAlchemy 会填 Python 侧 default，raw SQL 不会）。"""
    from inkflow.infrastructure.database.models.timeline import TimelineEventORM

    conn.execute(TimelineEventORM.__table__.insert().values(**values))


# ── 形态 1：空库（表不存在）→ no-op（不建表、不抛） ──


def test_missing_table_is_noop(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with engine.begin() as conn:
        ensure_timeline_era_columns(conn)
        tables = _tables(conn)
    assert "timeline_events" not in tables


# ── 形态 2：空库启动（create_all）→ 三列存在（ORM 已含） ──


def test_create_all_includes_three_columns(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    with engine.begin() as conn:
        db_module.Base.metadata.create_all(conn)
        cols = _columns(conn, "timeline_events")
    assert cols >= ERA_COLUMNS, f"缺列: {ERA_COLUMNS - cols}"


# ── 形态 3：有表缺列 → 补列 + 既有行零丢失 + 存量回填 ──


def test_legacy_table_adds_columns_backfills_and_preserves_rows(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        _legacy_table(conn)
        before = conn.execute(text("SELECT COUNT(*) FROM timeline_events")).fetchone()
        assert before is not None
        ensure_timeline_era_columns(conn)

        cols = _columns(conn, "timeline_events")
        assert cols >= ERA_COLUMNS, f"缺列: {ERA_COLUMNS - cols}"

        after = conn.execute(text("SELECT COUNT(*) FROM timeline_events")).fetchone()
        assert after is not None and int(after[0]) == int(before[0]) == 3  # 零丢失

        # 存量回填：extra.era / extra.era_value → 正式列；era_scale 默认 1.0
        row_a = conn.execute(
            text("SELECT era, era_value, era_scale FROM timeline_events WHERE title='事件甲'")
        ).fetchone()
        assert row_a is not None and tuple(row_a) == ("示例历", 317.5, 1.0)

        row_b = conn.execute(
            text("SELECT era, era_value, era_scale FROM timeline_events WHERE title='事件乙'")
        ).fetchone()
        assert row_b is not None and tuple(row_b) == ("", None, 1.0)  # 默认轴

        row_c = conn.execute(
            text("SELECT era, era_value, era_scale FROM timeline_events WHERE title='事件丙'")
        ).fetchone()
        assert row_c is not None and tuple(row_c) == ("", None, 1.0)  # 无纪元键 → 默认轴


# ── 幂等：连续两次不报错、不重复写（含「回填后旧快照不再影响正式列」） ──


def test_idempotent_second_run_does_not_rewrite(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'idem.db'}")
    with engine.begin() as conn:
        _legacy_table(conn)
        ensure_timeline_era_columns(conn)
        # 人为把 extra 改成另一个轴（模拟遗留快照后续变化）
        conn.execute(
            text("UPDATE timeline_events SET extra = :e WHERE title='事件甲'"),
            {"e": '{"era": "另一个轴", "era_value": 999}'},
        )
        ensure_timeline_era_columns(conn)  # 第二次：不报错、不回写

        row = conn.execute(
            text("SELECT era, era_value, era_scale FROM timeline_events WHERE title='事件甲'")
        ).fetchone()
        assert row is not None and tuple(row) == ("示例历", 317.5, 1.0)  # 保持首次结果

        count = conn.execute(text("SELECT COUNT(*) FROM timeline_events")).fetchone()
        assert count is not None and int(count[0]) == 3


# ── 形态 3b：有表有列（新形态）→ no-op，不破坏既有正式列值 ──


def test_table_with_columns_keeps_existing_values(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    with engine.begin() as conn:
        db_module.Base.metadata.create_all(conn)
        _orm_insert(
            conn,
            project_id=1,
            title="事件甲",
            era="仙界纪年",
            era_value=5.0,
            era_scale=2.0,
            uuid=str(uuid.uuid4()),
        )
        ensure_timeline_era_columns(conn)  # 有列 → no-op
        row = conn.execute(
            text("SELECT era, era_value, era_scale FROM timeline_events WHERE title='事件甲'")
        ).fetchone()
        assert row is not None and tuple(row) == ("仙界纪年", 5.0, 2.0)


# ── 接线门禁（AST 精确提取，禁 substring） ──


def _lifespan_called_names() -> set[str]:
    assert _APP_SOURCE.exists(), f"app.py 未找到: {_APP_SOURCE}（门禁形态失效，非迁移缺陷）"
    source = _APP_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
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


def test_migration_is_wired_into_lifespan() -> None:
    """迁移助手必须被 lifespan 接线（新迁移忘接 = 存量库静默不迁移）。"""
    assert _WIRED_NAME in _lifespan_called_names(), (
        f"lifespan 未接线 {_WIRED_NAME}（AST 提取，非 substring）"
    )


def test_wired_helper_is_importable_from_sibling_module() -> None:
    """helper 落在 sibling 模块（core/database.py 已顶 900 行护栏，不 re-export）。"""
    assert ensure_timeline_era_columns.__module__ == "inkflow.core.migrations_timeline_era"


# ── 回归守护：迁移不改 ``time_value`` / ``time_unit``（§2.7 S1-S10 不变） ──


def test_migration_does_not_touch_time_value_semantics(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'tv.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE timeline_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "title TEXT NOT NULL, time_value FLOAT, time_unit TEXT NOT NULL DEFAULT '', "
                "extra TEXT NOT NULL DEFAULT '{}')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO timeline_events (project_id, title, time_value, time_unit, extra) "
                "VALUES (1, '事件甲', 186.0, '日', :e)"
            ),
            {"e": '{"era": "示例历", "era_value": 317.5}'},
        )
        ensure_timeline_era_columns(conn)
        row = conn.execute(
            text("SELECT time_value, time_unit FROM timeline_events WHERE title='事件甲'")
        ).fetchone()
        assert row is not None and tuple(row) == (186.0, "日")


# ── 容错：脏 extra（非法 JSON / 非对象 / 非字符串轴名 / 非数值轴内值）不崩、不回填 ──


def test_backfill_tolerates_dirty_extra(tmp_path: Path) -> None:
    """迁移面对历史脏数据必须稳健：解析失败按「无纪元」处理，绝不写入垃圾。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'dirty.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE timeline_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, "
                "title TEXT NOT NULL, extra TEXT NOT NULL DEFAULT '{}')"
            )
        )
        cases = {
            "坏 JSON": "{not json",
            "空串": "",
            "非对象": "[1, 2]",
            "轴名非字符串": '{"era": 123, "era_value": 5}',
            "轴名空白": '{"era": "   "}',
            "值非数值": '{"era": "示例历", "era_value": "317"}',
            "值布尔": '{"era": "示例历", "era_value": true}',
            "值非有限": '{"era": "示例历", "era_value": 1e400}',
        }
        for title, raw in cases.items():
            conn.execute(
                text("INSERT INTO timeline_events (project_id, title, extra) VALUES (1, :t, :e)"),
                {"t": title, "e": raw},
            )
        ensure_timeline_era_columns(conn)

        got = {
            title: (era, value)
            for title, era, value in conn.execute(
                text("SELECT title, era, era_value FROM timeline_events")
            ).fetchall()
        }
        for bad_only in ("坏 JSON", "空串", "非对象", "轴名非字符串", "轴名空白"):
            assert got[bad_only] == ("", None), bad_only
        for name_only in ("值非数值", "值布尔", "值非有限"):
            assert got[name_only] == ("示例历", None), name_only
