"""#1323：时间线叙事序合成序回填迁移（幂等 + 可回滚）契约测试。

【缺陷（G4）】提取器曾把 LLM 的**章内序**原样落库 → 跨章碰撞
（issue 实测：215 条事件只有 34 个不同 position 值，1/6/7 各对应 10 条）。

【本批契约】
1. 回填后 `narrative_position` 在**项目内全局严格递增且两两不同**（跨章碰撞归零）。
2. **章内相对先后保持不变**（纯重编号，不改业务字段）。
3. 幂等：二次运行不改任何值、不覆盖快照。
4. 可回滚：`rollback_timeline_composite_positions` 精确恢复迁移前原值。
5. 全新环境（无表）→ no-op 不崩。

用真实 SQLite（同 SQLAlchemy 引擎）而非 mock —— 迁移语义只能靠真库验证。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from inkflow.core.migrations_timeline_position import (
    BACKUP_TABLE,
    ensure_timeline_composite_positions,
    rollback_timeline_composite_positions,
)

PID_A = "0192f000-0000-7000-8000-0000000000a0"
PID_B = "0192f000-0000-7000-8000-0000000000b0"
CH_1 = "0192f000-0000-7000-8000-0000000000c1"
CH_2 = "0192f000-0000-7000-8000-0000000000c2"


def _make_engine() -> Engine:
    """建一个带 timeline_events 的最小真库（只含迁移用到的列）。"""
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE timeline_events ("
                "  id INTEGER PRIMARY KEY,"
                "  project_id TEXT NOT NULL,"
                "  source_chapter_id TEXT,"
                "  narrative_position INTEGER NOT NULL)"
            )
        )
    return eng


def _seed(eng: Engine, rows: list[tuple[int, str, str | None, int]]) -> None:
    with eng.begin() as conn:
        for r in rows:
            conn.execute(
                text(
                    "INSERT INTO timeline_events "
                    "(id, project_id, source_chapter_id, narrative_position) "
                    "VALUES (:i, :p, :c, :n)"
                ),
                {"i": r[0], "p": r[1], "c": r[2], "n": r[3]},
            )


def _dump(eng: Engine) -> dict[int, int]:
    with eng.begin() as conn:
        return {
            row[0]: row[1]
            for row in conn.execute(
                text("SELECT id, narrative_position FROM timeline_events ORDER BY id")
            ).fetchall()
        }


def _dump_chapters(eng: Engine) -> dict[int, str | None]:
    with eng.begin() as conn:
        return {
            row[0]: row[1]
            for row in conn.execute(
                text("SELECT id, source_chapter_id FROM timeline_events ORDER BY id")
            ).fetchall()
        }


class TestTimelineCompositeBackfill:
    """#1323 G4：既有数据重排为合成序。"""

    def test_cross_chapter_collision_removed(self) -> None:
        """两章各自从 1 编号（碰撞）→ 迁移后全项目两两不同。"""
        eng = _make_engine()
        # 章1: pos 1,2 ；章2: pos 1,2,3  → 原来 1/2 各撞 2 次
        _seed(
            eng,
            [
                (1, PID_A, CH_1, 1),
                (2, PID_A, CH_1, 2),
                (3, PID_A, CH_2, 1),
                (4, PID_A, CH_2, 2),
                (5, PID_A, CH_2, 3),
            ],
        )
        with eng.begin() as conn:
            ensure_timeline_composite_positions(conn)

        positions = list(_dump(eng).values())
        assert len(positions) == len(set(positions)), f"仍有碰撞: {positions}"
        assert sorted(positions) == [1, 2, 3, 4, 5]

    def test_intra_chapter_relative_order_preserved(self) -> None:
        """章内相对先后必须保持不变（纯重编号）。"""
        eng = _make_engine()
        # 章1 章内序 2,1,3（乱序输入）→ 迁移后 id2 < id1 < id3
        _seed(
            eng,
            [(1, PID_A, CH_1, 2), (2, PID_A, CH_1, 1), (3, PID_A, CH_1, 3)],
        )
        with eng.begin() as conn:
            ensure_timeline_composite_positions(conn)

        got = _dump(eng)
        assert got[2] < got[1] < got[3], got

    def test_project_isolation(self) -> None:
        """不同项目各自独立编号（互不影响）。"""
        eng = _make_engine()
        _seed(
            eng,
            [
                (1, PID_A, CH_1, 5),
                (2, PID_A, CH_1, 9),
                (3, PID_B, CH_1, 1),
                (4, PID_B, CH_2, 1),
            ],
        )
        with eng.begin() as conn:
            ensure_timeline_composite_positions(conn)

        got = _dump(eng)
        assert sorted([got[1], got[2]]) == [1, 2]
        assert sorted([got[3], got[4]]) == [1, 2]

    def test_null_chapter_events_grouped_together(self) -> None:
        """未归章事件（source_chapter_id NULL）归入同一组，不消失、不碰撞。"""
        eng = _make_engine()
        _seed(
            eng,
            [
                (1, PID_A, None, 3),
                (2, PID_A, None, 1),
                (3, PID_A, CH_1, 1),
            ],
        )
        with eng.begin() as conn:
            ensure_timeline_composite_positions(conn)

        positions = list(_dump(eng).values())
        assert len(positions) == len(set(positions)), positions
        got = _dump(eng)
        assert got[2] < got[1]  # NULL 组内按原 position 升序

    def test_chapter_field_untouched(self) -> None:
        """业务字段（source_chapter_id）必须原样不变。"""
        eng = _make_engine()
        rows = [(1, PID_A, CH_1, 1), (2, PID_A, CH_2, 1)]
        _seed(eng, rows)
        before = _dump_chapters(eng)
        with eng.begin() as conn:
            ensure_timeline_composite_positions(conn)
        assert _dump_chapters(eng) == before


