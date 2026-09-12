"""首启模型就绪判据 — 纯函数 + 端点装配 helper（#934 / #1129）。

判据（spec §2.1 唯一真相）：存在**可解析的 chat 模型**——多源任一命中即就绪：
  (1) 注册表某 provider ∈ 已存 key 集合 且 ``models[]`` 含 ``type == "chat"``（#934 既有语义）；
  (2) 具名模型（``project.config.model`` / ``config.llm_default_model``）的 provider 有可用
      凭据且非注册表确知 embedding（镜 ``api/_llm_resolver.py`` 解析链，未知模型放行）。

#1129 根因：写作链真实可用性由 ``resolve_model(None, project_model, global_default)`` 判定
（``api/_llm_resolver.py:37``），而旧判据只查注册表 ``models[]``——``provider_config_service.create``
的 #735 D2 自动设默认只写内存单例 + config.json，从不回写 ``models[]`` → 「已存 key + 默认模型
可解析」被误判 false → GUI 引导页锁死且下拉为空。故收敛为 ``is_chat_model_resolvable`` 单一
可解析谓词，readiness 与 chat 模型下拉候选（``routers/provider_configs.py``）共用同一真相。

设计要点：
- ``compute_readiness`` / ``is_chat_model_resolvable`` 为**纯函数**（零 I/O），便于单测全分支覆盖；
- ``compute_model_readiness`` / ``read_project_models`` 为端点用装配 helper（读 DB + key 存储）；
- 判据**不含网络探测**（spec §2.1）——readiness 是高频查询，不能依赖外网可达性（离线用户会
  被误挡）；连通性验证发生在引导流程内的显式动作里。

依据: specs/f60-first-run-guide/spec.md §2.1 / §3.1；issue #1129。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.model_readiness import ModelReadiness, ReadinessReason
from inkflow.domain.models.provider_config import ProviderConfig


def _provider_names_with_models(
    provider: ProviderConfig, saved_names: set[str], model_type: str
) -> bool:
    """查 provider 是否「已存 key 且含至少一个指定 type 的模型」."""
    if provider.name not in saved_names:
        return False
    return any(m.type == model_type for m in provider.models)


def _registry_model_type(
    providers: list[ProviderConfig], provider: str, model_name: str
) -> str | None:
    """查注册表里 ``provider`` 名下 ``id == model_name`` 条目的 ``type``（纯函数）。

    镜 ``api/_llm_resolver._lookup_registry_model_type``：无该 provider / 无该条目 → None
    （未知 ≠ embedding → 放行，用户手填第三方 OpenAI 兼容模型名必须可用）。

    Args:
        providers: provider 注册表全量。
        provider: provider 名（``provider/model`` 首段）。
        model_name: 模型 id（``provider/model`` 余段）。

    Returns:
        ``"chat"`` / ``"embedding"``；未命中 → None。
    """
    for registry_entry in providers:
        if registry_entry.name != provider:
            continue
        for model in registry_entry.models:
            if model.id == model_name:
                return model.type
        return None
    return None


def is_chat_model_resolvable(
    model: str | None,
    providers: list[ProviderConfig],
    saved_provider_names: set[str],
    *,
    builtin_providers: dict[str, str | None] | None = None,
) -> bool:
    """``provider/model`` 是否可作 chat 消费（#1129 唯一可解析谓词）。

    语义（镜 ``api/_llm_resolver.py`` 的解析链，不阻塞主路径）：

    1. ``model`` 空 / 全空白 → False；
    2. 无 ``/`` → False（非 ``provider/model`` 形态）；
    3. provider 须有可用凭据：在 ``saved_provider_names`` 中，或 ``builtin_providers``
       内该 provider 值为真（镜像 ``infrastructure/llm/provider_config.py`` 的
       ``_BUILTIN_PROVIDERS``，含 ollama 占位）；
    4. 注册表**确知**该模型 ``type == "embedding"`` → False（#929 R1：embedding 永不
       当 chat）；注册表未知 / 无该条目 → True（benign unknown，同
       ``_lookup_registry_model_type`` 未知放行）。

    Args:
        model: 候选模型全名（``provider/model_name``），允许 None。
        providers: provider 注册表全量。
        saved_provider_names: 已存 API Key 的 provider 名集合（key_saved 语义）。
        builtin_providers: 内置 provider → key/占位值映射；None 视同 {}。

    Returns:
        True = 可解析为 chat 模型。
    """
    if not model or not model.strip():
        return False
    if "/" not in model:
        return False
    provider, model_name = model.split("/", 1)
    provider = provider.strip()
    model_name = model_name.strip()
    if not provider or not model_name:
        return False
    builtin = builtin_providers or {}
    if provider not in saved_provider_names and not builtin.get(provider):
        return False
    return _registry_model_type(providers, provider, model_name) != "embedding"


def compute_readiness(
    providers: list[ProviderConfig],
    saved_provider_names: set[str],
    *,
    project_models: list[str] | None = None,
    global_default: str | None = None,
    builtin_providers: dict[str, str | None] | None = None,
) -> ModelReadiness:
    """计算就绪判据（纯函数，零 I/O）。

    多源 OR（任一源可解析即就绪，顺序：注册表 → project 级模型 → 全局默认）：

    - src1 注册表 chat 条目 + provider 已存 key（#934 既有语义）；
    - src2 ``project_models`` 逐项可解析（项目级模型是写作链最高优先级，project > global）；
    - src3 ``global_default``（``config.llm_default_model``）可解析。

    reason 互斥（优先级不变，判定面扩到全部源）：

    - ``ready``：可解析；
    - ``no_provider``：无任何 provider 且无可解析源（真·全新安装）；
    - ``no_chat_model``：注册表无 chat 条目**且**无 project 级具名模型（#929 形态：只有
      embedding / provider 无模型条目）；
    - ``no_key``：存在具名 chat 源（注册表 chat 条目 / project 级模型）但无可用 key。

    ``has_embedding_model`` 保持注册表-only 判定（有 key 且 ``models[]`` 含 embedding），
    不随多源收敛变化（RAG 置灰判据独立）。

    Args:
        providers: provider 注册表全量（顺序无关）。
        saved_provider_names: 已存 API Key 的 provider 名集合（key_saved 语义）。
        project_models: 项目级模型候选（``projects.config.model``）；None 视同 []。
        global_default: 全局默认模型（``config.llm_default_model``）。
        builtin_providers: 内置 provider → key/占位值映射；None 视同 {}。

    Returns:
        ModelReadiness：ready / has_chat_model / has_embedding_model / reason。
    """
    builtin = builtin_providers or {}
    named_models = [m for m in (project_models or []) if m and m.strip()]

    has_chat_model = (
        any(_provider_names_with_models(p, saved_provider_names, "chat") for p in providers)
        or any(
            is_chat_model_resolvable(m, providers, saved_provider_names, builtin_providers=builtin)
            for m in named_models
        )
        or is_chat_model_resolvable(
            global_default, providers, saved_provider_names, builtin_providers=builtin
        )
    )
    has_embedding_model = any(
        _provider_names_with_models(p, saved_provider_names, "embedding") for p in providers
    )
    has_registry_chat_entry = any(m.type == "chat" for p in providers for m in p.models)

    if has_chat_model:
        reason: ReadinessReason = "ready"
    elif not providers:
        reason = "no_provider"
    elif has_registry_chat_entry or named_models:
        # 有具名 chat 源（注册表 chat 条目 / project 级模型）但无可用 key → 引导补 key；
        # 仅全局默认具名（无 project/注册表信号）仍按「无 chat 模型」引导配模型（#929 形态）。
        reason = "no_key"
    else:
        reason = "no_chat_model"

    return ModelReadiness(
        ready=has_chat_model,
        has_chat_model=has_chat_model,
        has_embedding_model=has_embedding_model,
        reason=reason,
    )


async def read_project_models(db: AsyncSession) -> list[str]:
    """读未删除项目的 ``config["model"]``（非空白字符串），失败 → []（绝不阻断主路径）。

    ORM / select 惰性导入（domain 层不静态依赖 SQLAlchemy DDL 面；本模块 helper 已
    走 api/infrastructure 惰性导入先例）。
    """
    try:
        from sqlalchemy import select

        from inkflow.infrastructure.database.models.project import ProjectORM

        configs = list(
            await db.scalars(select(ProjectORM.config).where(ProjectORM.is_deleted.is_(False)))
        )
    except Exception:
        return []
    models: list[str] = []
    for cfg in configs:
        value = cfg.get("model") if isinstance(cfg, dict) else None
        if isinstance(value, str) and value.strip():
            models.append(value)
    return models


def read_builtin_providers() -> dict[str, str | None]:
    """读内置 provider 表（``_BUILTIN_PROVIDERS``，含 ollama 占位）；失败 → {}。"""
    try:
        from inkflow.infrastructure.llm.provider_config import _BUILTIN_PROVIDERS

        return dict(_BUILTIN_PROVIDERS)
    except Exception:
        return {}


def _read_global_default() -> str:
    """读全局默认模型（``config.llm_default_model``）；失败 → ""。"""
    try:
        from inkflow.core.config import config

        default = config.llm_default_model or ""
    except Exception:
        return ""
    return default


async def compute_model_readiness(db: AsyncSession) -> ModelReadiness:
    """端点用装配 helper：读注册表 + 已存 key + 多源（project/global/builtin）→ compute_readiness。

    key 名集合经 ``APIKeyManager.list_providers()`` 获取（与 ``routers/provider_configs.py``
    key_saved 计算同源），不加载明文（安全红线：响应/日志禁回明细 key）。

    可选源逐项防御（镜 ``_llm_resolver``「辅助信息绝不阻断主路径」）：单源失败退化为空，
    不 500 端点；注册表本身的读取失败仍向上抛（端点 500 通用文案）。
    """
    from inkflow.api.deps import get_provider_config_service
    from inkflow.api.routers.settings import _get_key_manager

    service = get_provider_config_service(db)
    providers = await service.list()
    saved_names = set(_get_key_manager().list_providers())
    return compute_readiness(
        providers,
        saved_names,
        project_models=await read_project_models(db),
        global_default=_read_global_default(),
        builtin_providers=read_builtin_providers(),
    )
