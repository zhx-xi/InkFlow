"""#1409 项目级归一/重锚（`_timeline_timebase`）契约 —— 纯函数 + 与检查算法交叉验证.

契约源: specs/f12-timeline/spec.md §2.7（S1-S8）/§5.7（`timeline normalize`）。

RED 预期: 模块尚不存在 → 各用例体 **lazy import** ImportError（FAILED，而非收集 ERROR）。

GREEN 必实现（`backend/src/inkflow/domain/services/_timeline_timebase.py`，纯领域、无 I/O）:

- ``UNIT_DAYS``: 年/岁=365、月=30、周/星期=7、日/天=1；``CLOCK_UNITS`` = {"时", "时辰"}
- ``to_days(value, unit) -> float | None``：None → None；`时/时辰` → None（需序列上下文）；
  未知/空单位 → 原值（因子 1，§2.7 S5）
- ``normalized_days(events) -> dict[UUID, float | None]``：按**传入顺序**（叙事序）走一遍；
  日级事件 `× factor` 并更新**日锚点**；`时/时辰` = `日锚点 + (value % 24) / 24`（§2.7 S4）
- ``plan_reanchor(events) -> TimebasePlan``（§5.7）：段内计数器 → 项目时基的**单调投影**
  - ``segments``: 识别出的叙事段数；``total_valued``: 带值事件数
  - ``changes``: list[TimebaseChange(event_id, title, time_value, time_unit, new_time_value,
    new_time_unit="日", new_time_display: str | None)]（``new_time_display`` = None 表示不改）
  - ``conflicts_before`` / ``conflicts_after``: 未声明逆序对计数（与 §5.4 同规则）
  - ``projected``: dict[UUID, float] —— 重锚后的归一值（供核对）
  - 算法：按叙事序走**带值且未声明**倒叙/插叙的事件；**数值回落 = 新段**，新段起点接在
    上一段末尾（``offset = prev_global``），段内保留相对天数（``g = offset + (v - 段内最小)``）；
    单位统一「日」；`time_display` 为空时归档原表达式 ``f"{原值}{原单位}"``（§5.7 ⑤）
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.services.timeline_service import TimelineService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000000f9")
TS = datetime(2026, 10, 1, 10, 0, 0)


def _ev(
    title: str,
    *,
    value: float | None,
    unit: str = "日",
    pos: int = 1,
    flag: str = "",
    display: str = "",
) -> TimelineEvent:
    """构造带单位的时间线事件（固定 project/时间戳）."""
    return TimelineEvent(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        time_value=value,
        time_unit=unit,
        time_display=display,
        narrative_position=pos,
        timeline_flag=flag,
        created_at=TS,
        updated_at=TS,
    )


# ─────────────────────────── 单位表 / 单事件换算 ───────────────────────────


def test_unit_factor_table() -> None:
    """S2 单位表：年/岁 365、月 30、周/星期 7、日/天 1；未知/空 = 原值（S5）。"""
    from inkflow.domain.services._timeline_timebase import to_days

    assert to_days(1.0, "年") == 365.0
    assert to_days(2.0, "岁") == 730.0
    assert to_days(3.0, "月") == 90.0
    assert to_days(2.0, "周") == 14.0
    assert to_days(2.0, "星期") == 14.0
    assert to_days(8.0, "日") == 8.0
    assert to_days(8.0, "天") == 8.0
    assert to_days(8.0, "") == 8.0  # 空单位 → 因子 1（反例守护 S5）
    assert to_days(8.0, "纪元") == 8.0  # 未列举 → 因子 1
    assert to_days(None, "日") is None


def test_to_days_clock_units_need_sequence_context() -> None:
    """S4：「时/时辰」不是累计量 → `to_days` 返回 None（锚定需序列上下文）。"""
    from inkflow.domain.services._timeline_timebase import to_days

    assert to_days(3.0, "时") is None
    assert to_days(3.0, "时辰") is None


def test_normalized_days_anchors_clock_to_previous_day() -> None:
    """S2/S4 归一：`[8 日, 3 时, 9 日]` → `{8.0, 8 + 3/24 = 8.125, 9.0}`。"""
    from inkflow.domain.services._timeline_timebase import normalized_days

    events = [
        _ev("第八日", value=8.0, unit="日", pos=1),
        _ev("辰时", value=3.0, unit="时", pos=2),
        _ev("第九日", value=9.0, unit="日", pos=3),
    ]
    keys = normalized_days(events)
    assert keys[events[0].id] == 8.0
    assert keys[events[1].id] == pytest.approx(8.0 + 3.0 / 24.0)
    assert keys[events[2].id] == 9.0


def test_normalized_days_clock_without_anchor_defaults_zero() -> None:
    """S4：无前置日级事件 → 日锚点取 0（归一值 ∈ [0, 1)）。"""
    from inkflow.domain.services._timeline_timebase import normalized_days

    events = [_ev("辰时", value=3.0, unit="时", pos=1), _ev("午时", value=5.0, unit="时", pos=2)]
    keys = normalized_days(events)
    assert keys[events[0].id] == pytest.approx(3.0 / 24.0)
    assert keys[events[1].id] == pytest.approx(5.0 / 24.0)


def test_normalized_days_skips_none_and_keeps_anchor() -> None:
    """S9：`time_value = None` 不参与、不影响锚点；单位混合时锚点取归一后日值。"""
    from inkflow.domain.services._timeline_timebase import normalized_days

    events = [
        _ev("一月", value=1.0, unit="月", pos=1),  # 锚点 → 30.0
        _ev("时间未知", value=None, unit="", pos=2),  # 不更新锚点
        _ev("卯时", value=3.0, unit="时", pos=3),  # 30 + 0.125
    ]
    keys = normalized_days(events)
    assert keys[events[0].id] == 30.0
    assert keys[events[1].id] is None
    assert keys[events[2].id] == pytest.approx(30.0 + 3.0 / 24.0)


# ─────────────────────────── 重锚计划 ───────────────────────────


def test_reanchor_chains_segments_and_keeps_intra_segment_delta() -> None:
    """§5.7 段续接：回落 = 新段；新段起点接上一段末尾；**段内相对天数保留**。

    `[1, 8] → [3, 5, 7, 7.99]`（全是「日」）：
      段1 = [1, 8]（不变）；段2 起点接 8 → [8, 10, 12, 12.99]
      ⇒ 段内差保留：(5-3)=2 → (10-8)=2；(7.99-3)=4.99 → (12.99-8)=4.99
      ⇒ 投影序列非降：1, 8, 8, 10, 12, 12.99
    """
    from inkflow.domain.services._timeline_timebase import plan_reanchor

    events = [
        _ev("一", value=1.0, pos=1),
        _ev("八", value=8.0, pos=2),
        _ev("三", value=3.0, pos=3),
        _ev("五", value=5.0, pos=4),
        _ev("七", value=7.0, pos=5),
        _ev("七点九九", value=7.99, pos=6),
    ]
    plan = plan_reanchor(events)
    assert plan.segments == 2
    assert plan.total_valued == 6
    assert plan.projected[events[0].id] == pytest.approx(1.0)
    assert plan.projected[events[1].id] == pytest.approx(8.0)
    assert plan.projected[events[2].id] == pytest.approx(8.0)
    assert plan.projected[events[3].id] == pytest.approx(10.0)
    assert plan.projected[events[4].id] == pytest.approx(12.0)
    assert plan.projected[events[5].id] == pytest.approx(12.99)
    # 前两条（段1）无改动 → 只在 changes 里出现真正改写的 4 条
    assert {c.event_id for c in plan.changes} == {e.id for e in events[2:]}
    assert plan.conflicts_after == 0


def test_reanchor_unifies_unit_to_days_and_archives_display() -> None:
    """§5.7 ④⑤：单位统一写「日」；`time_display` 为空 → 归档原表达式。"""
    from inkflow.domain.services._timeline_timebase import plan_reanchor

    events = [
        _ev("第三月", value=3.0, unit="月", pos=1),
        _ev("第二日", value=2.0, unit="日", pos=2),
    ]
    plan = plan_reanchor(events)
    change = next(c for c in plan.changes if c.event_id == events[0].id)
    assert change.time_value == 3.0  # 原值保留在 change 里（供报告/审计）
    assert change.time_unit == "月"
    assert change.new_time_value == pytest.approx(90.0)
    assert change.new_time_unit == "日"
    assert change.new_time_display == "3.0月"  # 原表达式归档（display 原为空）
    # 已有 display 的事件不改 display
    kept = _ev("有表达", value=1.0, unit="月", pos=3, display="青元历三月")
    plan2 = plan_reanchor([_ev("甲", value=5.0, pos=1), kept])
    c2 = next(c for c in plan2.changes if c.event_id == kept.id)
    assert c2.new_time_display is None


def test_reanchor_exempts_declared_flags() -> None:
    """§5.7 豁免：**任一** `timeline_flag` 非空（已声明倒叙/插叙）的事件完全不改、不触发分段。"""
    from inkflow.domain.services._timeline_timebase import plan_reanchor

    events = [
        _ev("甲", value=1.0, pos=1),
        _ev("八", value=8.0, pos=2),
        _ev("回忆", value=2.0, pos=3, flag="倒叙"),  # 回落但已声明 → 不触发新段、不入 changes
        _ev("九", value=9.0, pos=4),
    ]
    plan = plan_reanchor(events)
    assert plan.segments == 1
    assert all(c.title != "回忆" for c in plan.changes)
    assert events[2].id not in plan.projected  # 豁免事件不参与投影
    assert plan.projected[events[3].id] == pytest.approx(9.0)


def test_reanchor_skips_none_values() -> None:
    """§5.7 边界：`time_value = None` 不入 changes、不入 projected；空/单条输入不报错。"""
    from inkflow.domain.services._timeline_timebase import plan_reanchor

    events = [
        _ev("未知", value=None, unit="", pos=1),
        _ev("甲", value=4.0, pos=2),
        _ev("乙", value=2.0, pos=3),  # 回落 → 新段（起点接 4）
    ]
    plan = plan_reanchor(events)
    assert plan.total_valued == 2
    assert events[0].id not in plan.projected
    assert {c.event_id for c in plan.changes} == {events[2].id}
    assert plan.projected[events[2].id] == pytest.approx(4.0)

    empty = plan_reanchor([])
    assert empty.segments == 0
    assert empty.changes == []
    assert empty.total_valued == 0
    assert empty.conflicts_before == 0
    assert empty.conflicts_after == 0

    only_none = plan_reanchor([_ev("未知", value=None, unit="", pos=1)])
    assert only_none.segments == 0
    assert only_none.changes == []


def test_reanchor_is_idempotent() -> None:
    """S8：对**已归一**（非降）序列再跑重锚 → `changes == []`（幂等，可安全重复 --apply）。"""
    from inkflow.domain.services._timeline_timebase import plan_reanchor

    legacy = [
        _ev("一", value=1.0, pos=1),
        _ev("八", value=8.0, pos=2),
        _ev("三", value=3.0, pos=3),
        _ev("五", value=5.0, pos=4),
    ]
    first = plan_reanchor(legacy)
    # 把投影结果当作新数据再跑一遍（模拟重复执行）
    rewritten = [
        _ev(
            e.title,
            value=first.projected[e.id],
            unit="日",
            pos=e.narrative_position,
            flag=e.timeline_flag,
        )
        for e in legacy
        if e.id in first.projected
    ]
    second = plan_reanchor(rewritten)
    assert second.changes == []
    assert second.segments == 1
    assert second.conflicts_before == 0
    assert second.conflicts_after == 0


def test_plan_conflict_counting_exempts_declared_flashforward() -> None:
    """§5.4 计数口径（覆盖补强）：prev 声明「插叙」的逆序对**不计**入 conflicts。

    与检查层同规则（`has_flag(prev, *FLASHFORWARD_WORDS)`）—— 防两处口径漂移；
    同时确认已声明事件被豁免重锚、且后续事件本身无需改写（无可改项）。
    """
    from inkflow.domain.services._timeline_timebase import plan_reanchor

    events = [
        _ev("未来插叙", value=10.0, pos=1, flag="插叙"),
        _ev("回到现在", value=5.0, pos=2),
    ]
    plan = plan_reanchor(events)
    assert plan.total_valued == 2
    assert plan.conflicts_before == 0  # prev 已声明插叙 → 合法，不计冲突
    assert plan.conflicts_after == 0
    assert plan.changes == []  # 已声明事件豁免；后叙事件值/单位均无需改写


def test_reanchor_monotone_input_is_noop() -> None:
    """§5.7 边界：单段单调序列 → `segments=1, changed=0`（工具对健康数据无副作用）。"""
    from inkflow.domain.services._timeline_timebase import plan_reanchor

    plan = plan_reanchor(
        [_ev("甲", value=1.0, pos=1), _ev("乙", value=2.0, pos=2), _ev("丙", value=3.0, pos=3)]
    )
    assert plan.segments == 1
    assert plan.changes == []
    assert plan.conflicts_before == 0


# ─────────────────────────── 与检查算法交叉验证（防漂移） ───────────────────────────


class _FakeRepo:
    """内存仓储（镜像 test_timeline_check.FakeTimelineRepo 的 list_all 契约）."""

    def __init__(self, events: list[TimelineEvent]) -> None:
        self._events = list(events)

    async def list_all(self, project_id: uuid.UUID) -> list[TimelineEvent]:
        events = [e for e in self._events if e.project_id == project_id]
        return sorted(events, key=lambda e: (e.narrative_position, e.created_at))


class _FakeProjectRepo:
    async def get(self, project_id: uuid.UUID) -> object:
        return object()


@pytest.mark.asyncio
async def test_plan_conflicts_before_matches_check_and_after_is_zero() -> None:
    """交叉验证（防规则漂移）：`plan.conflicts_before` == `check_consistency().conflicts` 条数，
    且重锚后 `conflicts_after == 0`（§5.7 单调投影性质）。

    序列：`[1日, 8日, 3日, 5日]` —— 裸值 1 条逆序（8>3）；
    归一后仍 1 条（同单位）；重锚后续接为 `[1, 8, 8, 10]` → 0 条。
    """
    from inkflow.domain.services._timeline_timebase import plan_reanchor

    events = [
        _ev("一", value=1.0, pos=1),
        _ev("八", value=8.0, pos=2),
        _ev("三", value=3.0, pos=3),
        _ev("五", value=5.0, pos=4),
    ]
    service = TimelineService(repository=_FakeRepo(events), project_repo=_FakeProjectRepo())
    report = await service.check_consistency(PID)
    assert report is not None

    plan = plan_reanchor(events)
    assert plan.conflicts_before == len(report.conflicts) == 1
    assert plan.conflicts_after == 0


@pytest.mark.asyncio
async def test_cross_unit_only_false_positive_is_not_removed_silently() -> None:
    """交叉验证：纯跨单位相邻（`8 日` → `3 月`）在**检查层**就不该报冲突（归一已在判定层生效），
    因此重锚的 `conflicts_before` 也应为 0（两处口径一致：不得一边报一边不报）。"""
    from inkflow.domain.services._timeline_timebase import plan_reanchor

    events = [
        _ev("第八日", value=8.0, unit="日", pos=1),
        _ev("第三月", value=3.0, unit="月", pos=2),
    ]
    service = TimelineService(repository=_FakeRepo(events), project_repo=_FakeProjectRepo())
    report = await service.check_consistency(PID)
    assert report is not None
    assert report.conflicts == []

    plan = plan_reanchor(events)
    assert plan.conflicts_before == 0
    assert plan.conflicts_after == 0
