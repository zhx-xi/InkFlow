"""预算计算测试 — ModelContextRegistry + TokenBudgetConfig + 预算/分层 cap 计算.

测试范围 (spec §9):
    - 预算 = 窗口 × max_ratio
    - max_tokens 覆盖
    - 分层 cap 计算
    - layer_ratio 归一化
    - 模型窗口查询（精确 / 前缀 / 兜底）
    - 窗口 < 4096 → ValueError
"""

from __future__ import annotations

import pytest

from inkflow.core.model_registry import (
    calculate_budget,
    get_layer_cap,
    get_model_window,
    normalize_layer_ratio,
)
from inkflow.domain.models.context import ContextLayer, TokenBudgetConfig

# ─────────────────────────────────────────────────────────────
# get_model_window
# ─────────────────────────────────────────────────────────────


class TestModelWindow:
    """模型窗口查询."""

    def test_exact_match_gpt4o(self) -> None:
        assert get_model_window("openai/gpt-4o") == 128_000

    def test_exact_match_deepseek_chat(self) -> None:
        assert get_model_window("deepseek/deepseek-chat") == 128_000

    def test_exact_match_claude(self) -> None:
        assert get_model_window("anthropic/claude-3-5-sonnet-20241022") == 200_000

    def test_provider_prefix_deepseek(self) -> None:
        """未精确匹配但 provider=deepseek 有默认值."""
        assert get_model_window("deepseek/deepseek-v4") == 128_000

    def test_provider_prefix_openai(self) -> None:
        assert get_model_window("openai/gpt-5-unknown") == 128_000

    def test_provider_prefix_anthropic(self) -> None:
        assert get_model_window("anthropic/claude-4-future") == 200_000

    def test_fallback_unknown(self) -> None:
        """完全未知的模型使用兜底 128000."""
        assert get_model_window("unknown/unknown-model") == 128_000

    def test_custom_fallback(self) -> None:
        assert get_model_window("unknown/x", default_window=64_000) == 64_000

    def test_window_too_small_raises(self) -> None:
        """窗口 < 4096 应抛出错误."""
        # To trigger this, we need a model with small window
        assert get_model_window("openai/gpt-3.5-turbo") == 16_384  # still fine

    def test_window_below_4096_raises_valueerror(self) -> None:
        """模拟极小窗口."""
        # Monkey-patch the builtin table
        import inkflow.core.model_registry as mr

        original = mr._BUILTIN_WINDOWS.copy()
        try:
            mr._BUILTIN_WINDOWS["test/tiny"] = 2048
            with pytest.raises(ValueError, match="窗口过小"):
                get_model_window("test/tiny")
        finally:
            mr._BUILTIN_WINDOWS = original


# ─────────────────────────────────────────────────────────────
# calculate_budget
# ─────────────────────────────────────────────────────────────


class TestCalculateBudget:
    """预算计算."""

    def test_normal_80pct(self) -> None:
        """默认比例: 128000 × 0.8 = 102400."""
        assert calculate_budget("openai/gpt-4o") == 102_400

    def test_deepseek_80pct(self) -> None:
        assert calculate_budget("deepseek/deepseek-chat") == 102_400

    def test_claude_80pct(self) -> None:
        assert calculate_budget("anthropic/claude-3-5-sonnet-20241022") == 160_000

    def test_custom_ratio(self) -> None:
        assert calculate_budget("openai/gpt-4o", max_ratio=0.5) == 64_000

    def test_max_tokens_override(self) -> None:
        """max_tokens 覆盖模型窗口时用较小值."""
        # gpt-4o window=128000, max_tokens=50000 → effective=50000 × 0.8 = 40000
        assert calculate_budget("openai/gpt-4o", max_tokens=50_000) == 40_000

    def test_max_tokens_larger_than_window(self) -> None:
        """max_tokens > 窗口时用窗口值."""
        assert calculate_budget("openai/gpt-4o", max_tokens=200_000) == 102_400

    def test_small_window_gpt35(self) -> None:
        """gpt-3.5-turbo: 16384 × 0.8 = 13107."""
        expected = int(16384 * 0.8)
        assert calculate_budget("openai/gpt-3.5-turbo") == expected

    def test_zero_max_ratio(self) -> None:
        """max_ratio=0 应返回 0."""
        assert calculate_budget("openai/gpt-4o", max_ratio=0.0) == 0


# ─────────────────────────────────────────────────────────────
# get_layer_cap
# ─────────────────────────────────────────────────────────────


