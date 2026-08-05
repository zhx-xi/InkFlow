"""LLM Provider 配置 — 从环境变量/配置加载。

支持 LangChain 1.x 兼容的 Provider 路由。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from inkflow.core.config import config


@dataclass
class LLMProviderConfig:
    """单个 LLM Provider 的配置。"""

    provider: str
    api_key: str
    base_url: str | None = None
    default_model: str = ""
    models: list[str] = field(default_factory=list)
    max_retries: int = 3
    timeout: int = 120


# Provider → base_url 映射（OpenAI 兼容 API）
_PROVIDER_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/",
    # OpenAI 使用 SDK 默认端点
}

# 内建 Provider 注册表 — 从 config 对象读取 API Key
# 注（ADR-005v2 更新，2026-08-01）：实现走 langchain_openai.ChatOpenAI + base_url，
# 仅支持 OpenAI 兼容端点。anthropic 已从注册表移除——其原生 API 非 OpenAI 兼容，
# 需独立 SDK 适配（config.anthropic_api_key 字段保留供未来实现）。
_BUILTIN_PROVIDERS: dict[str, str | None] = {
    "openai": config.openai_api_key or None,
    "deepseek": config.deepseek_api_key or None,
    "zhipu": config.zhipu_api_key or None,
    "ollama": "ollama",  # Ollama 本地运行，无需真实 API Key
}


def get_provider_config(provider: str, api_key: str | None = None) -> LLMProviderConfig:
    """获取指定 Provider 的配置。

    Args:
        provider: Provider 名称（如 "openai", "deepseek"）。
        api_key: 可选 API Key 覆盖值 — 为 None 时回退环境变量注入；连通探测
            等按请求携带密钥的场景显式传入。

    Returns:
        LLMProviderConfig 实例。

    Raises:
        ValueError: Provider 的 API Key 未配置。
    """
    resolved_key = api_key if api_key is not None else _BUILTIN_PROVIDERS.get(provider)
    if resolved_key is None:
        raise ValueError(
            f"API key not configured for provider: {provider}. "
            f"Set INKFLOW_{provider.upper()}_API_KEY environment variable."
        )

    return LLMProviderConfig(
        provider=provider,
        api_key=resolved_key,
        base_url=_PROVIDER_BASE_URLS.get(provider),
        default_model=config.model_routing.get(provider, config.llm_default_model),
        max_retries=config.llm_max_retries,
        timeout=config.llm_request_timeout,
    )


def parse_model_string(model: str) -> tuple[str, str]:
    """解析 LiteLLM 格式的模型字符串。

    Args:
        model: 模型标识（如 "openai/gpt-4o", "deepseek/deepseek-chat"）。

    Returns:
        (provider, model_name) 元组。

    Raises:
        ValueError: 格式无效。
    """
    if "/" not in model:
        raise ValueError(
            f"Invalid model format: {model!r}. "
            f"Expected 'provider/model_name' (e.g., 'openai/gpt-4o')."
        )
    provider, model_name = model.split("/", 1)
    return provider, model_name
