"""LLM Provider 配置 — 从环境变量/配置加载，支持注册表优先 + APIKeyManager 已存 key 回退。

支持 LangChain 1.x 兼容的 Provider 路由。

#106 解析改造（spec §8.2②/§8.7）：
- 注册表优先：get_provider_config 先查 ProviderConfigService（持久化注册表），
  命中 → base_url/default_model 取注册表值；未命中/查询失败 → 静默回退内置硬编码。
- key 回退链：显式 api_key → 环境变量 → APIKeyManager 已存 key → 内置占位
  （ollama）→ ValueError。
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import dataclass, field

from inkflow.core.config import config
from inkflow.domain.models.provider_config import ProviderConfig
from inkflow.domain.services.provider_config_service import ProviderConfigService
from inkflow.infrastructure.llm.key_manager import APIKeyManager


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
    # 注（ADR-047 S0）："fake" 故意不在 _BUILTIN_PROVIDERS —— seed_builtin_providers
    # 遍历本表把 fake 当 GUI 内建 provider 持久化（污染 provider_configs 表）。
    # fake 的解析由 get_provider_config 顶部短接（provider == "fake"）完成，无需注册。
}


def _load_stored_key(provider: str) -> str | None:
    """key 回退链第 3 级：读取 APIKeyManager 已存 key（data_dir/keys/{provider}.json / .key）。

    #821 打包版差异防御：存储格式与当前 secret_key 状态不匹配时（如明文/密文
    不一致），交叉尝试 get_key → 明文 .key → 密文 .json 解密，任一命中即返回；
    全部失败 → 返回 None（保持调用方回退语义）。文件不存在/解密失败 → 忽略。
    """
    storage_dir = config.data_dir / "keys"
    try:
        key = APIKeyManager(
            secret_key=config.secret_key,
            storage_dir=storage_dir,
        ).get_key(provider)
        if key:
            return key
    except Exception:
        pass
    try:
        key = (storage_dir / f"{provider}.key").read_text(encoding="utf-8").strip()
        if key:
            return key
    except Exception:
        pass
    try:
        encrypted = json.loads((storage_dir / f"{provider}.json").read_text(encoding="utf-8"))
        key = APIKeyManager(
            secret_key=config.secret_key,
            storage_dir=storage_dir,
        ).decrypt(provider, encrypted_data=encrypted)
        if key:
            return key
    except Exception:
        pass
    return None


async def _lookup_registry_entry(provider: str) -> ProviderConfig | None:
    """查询持久化 Provider 注册表（ProviderConfigService.get_by_name）。

    SQLiteProviderConfigRepository / async_session_factory 放函数内部引入，
    避免 provider_config_repo.py 顶部引入本模块时的循环依赖。
    """
    from inkflow.core.database import async_session_factory
    from inkflow.infrastructure.database.repositories.provider_config_repo import (
        SQLiteProviderConfigRepository,
    )

    async with async_session_factory() as session:
        svc = ProviderConfigService(
            repository=SQLiteProviderConfigRepository(session),
        )
        return await svc.get_by_name(provider)


def _await_registry_entry(provider: str) -> ProviderConfig | None:
    """同步桥接注册表查询并阻塞直到结果。

    get_provider_config 保持同步函数签名（deps 8 处调用点零改动）。无运行中
    事件循环时用 asyncio.run；若被 LangChainLLMClient 在 async 上下文中调用，
    则另起线程 + 独立事件循环执行查询，避免阻塞当前运行循环
    （asyncio.run 会报 RuntimeError）。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_lookup_registry_entry(provider))

    result: list[ProviderConfig | None] = []
    error: list[BaseException] = []

    def _run_in_fresh_loop() -> None:
        try:
            result.append(asyncio.run(_lookup_registry_entry(provider)))
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(
        target=_run_in_fresh_loop,
        name=f"inkflow-registry-{provider}",
        daemon=True,
    )
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


def _builtin_default_model(provider: str) -> str:
    """内置路由默认（chat 型才可为 chat 消费）→ LiteLLM 格式 provider/model；无 → ""。"""
    entry = config.model_routing.get(provider)
    if entry is None or entry.type != "chat":
        return ""
    return f"{provider}/{entry.model}"


def get_provider_config(provider: str, api_key: str | None = None) -> LLMProviderConfig:
    """获取指定 Provider 的配置。

    Args:
        provider: Provider 名称（如 "openai", "deepseek"）。
        api_key: 可选 API Key 覆盖值——为 None 时回退环境变量注入；连通探测
            等按请求携带密钥的场景显式传入。

    key 解析优先级（high → low）:
      1. 显式传入 ``api_key`` 参数
      2. 环境变量 ``INKFLOW_{PROVIDER.upper()}_API_KEY``（调用时读 os.environ）/
         ``_BUILTIN_PROVIDERS`` 内建正取（含 ollama 占位 "ollama"）
      3. APIKeyManager.load(provider) 已存 key（文件不存在/解密失败 → 忽略）
      4. 全部缺失 → ValueError

    base_url / default_model 解析：注册表命中 → 注册表值；未命中/查询失败 →
    回退内置硬编码（_PROVIDER_BASE_URLS + config.model_routing / llm_default_model）。

    Returns:
        LLMProviderConfig 实例。

    Raises:
        ValueError: Provider 的 API Key 未配置。
    """
    # ADR-047 S0：fake provider 短接——INKFLOW_LLM_BASE_URL 指向 fake server。
    # fake 无真实 API key，不查注册表（无 DB 依赖）；key 用占位符，避免 ValueError。
    if provider == "fake":
        if config.llm_base_url:
            return LLMProviderConfig(
                provider="fake",
                api_key="placeholder-fake-key",
                base_url=config.llm_base_url,
                default_model="fake-model",
                models=[],
                max_retries=config.llm_max_retries,
                timeout=config.llm_request_timeout,
            )
        raise ValueError(
            "fake provider requires INKFLOW_LLM_BASE_URL to be set (ADR-047 S0)"
        )

    resolved_key = (
        api_key if api_key is not None else os.environ.get(f"INKFLOW_{provider.upper()}_API_KEY")
    )
    if resolved_key is None:
        resolved_key = _BUILTIN_PROVIDERS.get(provider)
    if resolved_key is None:
        resolved_key = _load_stored_key(provider)
    if resolved_key is None:
        raise ValueError(
            f"API key not configured for provider: {provider}. "
            f"Set INKFLOW_{provider.upper()}_API_KEY environment variable."
        )

    registry_entry: ProviderConfig | None = None
    try:
        registry_entry = _await_registry_entry(provider)
    except Exception:
        # 注册表查询失败（DB 未初始化/无表等）→ 静默回退内置硬编码，不抛异常
        registry_entry = None

    if registry_entry is not None:
        base_url = registry_entry.base_url
        default_model = (
            registry_entry.default_model
            or _builtin_default_model(provider)
            or config.llm_default_model
        )
        # #106 F6：注册表 models 传播（前端模型表展示）；getattr 兼容无 models
        # 属性的鸭子类型替身（test_provider_config_resolution.py 契约）
        registry_models = getattr(registry_entry, "models", None)
        models = [m.id for m in registry_models] if registry_models else []
    else:
        base_url = _PROVIDER_BASE_URLS.get(provider)
        default_model = _builtin_default_model(provider) or config.llm_default_model
        models = []

    return LLMProviderConfig(
        provider=provider,
        api_key=resolved_key,
        base_url=base_url,
        default_model=default_model,
        models=models,
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