class TestIdempotencyAndRollback:
    """#1323：幂等 + 可回滚（S10 要求回滚可行）。"""

    def test_second_run_is_noop(self) -> None:
        """二次运行：值不变（幂等），且不覆盖原始快照。"""
        eng = _make_engine()
        _seed(eng, [(1, PID_A, CH_1, 7), (2, PID_A, CH_2, 7)])
        with eng.begin() as conn:
            ensure_timeline_composite_positions(conn)
        after_first = _dump(eng)

        with eng.begin() as conn:
            ensure_timeline_composite_positions(conn)
        assert _dump(eng) == after_first, "二次运行改动了值（不幂等）"

        # 原始快照仍是迁移前的 7/7（未被已迁移值覆盖）
        with eng.begin() as conn:
            snap = dict(
                conn.execute(
                    text(f"SELECT event_id, narrative_position FROM {BACKUP_TABLE}")
                ).fetchall()
            )
        assert snap == {1: 7, 2: 7}, f"原始快照被覆盖: {snap}"

    def test_rollback_restores_original_values(self) -> None:
        """回滚精确恢复迁移前原值。"""
        eng = _make_engine()
        original = {1: 7, 2: 7, 3: 2}
        _seed(
            eng,
            [
                (1, PID_A, CH_1, 7),
                (2, PID_A, CH_2, 7),
                (3, PID_A, CH_2, 2),
            ],
        )
        with eng.begin() as conn:
            ensure_timeline_composite_positions(conn)
        assert _dump(eng) != original, "迁移未生效，回滚测试无意义"

        with eng.begin() as conn:
            restored = rollback_timeline_composite_positions(conn)
        assert _dump(eng) == original, f"回滚不精确: {_dump(eng)}"
        assert restored == 3

    def test_rollback_without_backup_is_safe(self) -> None:
        """无快照表（未迁移）→ 回滚返回 0，不崩。"""
        eng = _make_engine()
        _seed(eng, [(1, PID_A, CH_1, 1)])
        with eng.begin() as conn:
            assert rollback_timeline_composite_positions(conn) == 0

    def test_rollback_then_remigrate(self) -> None:
        """回滚后可再次迁移（标记被清）→ 结果与首次一致。"""
        eng = _make_engine()
        _seed(eng, [(1, PID_A, CH_1, 4), (2, PID_A, CH_2, 4)])
        with eng.begin() as conn:
            ensure_timeline_composite_positions(conn)
        first = _dump(eng)
        with eng.begin() as conn:
            rollback_timeline_composite_positions(conn)
        with eng.begin() as conn:
            ensure_timeline_composite_positions(conn)
        assert _dump(eng) == first

    def test_missing_table_is_noop(self) -> None:
        """全新环境（无 timeline_events 表）→ no-op 不崩。"""
        eng = create_engine("sqlite://")
        with eng.begin() as conn:
            ensure_timeline_composite_positions(conn)  # 不应抛异常

    def test_empty_table_marks_done(self) -> None:
        """空表迁移后打标记（避免每次启动重复扫表）。"""
        eng = _make_engine()
        with eng.begin() as conn:
            ensure_timeline_composite_positions(conn)
        with eng.begin() as conn:
            mark = conn.execute(
                text("SELECT value FROM migration_markers WHERE key = :k"),
                {"k": "timeline_composite_backfill_1323"},
            ).fetchone()
        assert mark is not None


def test_migration_module_exposes_expected_symbols() -> None:
    """接口面冻结：迁移入口 + 回滚入口 + 快照表名。"""
    assert callable(ensure_timeline_composite_positions)
    assert callable(rollback_timeline_composite_positions)
    assert BACKUP_TABLE == "timeline_position_backup_1323"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
