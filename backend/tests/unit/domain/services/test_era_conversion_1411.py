"""#1411 跨纪元流速换算 — 纯函数契约（f12 spec v1.5 §2.8 E11 / ADR-065 §2.1）。

【契约（本文件钉住）】
- ``to_global(era, era_value, scale) = era_value / scale``
  （``era_scale`` = 该纪元相对项目时基的**流速比**；``1.0`` = 同速、越大越快）；
- **跨轴等值**：甲 ``scale=1`` ``era_value=1`` 与 乙 ``scale=2`` ``era_value=2`` 换算后同值
  （「甲纪元 1 单位 = 乙纪元 2 单位」，§14.3 A11 ①）；
- 边界：``era`` 为空 / ``era_value`` 为 None → ``None``；``era_value`` 为 0 / 负数 → 原样换算；
  ``scale <= 0`` → 按 ``1.0`` 处置（防御，流速比非正无意义）；
- 确定性：同输入同输出。
"""

from __future__ import annotations

import pytest

from inkflow.domain.services.era_conversion import to_global


class TestToGlobal:
    """换算公式与边界（spec §2.8 E11）。"""

    def test_scale_one_is_identity(self) -> None:
        """scale = 1.0（与项目时基同速）→ 全局标量 = 轴内值。"""
        assert to_global("示例历", 317.5, 1.0) == 317.5

    @pytest.mark.parametrize("scale", [0.5, 2.0, 100.0])
    def test_positive_scale_divides(self, scale: float) -> None:
        """scale 非 1 → 全局标量 = era_value / scale（流速比越大，周期越短）。"""
        assert to_global("示例历", 100.0, scale) == 100.0 / scale

    def test_equal_global_scalar_across_axes(self) -> None:
        """甲 1 单位 = 乙 2 单位（甲 scale=1 / 乙 scale=2）→ 换算后同值。"""
        assert to_global("甲纪", 1.0, 1.0) == to_global("乙纪", 2.0, 2.0) == 1.0

    def test_empty_era_returns_none(self) -> None:
        """默认轴（era 为空）→ 无全局标量。"""
        assert to_global("", 317.5, 1.0) is None

    def test_era_value_none_returns_none(self) -> None:
        """轴内值未知 → 无全局标量。"""
        assert to_global("示例历", None, 1.0) is None

    def test_zero_era_value(self) -> None:
        assert to_global("示例历", 0.0, 2.0) == 0.0

    def test_negative_era_value(self) -> None:
        """负数轴内值（纪元前）原样换算。"""
        assert to_global("示例历", -10.0, 2.0) == -5.0

    @pytest.mark.parametrize("bad_scale", [0.0, -1.0])
    def test_non_positive_scale_falls_back_to_one(self, bad_scale: float) -> None:
        """scale <= 0 → 按 1.0 处置（防御；请求面另有「须为正数」校验）。"""
        assert to_global("示例历", 7.0, bad_scale) == 7.0

    def test_deterministic(self) -> None:
        assert to_global("示例历", 3.0, 2.0) == to_global("示例历", 3.0, 2.0)
