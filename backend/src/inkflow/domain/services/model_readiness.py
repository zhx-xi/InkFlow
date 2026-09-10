"""首启模型就绪判据 — 纯函数 + 端点用装配 helper（#934）。

判据（spec §2.1 唯一真相）：存在 provider 同时满足
  (1) ``provider.name`` ∈ 已存 key 的 provider 名集合（key_saved 语义）
  (2) 该 provider 的 ``models`` 中存在至少一个 ``type == "chat"`` 条目

设计要点：
- ``compute_readiness`` 为**纯函数**（零 I/O），便于单测全分支覆盖；
- ``compute_model_readiness`` 为端点用装配 helper（读 DB + 读 key 存储）；
- 判据**不含网络探测**（spec §2.1）——readiness 是高频查询，不能依赖外网
  可达性（离线用户会被误挡）；连通性验证发生在引导流程内。

依据: specs/f60-first-run-guide/spec.md §2.1 / §3.1。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.model_readiness import ModelReadiness, ReadinessReason
from inkflow.domain.models.provider_config import ProviderConfig


def _provider_names_with_models(
    provider: ProviderConfig, saved_names: set[str], model_type: str
) -> bool:
    """该 provider 是否「已存 key 且含至少一个指定 type 的模型」。"""
    if provider.name not in saved_names:
        return False
    return any(m.type == model_type for m in provider.models)


def compute_readiness(
    providers: list[ProviderConfig],
    saved_provider_names: set[str],
) -> ModelReadiness:
    """计算就绪判据（纯函数，零 I/O）。

    Args:
        providers: provider 注册表全量（顺序无关）。
        saved_provider_names: 已存 API Key 的 provider 名集合（key_saved 语义）。

    Returns:
        ModelReadiness：ready / has_chat_model / has_embedding_model / reason。
    """
    has_chat_model = any(
        _provider_names_with_models(p, saved_provider_names, "chat") for p in providers
    )
    has_embedding_model = any(
        _provider_names_with_models(p, saved_provider_names, "embedding") for p in providers
    )

    if has_chat_model:
        reason: ReadinessReason = "ready"
    elif not providers:
        reason = "no_provider"
    elif not any(m.type == "chat" for p in providers for m in p.models):
        # 有 provider 但全无 chat 模型（#929 形态：只有 embedding）→ 先引导配模型
        reason = "no_chat_model"
    else:
        # 有 chat 模型但对应 provider 无 key → 引导补 key
        reason = "no_key"

    return ModelReadiness(
        ready=has_chat_model,
        has_chat_model=has_chat_model,
        has_embedding_model=has_embedding_model,
        reason=reason,
    )


async def compute_model_readiness(db: AsyncSession) -> ModelReadiness:
    """端点用装配 helper：读注册表 + 读加密 key 存储 → compute_readiness。

    key 名集合经 ``APIKeyManager.list_providers()`` 获取（与
    ``routers/provider_configs.py`` key_saved 计算同源），不加载明文
    （安全红线：响应/日志禁回显 key）。
    """
    from inkflow.api.deps import get_provider_config_service
    from inkflow.api.routers.settings import _get_key_manager

    service = get_provider_config_service(db)
    providers = await service.list()
    saved_names = set(_get_key_manager().list_providers())
    return compute_readiness(providers, saved_names)
