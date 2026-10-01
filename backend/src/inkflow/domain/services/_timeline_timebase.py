"""F12 时间归属归一/重锚纯函数（#1409 spec §2.7 / §5.7）.

纯领域模块：无 I/O、无框架依赖、确定性（同输入同输出，§2.7 S8）。被
`timeline_service`（判定层只读归一）与 `inkflow timeline normalize`
CLI（数据层显式重锚）共用——「单位表 / 倒叙词表 / 归一算法」只允许有这一份真相。

核心语义（spec §2.7）:
- `time_value` = **相对项目时基的累计时长**，物理尺度由 `time_unit` 给定；
- 比较/排序前必须按单位归一到「日」（年/岁=365、月=30、周/星期=7、日/天=1）；
- `时 / 时辰` 是**当天时刻**而非累计量 → 锚定叙事序上最近的日锚点；
- 未知/空单位 = 时基裸值（因子 1，向后兼容，§2.7 S5）。

依据: specs/f12-timeline/spec.md §2.7（S1-S10）/§5.3/§5.4/§5.7。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import cast

from inkflow.domain.models.timeline import TimelineEvent

UNIT_DAYS: dict[str, float] = {
    "年": 365.0,
    "岁": 365.0,
    "月": 30.0,
    "周": 7.0,
    "星期": 7.0,
    "日": 1.0,
    "天": 1.0,
}
"""单位换算表（§2.7 S2）：年/岁=365 日、月=30 日、周/星期=7 日、日/天=1 日."""

CLOCK_UNITS = frozenset({"时", "时辰"})
"""当天时刻单位（§2.7 S4）——不是累计量，锚定需日锚点上下文."""

FLASHBACK_WORDS = ("flashback", "倒叙", "回忆")
"""倒叙语义词表（#1323：prompt 枚举 + 中文自由文本兼容）."""

FLASHFORWARD_WORDS = ("flashforward", "插叙", "预叙")
"""插叙/预叙语义词表（#1323：prompt 枚举 + 中文自由文本兼容）."""

_EPS = 1e-9
"""重锚改写的浮点容差（§2.7 S8：避免无意义改写破坏幂等）."""


def has_flag(flag: str | None, *needles: str) -> bool:
    """#1323 G6：``timeline_flag`` 是**自由文本**，用包含式匹配判定语义。

    真实数据为中文自由文本（DB 实测：``''=181, 倒叙=29, 插叙=3, 梦境=1, 回忆=1``），
    此前用字面量等值比较（``== "flashback"``）→ 33 条已声明倒叙/插叙被当作「未标记」，
    直接产 ``order_conflict``（error 级 finding）串到审计报告。

    包含式匹配对既有英文值零破坏（``flashback`` 含 ``flashback``），
    且能覆盖带修饰的自由文本（``倒叙（回忆片段）``）。

    Args:
        flag: 事件的 timeline_flag 原值（可能为 None / 空串）.
        needles: 语义等价词表（中英并列）.

    Returns:
        任一 needle 作为子串出现 → True.
    """
    if not flag:
        return False
    lowered = flag.lower()
    return any(n.lower() in lowered for n in needles)


def to_days(time_value: float | None, time_unit: str | None) -> float | None:
    """把单个 ``(time_value, time_unit)`` 换算为「日」尺度（§2.7 S2/S4/S5）.

    Args:
        time_value: 世界内时间数值；None = 时间未知.
        time_unit: 时间单位标签（自由文本）.

    Returns:
        归一后的天数；``time_value`` 为 None → None；``时 / 时辰`` → None
        （当天时刻不是累计量，锚定需序列上下文，见 `normalized_days`）；
        未知/空单位 → 原值（因子 1，§2.7 S5）.
    """
    if time_value is None:
        return None
    unit = (time_unit or "").strip()
    if unit in CLOCK_UNITS:
        return None
    return time_value * UNIT_DAYS.get(unit, 1.0)


def normalized_days(events: Sequence[TimelineEvent]) -> dict[uuid.UUID, float | None]:
    """按**传入顺序**（叙事序）把事件投影到「日」尺度（§2.7 S2/S4/S9）.

    日级事件 `value × factor` 并更新**日锚点**；`时 / 时辰` = 日锚点 +
    `(value % 24) / 24`（当天时刻）；`time_value` 为 None → None 且不更新锚点
    （时间未知不计入、不影响后续锚定）。

    Args:
        events: 叙事序事件序列（调用方保证已按 narrative_position 排序）.

    Returns:
        事件 id → 归一后的天数（None = 时间未知），仅含传入的事件.
    """
    keys: dict[uuid.UUID, float | None] = {}
    anchor = 0.0
    for event in events:
        value = event.time_value
        if value is None:
            keys[event.id] = None
            continue
        unit = (event.time_unit or "").strip()
        if unit in CLOCK_UNITS:
            keys[event.id] = anchor + (value % 24) / 24.0
            continue
        days = value * UNIT_DAYS.get(unit, 1.0)
        keys[event.id] = days
        anchor = days
    return keys


