"""#1581 时间线后置时间归一 —— 确定性文本解析器单测（RED）。

被测（GREEN 才实现）::

    from inkflow.domain.services._timeline_text_time import ParsedTime, parse_time_display

    parse_time_display(text) -> tuple[ParsedTime | None, str]
        解析成功 → (ParsedTime(value, unit, era), "")
        解析失败 → (None, reason)   reason 非空（供暂存区展示「未定原因」）

RED 预期: 模块不存在 → 收集期 ImportError（FAIL）。

依据: specs/f12-timeline/spec.md §2.9 Z2（解析器能力边界表 + 不覆盖清单）。
"""

from __future__ import annotations

import pytest

from inkflow.domain.services._timeline_text_time import parse_time_display

# ── 覆盖形态（spec §2.9 表）─────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "value", "unit", "era"),
    [
        # 纪年式：<轴名> <N> 年[季/月/…]
        ("示例历 317 年", 317.0, "年", "示例历"),
        ("示例历 317 年秋", 317.0, "年", "示例历"),
        ("示例仙界 1024 年", 1024.0, "年", "示例仙界"),
        # 真序数：第 <N> <单位>
        ("第 5 天", 5.0, "天", ""),
        ("第16年", 16.0, "年", ""),
        # 数量：<N><单位>
        ("三年", 3.0, "年", ""),
        ("15 日", 15.0, "日", ""),
        ("两个月", 2.0, "月", ""),
        ("三周", 3.0, "周", ""),
    ],
)
def test_parse_covered_forms(raw: str, value: float, unit: str, era: str) -> None:
    """覆盖形态 → (value, unit, era) 完全一致，且 reason 为空。"""
    parsed, reason = parse_time_display(raw)
    assert reason == ""
    assert parsed is not None
    assert (parsed.value, parsed.unit, parsed.era) == (value, unit, era)


def test_parse_month_day_folds_to_days() -> None:
    """月日按 spec 口径折算：value = (月-1)×30 + 日，单位「日」。"""
    parsed, reason = parse_time_display("三月初二")

    assert reason == ""
    assert parsed is not None
    assert parsed.value == 62.0  # (3-1)*30 + 2
    assert parsed.unit == "日"
    assert parse_time_display("十二月初五")[0].value == 335.0  # (12-1)*30 + 5
    # 「廿 N」= 20 + N（下旬写法）
    assert parse_time_display("三月廿五")[0].value == 85.0  # (3-1)*30 + 25


def test_month_out_of_range_falls_through_to_failure() -> None:
    """月超出 1-12 → 不产假值，走失败分支（带 reason）。"""
    parsed, reason = parse_time_display("十三月初一")

    assert parsed is None
    assert reason.strip() != ""


# ── 不覆盖形态（spec §2.9「不覆盖」清单）→ 失败 + reason ──────────


@pytest.mark.parametrize(
    "raw",
    [
        "第二天",  # 相对序数（中文数字序号不做锚定）
        "第二天早上",
        "第九天",  # 同上（仅阿拉伯数字序号视为绝对时间键）
        "过了两天",  # 相对时长
        "三年后",
        "十五日后",
        "那年冬天",  # 无绝对时间量
        "有一天",
        "当年",
        "卯时三刻",  # 当天时刻（无日锚点）
        "二更上",
        "初五",  # 缺年月
        "三十二岁",  # 人物年龄，非世界内时间
        "又过几年",  # 数量模糊
        "",  # 原文缺失
        "   ",
    ],
)
def test_uncovered_forms_fail_with_reason(raw: str) -> None:
    """不覆盖形态 → 解析为 None + **非空** reason（禁止静默）。"""
    parsed, reason = parse_time_display(raw)

    assert parsed is None
    assert reason.strip() != ""


def test_parse_is_deterministic_and_pure() -> None:
    """同输入同输出（幂等；spec 要求确定性纯函数）。"""
    assert parse_time_display("示例历 317 年") == parse_time_display("示例历 317 年")
    assert parse_time_display("那年冬天") == parse_time_display("那年冬天")


def test_no_time_unit_without_value() -> None:
    """不变量：永不返回「有 unit 无 value」的解析结果（spec §2.9 禁止 ④）。"""
    for raw in ("示例历 317 年", "第 5 天", "三年", "三月初二"):
        parsed, _ = parse_time_display(raw)
        assert parsed is not None and parsed.value is not None and parsed.unit != ""