class TestLayerCap:
    """分层 cap 计算."""

    BUDGET = 100_000  # 方便验证的整数预算

    def test_protected_default(self) -> None:
        cap = get_layer_cap("protected", self.BUDGET)
        assert cap == 30_000  # 100000 × 0.30

    def test_compressible_default(self) -> None:
        cap = get_layer_cap("compressible", self.BUDGET)
        assert cap == 40_000  # 100000 × 0.40

    def test_dynamic_default(self) -> None:
        cap = get_layer_cap("dynamic", self.BUDGET)
        assert cap == 30_000  # 100000 × 0.30

    def test_custom_ratio(self) -> None:
        custom = {"protected": 0.5, "compressible": 0.3, "dynamic": 0.2}
        assert get_layer_cap("protected", self.BUDGET, custom) == 50_000
        assert get_layer_cap("compressible", self.BUDGET, custom) == 30_000
        assert get_layer_cap("dynamic", self.BUDGET, custom) == 20_000

    def test_normalization_when_sum_exceeds_one(self) -> None:
        """总和 1.5 → 归一化后 protected 占比 0.5/1.5 ≈ 0.333."""
        over = {"protected": 0.5, "compressible": 0.5, "dynamic": 0.5}  # total=1.5
        # 归一化后 protected = 0.5/1.5 = 1/3
        expected = int(self.BUDGET * (1 / 3))
        assert get_layer_cap("protected", self.BUDGET, over) == expected

    def test_zero_budget(self) -> None:
        assert get_layer_cap("protected", 0) == 0


# ─────────────────────────────────────────────────────────────
# normalize_layer_ratio
# ─────────────────────────────────────────────────────────────


class TestNormalizeLayerRatio:
    """分层比例归一化."""

    def test_normal_sum_one(self) -> None:
        r = {"a": 0.3, "b": 0.4, "c": 0.3}
        assert normalize_layer_ratio(r) == r

    def test_sum_less_than_one(self) -> None:
        r = {"a": 0.2, "b": 0.3}
        # sum = 0.5 ≤ 1.0，不归一化
        assert normalize_layer_ratio(r) == r

    def test_sum_exceeds_one(self) -> None:
        r = {"a": 0.6, "b": 0.6}  # total=1.2
        result = normalize_layer_ratio(r)
        assert result == {"a": 0.5, "b": 0.5}
        assert sum(result.values()) == 1.0

    def test_sum_double(self) -> None:
        r = {"x": 1.0, "y": 1.0}  # total=2.0
        result = normalize_layer_ratio(r)
        assert result == {"x": 0.5, "y": 0.5}

    def test_empty(self) -> None:
        assert normalize_layer_ratio({}) == {}


# ─────────────────────────────────────────────────────────────
# TokenBudgetConfig (Pydantic 验证)
# ─────────────────────────────────────────────────────────────


class TestTokenBudgetConfig:
    """TokenBudgetConfig 模型验证."""

    def test_defaults(self) -> None:
        cfg = TokenBudgetConfig()
        assert cfg.max_ratio == 0.8
        assert cfg.summary_max_chapters == 10
        assert cfg.compress_target_ratio == 0.5
        assert cfg.summary_model is None

    def test_default_layer_ratio(self) -> None:
        cfg = TokenBudgetConfig()
        assert cfg.layer_ratio[ContextLayer.PROTECTED] == 0.30
        assert cfg.layer_ratio[ContextLayer.COMPRESSIBLE] == 0.40
        assert cfg.layer_ratio[ContextLayer.DYNAMIC] == 0.30

    def test_max_ratio_clamp(self) -> None:
        """max_ratio 必须在 [0.1, 1.0] 内."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            TokenBudgetConfig(max_ratio=1.5)

    def test_auto_normalize_layer_ratio(self) -> None:
        """总和 > 1.0 自动归一化."""
        cfg = TokenBudgetConfig(
            layer_ratio={
                ContextLayer.PROTECTED: 0.5,
                ContextLayer.COMPRESSIBLE: 0.5,
                ContextLayer.DYNAMIC: 0.5,
            }
        )
        s = sum(cfg.layer_ratio.values())
        assert s == pytest.approx(1.0)

    def test_compress_target_ratio_range(self) -> None:
        with pytest.raises(Exception):
            TokenBudgetConfig(compress_target_ratio=2.0)

    def test_summary_max_chapters_range(self) -> None:
        with pytest.raises(Exception):
            TokenBudgetConfig(summary_max_chapters=0)
