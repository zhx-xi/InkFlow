"""模型上下文窗口注册表 — 查询各模型的 Token 上限.

查询规则（按优先级递减）:
1. 精确匹配: provider/model_name（如 openai/gpt-4o）
2. Provider 前缀匹配: model 以 "provider/" 开头时，查该 provider 的默认窗口
3. 兜底: config.context.default_window + WARNING 日志

依据: specs/f6-context/spec.md §7 ModelContextRegistry.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 内置模型窗口表（Phase 1）
# 格式: "provider/model_name" → context_window
_BUILTIN_WINDOWS: dict[str, int] = {
    "openai/gpt-4o": 128_000,
    "openai/gpt-4o-mini": 128_000,
    "openai/gpt-4-turbo": 128_000,
    "openai/gpt-3.5-turbo": 16_384,
    "deepseek/deepseek-chat": 128_000,
    "deepseek/deepseek-v4-flash": 128_000,
    "deepseek/deepseek-reasoner": 128_000,
    "zhipu/glm-4.5": 128_000,
    "anthropic/claude-3-5-sonnet-20241022": 200_000,
    "anthropic/claude-3-opus-20240229": 200_000,
    "anthropic/claude-3-haiku-20240307": 200_000,
    "anthropic/claude-3-sonnet-20240229": 200_000,
}

# Provider 默认窗口（前缀匹配用）
_PROVIDER_DEFAULTS: dict[str, int] = {
    "openai": 128_000,
    "deepseek": 128_000,
    "zhipu": 128_000,
    "anthropic": 200_000,
}

# 兜底默认窗口
_DEFAULT_WINDOW: int = 128_000


def get_model_window(model: str, default_window: int | None = None) -> int:
    """查询模型上下文窗口大小.

    Args:
        model: 模型名（provider/model_name 格式）.
        default_window: 兜底默认值，None 则用内置默认 128000.

    Returns:
        模型上下文窗口 Token 数.

    Raises:
        ValueError: 窗口 < 4096（配置错误，无法工作）.
    """
    fallback = default_window if default_window is not None else _DEFAULT_WINDOW

    # 1. 精确匹配
    if model in _BUILTIN_WINDOWS:
        window = _BUILTIN_WINDOWS[model]
    else:
        # 2. Provider 前缀匹配
        provider = model.split("/")[0] if "/" in model else ""
        if provider in _PROVIDER_DEFAULTS:
            window = _PROVIDER_DEFAULTS[provider]
        else:
            # 3. 兜底
            logger.warning("未知模型窗口: model=%s，使用兜底 %d", model, fallback)
            window = fallback

    if window < 4096:
        raise ValueError(f"模型窗口过小: model={model}, window={window}（最小要求 4096）")

    return window


def calculate_budget(
    model: str,
    max_ratio: float = 0.8,
    max_tokens: int | None = None,
    default_window: int | None = None,
) -> int:
    """计算上下文预算 = min(模型窗口, max_tokens) × max_ratio.

    Args:
        model: 模型名.
        max_ratio: 预算比例上限（默认 0.8 = 80%）.
        max_tokens: 显式覆盖最大 Token 数，None 则全用模型窗口.
        default_window: 兜底窗口大小.

    Returns:
        预算 Token 数.
    """
    window = get_model_window(model, default_window)
    effective_window = min(window, max_tokens) if max_tokens else window
    return int(effective_window * max_ratio)


def get_layer_cap(
    layer: ContextLayer,  # type: ignore[name-defined]  # noqa: F821
    budget: int,
    layer_ratio: dict[str, float] | None = None,
) -> int:
    """计算分层 cap = budget × layer_ratio[layer].

    Args:
        layer: 上下文层（ContextLayer 枚举值）.
        budget: 总预算 Token 数.
        layer_ratio: 分层比例映射，None 则使用默认 {protected:0.3, compressible:0.4, dynamic:0.3}.

    Returns:
        该层的 Token 上限.
    """
    if layer_ratio is None:
        layer_ratio = {
            "protected": 0.30,
            "compressible": 0.40,
            "dynamic": 0.30,
        }

    ratio = layer_ratio.get(layer, 0.0)

    # 归一化：如果总和 > 1.0，按比例缩放
    total = sum(layer_ratio.values())
    if total > 1.0:
        ratio = ratio / total

    return int(budget * ratio)


def normalize_layer_ratio(
    layer_ratio: dict[str, float],
) -> dict[str, float]:
    """归一化分层比例，确保总和 ≤ 1.0.

    Args:
        layer_ratio: 原始分层比例（可能总和 > 1.0）.

    Returns:
        归一化后的比例（总和 ≤ 1.0）.
    """
    total = sum(layer_ratio.values())
    if total <= 1.0:
        return layer_ratio
    return {k: v / total for k, v in layer_ratio.items()}
