"""F12 历法换算（0.18.0 / #1589 / ADR-068；契约见 specs/f12-timeline/spec.md §2.10）.

纯领域模块：无 I/O、无框架依赖、确定性（同输入同输出）。

分工（ADR-068 §2.1 S1）:
- **数据契约 + 表达式词法/求值** 在 `domain/models/calendar.py`（`CalendarSpec` 等；
  models 层不得引 services）；
- **换算（累计日数 → 年月日）** 在本模块 —— **唯一实现点**（纪律同 §2.8 E11）；
- 读路径（`TimelineService.get_timeline_view`）调 `resolve_calendar_date` 把结果填进事件
  `calendar_date`，**API 随事件下发纯数据**、前端只选粒度拼文案（粒度是版面问题，不在本层）。

语义:
- ``day_count_to_date`` 把**累计日数**换算为 ``{year, month, day}``（1 基）；
  亚日小数**同日归整**（C1）；
- **未配历法 ⇒ 调用方不调用本模块**（回落「N 日」，D3）；本模块只产数据、不产文案；
- 换算**只做显示层投影**，不回写 ``time_value`` / ``era_value`` / ``era_scale``（D6）。

依据: specs/f12-timeline/spec.md §2.10 · adr/database/ADR-068.md。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from inkflow.domain.models.calendar import CalendarDate, CalendarSpec, evaluate_leap_rule

__all__ = ["day_count_to_date", "resolve_calendar_date", "resolve_day_count"]

# ── 单位 → 日因子（spec §2.7 S2 归一表；`时/时辰` 按 S4 当天时刻、无日锚点时锚点取 0） ──
_UNIT_DAYS: dict[str, float] = {
    "年": 365.0,
    "岁": 365.0,
    "月": 30.0,
    "周": 7.0,
    "星期": 7.0,
    "日": 1.0,
    "天": 1.0,
    "时": 1.0 / 24.0,
    "时辰": 1.0 / 24.0,
}


def _year_length(spec: CalendarSpec, year: int) -> int:
    """年长 = 平年月长和 +（闰年规则命中 ? add_days : 0）（L2）."""
    length = spec.days_per_year
    if spec.leap is not None and evaluate_leap_rule(spec.leap.rule, year):
        length += spec.leap.add_days
    return length


def day_count_to_date(day_count: float, spec: CalendarSpec) -> CalendarDate:
    """累计日数 → ``{year, month, day}``（L1–L4；唯一实现点）.

    Args:
        day_count: 归一日数（**亚日小数同日归整**：内部 ``floor`` —— 同一日内的多个刻度
            得到同一结果）.
        spec: 该轴的历法（未配历法时调用方**不应**调用本函数）.

    Returns:
        ``CalendarDate``（``year`` / ``month`` / ``day`` 均 1 基；``era_cycle`` 生效时
        带 ``cycle``）.

    Note:
        逐年 / 逐月累加：历法年数 < 10⁴ 足够（ADR-068 C3）；更大时改前缀和 / 闭式。
    """
    remaining = math.floor(day_count)
    if remaining < 0:
        remaining = 0

    year = 1
    while remaining >= _year_length(spec, year):
        remaining -= _year_length(spec, year)
        year += 1

    leap_days = _year_length(spec, year) - spec.days_per_year
    leap_month = spec.leap.month if spec.leap is not None and leap_days else 0
    for index, days in enumerate(spec.month_days):
        length = days + (leap_days if index + 1 == leap_month else 0)
        if remaining < length:
            day = remaining + 1
            cycle = None
            cycle_label = None
            if spec.era_cycle is not None:
                cycle = (year - 1) // spec.era_cycle.years + 1
                cycle_label = spec.era_cycle.label
            return CalendarDate(
                year=year,
                month=index + 1,
                day=day,
                cycle=cycle,
                era_cycle_label=cycle_label,
                epoch_label=spec.epoch_label,
            )
        remaining -= length

    # 不可达（循环内必然返回）；保留以防 month_days 为空（已被校验拒绝）
    raise AssertionError("month_days 为空：spec 校验应已拒绝")


def resolve_calendar_date(
    calendars: Sequence[CalendarSpec],
    era: str,
    era_value: float | None,
    time_value: float | None,
    time_unit: str | None,
) -> CalendarDate | None:
    """取该事件的**历法显示日期**（读路径唯一入口；ADR-068 §2.1 S1/S4）.

    Args:
        calendars: 项目级历法清单（`ProjectConfig.calendars`）.
        era: 事件 `era` 值（轴身份，D1）.
        era_value: 纪元轴内值.
        time_value: 全局标量（累计时长）.
        time_unit: `time_value` 的物理尺度.

    Returns:
        ``CalendarDate``；**该轴未配历法 / 时间未知 → None**（调用方回落「N 日」，D3/N1/N8）.
    """
    key = era.strip()
    spec = next((item for item in calendars if item.axis == key), None)
    if spec is None:
        return None
    days = resolve_day_count(era, era_value, time_value, time_unit)
    return None if days is None else day_count_to_date(days, spec)


def resolve_day_count(
    era: str,
    era_value: float | None,
    time_value: float | None,
    time_unit: str | None,
) -> float | None:
    """取「用于换算的日数」——**现行标签的取值来源**（ADR-068 §2.1 S2/S3）.

    Args:
        era: 事件 `era` 值；非空 = 纪元轴.
        era_value: 轴内值.
        time_value: 全局标量（累计时长）.
        time_unit: `time_value` 的物理尺度（§2.7 S2）.

    Returns:
        归一到「日」的数值；输入未知 → None.

    Note:
        ① 纪元轴（`era` 非空）⇒ 取 `era_value`（**该历法自己的「日」尺度**，S3），
        **不看** `time_value` / `time_unit`；
        ② 默认轴 ⇒ `time_value × factor(time_unit)`（S2：年/岁=365、月=30、周/星期=7、日/天=1，
        `时/时辰` = 当天时刻按 S4 无日锚点取 0）；未列举单位 = 时基裸值（因子 1）；
        ③ **本函数不接收 `era_scale`** —— 流速比只影响跨轴纵向定位（D6 / 验收 N7）。
    """
    if era.strip():
        return None if era_value is None else float(era_value)
    if time_value is None:
        return None
    factor = _UNIT_DAYS.get((time_unit or "").strip(), 1.0)
    return float(time_value) * factor
