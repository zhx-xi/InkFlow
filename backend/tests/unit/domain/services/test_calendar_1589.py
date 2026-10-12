"""#1589 / ADR-068：历法 spec 与「累计日数 → 年/月/日」换算（f12 §2.10 契约）.

RED 形态：``inkflow.domain.services.calendar`` 不存在时本文件**收集失败**（整文件 1 失败，预期）。

【为什么这些期望值可信】全部由**独立 oracle**（另写的最小实现，只用最直白的逐年/逐月累加）
先算出来，再写成字面量 —— 期望值不依赖被测实现，也不是「跑一遍实现抄回来」。

【契约（GREEN 必须提供）】
- ``CalendarSpec`` / ``CalendarConfig``：字段约束（表见 f12 §2.10）非法即 ``ValidationError``；
- ``evaluate_leap_rule(rule, year) -> bool``：白名单词法，**永不 eval**；
  非法表达式抛 ``ValueError``；
  求值异常（除零）→ ``False``（不抛）；
- ``day_count_to_date(days, spec) -> CalendarDate``：``days`` 已归整（本函数只吃浮点，内部 floor）；
- ``resolve_day_count(era, era_value, time_value, time_unit) -> float | None``：S2/S3 输入口径
  （纪元轴 = ``era_value``；默认轴 = ``time_value × factor(unit)``；未知 → None）；
- **N7 反例守护**：换算链路**不含** ``era_scale``（流速比只影响纵向定位）。
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from inkflow.domain.services.calendar import (
    CalendarConfig,
    CalendarSpec,
    day_count_to_date,
    evaluate_leap_rule,
    resolve_day_count,
)

#: Gregorian 式闰年表达式（D2 的「表达式字符串」形态）
GREG = "# % 4 == 0 && (# % 100 != 0 || # % 400 == 0)"
#: 不等月长（N3/N4）
GLD = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
#: 均等月长 12×30（N2/N5）
FLAT = [30] * 12


def make_spec(**overrides: object) -> CalendarSpec:
    """默认 = 均等月长 + 每 4 年闰 1 日（计入第 2 月）。"""
    base: dict[str, object] = {
        "axis": "武侠界",
        "month_days": FLAT,
        "leap": {"rule": GREG, "add_days": 1, "month": 2},
    }
    base.update(overrides)
    return CalendarSpec(**base)


def ymd(days: float, spec: CalendarSpec) -> tuple[int, int, int]:
    d = day_count_to_date(days, spec)
    return d.year, d.month, d.day


# ══════════════════════════ 1. spec 校验（写入面 422 的领域侧前提） ══════════════════════════


class TestSpecValidation:
    def test_month_days_required_and_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSpec(axis="x", month_days=[])

    @pytest.mark.parametrize("bad", [[0] * 12, [30, -1], [1, 2, 0]])
    def test_month_days_must_be_positive(self, bad: list[int]) -> None:
        with pytest.raises(ValidationError):
            CalendarSpec(axis="x", month_days=bad)

    def test_month_days_length_capped(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSpec(axis="x", month_days=[30] * 25)

    def test_month_names_length_must_match(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSpec(axis="x", month_days=[30, 30], month_names=["正月"])

    def test_month_names_ok_when_length_matches(self) -> None:
        spec = CalendarSpec(axis="x", month_days=[30, 30], month_names=["正月", "二月"])
        assert spec.month_names == ["正月", "二月"]

    def test_leap_month_must_be_in_range(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSpec(axis="x", month_days=[30, 30], leap={"rule": "1 == 1", "month": 3})

    @pytest.mark.parametrize("add_days", [0, 11])
    def test_leap_add_days_range(self, add_days: int) -> None:
        with pytest.raises(ValidationError):
            CalendarSpec(axis="x", month_days=[30], leap={"rule": "1 == 1", "add_days": add_days})

    def test_leap_rule_must_parse(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSpec(axis="x", month_days=[30], leap={"rule": "import os", "month": 1})

    def test_leap_rule_length_capped(self) -> None:
        with pytest.raises(ValidationError):
            CalendarSpec(axis="x", month_days=[30], leap={"rule": "# " * 120 + "== 0", "month": 1})

    @pytest.mark.parametrize("years", [1, 10001])
    def test_era_cycle_years_range(self, years: int) -> None:
        with pytest.raises(ValidationError):
            CalendarSpec(axis="x", month_days=[30], era_cycle={"years": years, "label": "劫"})

    def test_axis_stripped_and_capped(self) -> None:
        assert make_spec(axis="  武侠界  ").axis == "武侠界"
        assert make_spec(axis="").axis == ""
        with pytest.raises(ValidationError):
            make_spec(axis="x" * 51)

    def test_config_rejects_duplicate_axis(self) -> None:
        with pytest.raises(ValidationError):
            CalendarConfig(
                calendars=[make_spec(axis="武侠界"), make_spec(axis="武侠界", month_days=GLD)]
            )

    def test_config_accepts_distinct_axes_and_empty(self) -> None:
        assert CalendarConfig().calendars == []
        cfg = CalendarConfig(
            calendars=[make_spec(axis="武侠界"), make_spec(axis="仙界", month_days=GLD)]
        )
        assert [c.axis for c in cfg.calendars] == ["武侠界", "仙界"]

    def test_intercalary_reserved_field_is_accepted_but_ignored(self) -> None:
        """0.18.0：`intercalary` 接受存储、不参与换算（f12 §2.10 表）。"""
        spec = make_spec(intercalary=[{"name": "立春", "days": 1}])
        assert ymd(0, spec) == (1, 1, 1)
        assert ymd(360, spec) == (2, 1, 1)  # 与无 intercalary 时逐位相同


# ══════════════════════════ 2. 表达式求值器（受限词法，永不 eval） ══════════════════════════


class TestLeapExpression:
    @pytest.mark.parametrize(
        ("year", "expected"),
        [
            (1, False),
            (4, True),
            (100, False),
            (400, True),
            (1900, False),
            (2000, True),
            (2100, False),
        ],
    )
    def test_gregorian_expression(self, year: int, expected: bool) -> None:
        assert evaluate_leap_rule(GREG, year) is expected

    @pytest.mark.parametrize(
        "rule",
        [
            "# % 4 == 0",
            "# % 100 == 0 || (# % 4 == 0 && # % 400 != 0)",
            "# * 2 > 3",
        ],
    )
    def test_simple_arithmetic_allowed(self, rule: str) -> None:
        assert isinstance(evaluate_leap_rule(rule, 8), bool)

    @pytest.mark.parametrize(
        "rule",
        [
            "",
            "   ",
            "__import__('os').system('x')",
            "open('x')",
            "a % 4 == 0",
            "# + b",
            "# ** 2 == 4",
            "# // 2 == 1",
            "#.real == 1",
            "(# % 4 == 0",
            "# % 4 == 0)",
            "1 if # else 2",
            "# and 1",
            "lambda: 1",
            "[1][0]",
            "# % 4 ==",
        ],
    )
    def test_whitelist_rejects_everything_else(self, rule: str) -> None:
        with pytest.raises(ValueError, match="表达式"):
            evaluate_leap_rule(rule, 4)

    def test_zero_division_does_not_raise(self) -> None:
        assert evaluate_leap_rule("# % 4 == 0 && 1 / (# - #) > 0", 4) is False

    def test_evaluator_never_calls_eval(self) -> None:
        """结构化守护：模块源码不得调用內建 eval/exec/compile（`re.compile(` 不算）。"""
        import re

        from inkflow.domain.services import calendar as mod

        src = inspect.getsource(mod)
        for banned in (r"(?<![\w.])eval\(", r"(?<![\w.])exec\(", r"(?<![\w.])compile\("):
            assert re.search(banned, src) is None, f"禁用内建 {banned}"


# ══════════════════════════ 3. 换算（oracle 字面量） ══════════════════════════


class TestConversion:
    def test_n2_flat_months_2920_days(self) -> None:
        """N2 量级：12×30 + 每 4 年闰 1 日 → 2920 日 = 第 9 年（非原始「2920 日」）。"""
        spec = make_spec()
        assert ymd(2920, spec) == (9, 2, 9)
        assert ymd(2882, spec) == (9, 1, 1)
        assert ymd(2881, spec) == (8, 12, 30)

    @pytest.mark.parametrize(
        ("days", "expected"),
        [
            (0, (1, 1, 1)),
            (29, (1, 1, 30)),
            (359, (1, 12, 30)),
            (360, (2, 1, 1)),
            (361, (2, 1, 2)),
        ],
    )
    def test_year_boundary(self, days: float, expected: tuple[int, int, int]) -> None:
        assert ymd(days, make_spec()) == expected

    @pytest.mark.parametrize(
        ("days", "expected"),
        [
            (0, (1, 1, 1)),
            (30, (1, 1, 31)),
            (31, (1, 2, 1)),
            (58, (1, 2, 28)),
            (59, (1, 3, 1)),
            (365, (2, 1, 1)),
            (1095, (4, 1, 1)),
        ],
    )
    def test_n3_uneven_months(self, days: float, expected: tuple[int, int, int]) -> None:
        """N3：不等月长下同一年内月/日正确。"""
        assert ymd(days, make_spec(month_days=GLD)) == expected

    def test_n4_leap_year_and_century(self) -> None:
        """N4：第 4 年 2 月为 29 日；第 100 年不闰（2 月 28 日后即 3 月 1 日）。"""
        spec = make_spec(month_days=GLD)
        assert ymd(1154, spec) == (4, 2, 29)  # 第 4 年 2 月 29 日
        assert ymd(1155, spec) == (4, 3, 1)  # 第 4 年 2 月无第 30 天
        assert ymd(36217, spec) == (100, 2, 28)
        assert ymd(36218, spec) == (100, 3, 1)  # 第 100 年 2 月无 29 日

    def test_n5_era_cycle(self) -> None:
        """N5：纪元周期生效 → cycle 字段（标签前插「N 劫」由前端拼）。"""
        spec = make_spec(era_cycle={"years": 100, "label": "劫"})
        assert day_count_to_date(0, spec).cycle == 1
        got100 = day_count_to_date(35664, spec)  # 第 100 年起始
        assert (got100.year, got100.cycle) == (100, 1)
        got101 = day_count_to_date(36024, spec)  # 第 101 年起始
        assert (got101.year, got101.cycle) == (101, 2)
        got250 = day_count_to_date(89700, spec)  # 第 250 年起始
        assert (got250.year, got250.cycle) == (250, 3)

    def test_c1_same_day_rounding(self) -> None:
        """C1 同日归整：亚日小数向下归整（0.79 日不再单独成刻度）。"""
        spec = make_spec()
        assert ymd(0.0, spec) == ymd(0.79, spec) == ymd(0.999, spec) == (1, 1, 1)
        assert ymd(3.27, spec) == (1, 1, 4)
        assert ymd(2920.999, spec) == ymd(2920.0, spec) == (9, 2, 9)

    def test_c5_deterministic(self) -> None:
        spec = make_spec(month_days=GLD)
        assert [ymd(12345, spec) for _ in range(3)] == [ymd(12345, spec)] * 3

    def test_default_epoch_label_does_not_affect_numbers(self) -> None:
        assert ymd(360, make_spec(epoch_label="开元")) == ymd(360, make_spec())


# ══════════════════════════ 4. 输入口径（S2/S3/N7） ══════════════════════════


class TestResolveDayCount:
    def test_default_axis_uses_time_value_times_unit_factor(self) -> None:
        assert resolve_day_count("", None, 3.0, "年") == 1095.0  # 3 年 = 1095 日（S2：年 = 365 日）
        assert resolve_day_count("", None, 2.0, "月") == 60.0
        assert resolve_day_count("", None, 2.0, "周") == 14.0
        assert resolve_day_count("", None, 7.5, "日") == 7.5
        assert resolve_day_count("", None, 7.5, "天") == 7.5

    def test_default_axis_unknown_unit_is_raw(self) -> None:
        """S5（f12 §2.7）：未列举单位 / 空串 = 时基裸值（因子 1，向后兼容）。"""
        assert resolve_day_count("", None, 42.0, "") == 42.0
        assert resolve_day_count("", None, 42.0, None) == 42.0
        assert resolve_day_count("", None, 42.0, "刻") == 42.0

    def test_hour_unit_has_no_day_anchor(self) -> None:
        """S4：`时/时辰` 是当天时刻（无日锚点 → 锚点取 0）→ 值 < 24 归到第 1 日。"""
        assert resolve_day_count("", None, 0.0, "时") == 0.0
        assert resolve_day_count("", None, 12.0, "时辰") == 0.5

    def test_era_axis_uses_era_value_only(self) -> None:
        """S3：纪元轴取 `era_value`（该历法自己的日尺度），**不受 time_value / time_unit 影响**。"""
        assert resolve_day_count("武侠界", 2920.0, 9.0, "年") == 2920.0
        assert resolve_day_count("武侠界", 2920.0, None, None) == 2920.0

    def test_unknown_input_returns_none(self) -> None:
        assert resolve_day_count("", None, None, "年") is None
        assert resolve_day_count("", None, None, None) is None
        assert resolve_day_count("武侠界", None, 100.0, "年") is None

    def test_n7_no_era_scale_in_conversion_chain(self) -> None:
        """N7 反例守护（D6）：换算链路**不接收** `era_scale` —— 流速比只动纵向位置。"""
        for fn in (day_count_to_date, resolve_day_count):
            params = inspect.signature(fn).parameters
            assert "era_scale" not in params, f"{fn.__name__} 不得消费 era_scale"
        # 同一日数、不同「流速比」在调用面上无法表达差异 → 标签必然不变
        assert ymd(2920, make_spec()) == ymd(2920, make_spec(axis="武侠界"))