@dataclass(frozen=True)
class TimebaseChange:
    """一条待改写的重锚计划项（§5.7 ④⑤）.

    Attributes:
        event_id: 目标事件 id.
        title: 事件标题（报告展示用）.
        time_value: 改写前的原值（审计留痕）.
        time_unit: 改写前的原单位（审计留痕）.
        new_time_value: 改写后的「日」尺度值.
        new_time_unit: 改写后的单位（恒为「日」）.
        new_time_display: 原 `time_display` 为空时归档的原表达式；None = 不修改.
    """

    event_id: uuid.UUID
    title: str
    time_value: float
    time_unit: str
    new_time_value: float
    new_time_unit: str = "日"
    new_time_display: str | None = None


@dataclass(frozen=True)
class TimebasePlan:
    """项目级归一/重锚计划（§5.7 报告结构与 `timeline normalize` 同构）.

    Attributes:
        segments: 识别出的叙事段数（数值回落 = 新段）.
        total_valued: 带值事件数（`time_value` 非 None）.
        changes: 待改写事件列表（空 = 幂等无操作）.
        conflicts_before: 归一前（原始数据）未声明逆序对数量.
        conflicts_after: 重锚（归一后）未声明逆序对数量.
        projected: 重锚后的归一值（供核对）；豁免事件不在其中.
    """

    segments: int
    total_valued: int
    changes: list[TimebaseChange]
    conflicts_before: int
    conflicts_after: int
    projected: dict[uuid.UUID, float]


def _count_conflicts(
    events: Sequence[TimelineEvent], keys: Mapping[uuid.UUID, float | None]
) -> int:
    """按 §5.4 规则统计相邻**未声明**逆序对数量（重锚报告用）.

    `None` 跳过；next 命中倒叙词表 / prev 命中插叙词表 → 合法，不计冲突。
    """
    total = 0
    for prev, nxt in pairwise(events):
        prev_key = keys.get(prev.id)
        next_key = keys.get(nxt.id)
        if prev_key is None or next_key is None or prev_key <= next_key:
            continue
        if has_flag(nxt.timeline_flag, *FLASHBACK_WORDS):
            continue
        if has_flag(prev.timeline_flag, *FLASHFORWARD_WORDS):
            continue
        total += 1
    return total


def plan_reanchor(events: Sequence[TimelineEvent]) -> TimebasePlan:
    """生成项目级归一/重锚计划（§5.7，一次性、显式、用户裁决的数据修复）.

    算法：按叙事序（调用方保证已排序）走**带值且未声明**倒叙/插叙的事件；
    **数值回落 = 新叙事段**，新段起点接在**上一段末尾**（`offset = prev_global`），
    **段内保留原有相对天数**（`g = offset + (v − 段内最小)`）；单位统一写「日」。
    首段 `offset = seg_min = v`（首段值不变）。

    ⚠️ 这是**单调投影**：对未声明事件按构造消除全部逆序（`conflicts_after = 0`），
    故必须 `dry-run` 优先、由作者看 `conflicts_before` 后显式 `--apply`。

    Args:
        events: 叙事序事件序列.

    Returns:
        TimebasePlan（空/全未知输入 → 空计划，不报错）.
    """
    before = normalized_days(events)
    projected: dict[uuid.UUID, float] = {}
    changes: list[TimebaseChange] = []
    segments = 0
    total_valued = 0
    offset = 0.0
    seg_min = 0.0
    prev_raw: float | None = None
    prev_global = 0.0
    for event in events:
        value = event.time_value
        if value is None:
            continue  # 时间未知：不改、不参与分段、不入 projected（§5.7 豁免）
        total_valued += 1
        if event.timeline_flag:
            continue  # 已声明倒叙/插叙：合法性由声明制保证，完全不改（§5.7 豁免）
        # `time_value is None` 已在上面 continue，`normalized_days` 对非 None 值必返回
        # float → 此处的归一值必为 float；用 cast 表达该不变量（无运行时分支）。
        raw = cast(float, before[event.id])
        if segments == 0:  # 首段：起点即本事件，故首段值不变
            segments = 1
            seg_min = raw
            offset = raw
        elif prev_raw is not None and raw < prev_raw:  # 回落 = 新叙事段
            segments += 1
            seg_min = raw
            offset = prev_global
        new_value = offset + (raw - seg_min)
        projected[event.id] = new_value
        prev_raw = raw
        prev_global = new_value
        if abs(new_value - raw) > _EPS or (event.time_unit or "").strip() != "日":
            changes.append(
                TimebaseChange(
                    event_id=event.id,
                    title=event.title,
                    time_value=value,
                    time_unit=event.time_unit,
                    new_time_value=new_value,
                    new_time_unit="日",
                    new_time_display=None if event.time_display else f"{value}{event.time_unit}",
                )
            )
    after: dict[uuid.UUID, float | None] = dict(before)
    after.update(projected)
    return TimebasePlan(
        segments=segments,
        total_valued=total_valued,
        changes=changes,
        conflicts_before=_count_conflicts(events, before),
        conflicts_after=_count_conflicts(events, after),
        projected=projected,
    )
