"""LLM 模型/密钥/base_url 装配解析（#758/#929/#936）。

从 deps.py 抽出以控制 900 行护栏。#929 拍板：删除最终 fallback——解析不到模型
（project/global 全空或 named provider key 不可用）→ logger.error 诊断 + 422，
绝不静默遍历注册表取 models[0]（不筛 type 会把 embedding 模型装配为 chat，
zhipu 400 1213 缺陷通道，issue #929 R1/R2）。

#936 收敛（A/B 两项）：
- A：新增 `resolve_chat_model` 单值守卫（只消费模型名的旁路点用）；
  `resolve_llm_credentials` 内部复用同一解析链（单一真相，禁第二份逻辑）。
- B：named model 若注册表确知 `type=embedding` → 422（新锚文本，不复用旧 detail）。
"""

from __future__ import annotations

from loguru import logger

_EMPTY_MODEL_DETAIL = "未配置默认模型，请在设置中配置 LLM Provider 和默认模型"


def resolve_chat_model(
    global_default: str,
    *,
    project_model: str | None = None,
) -> str:
    """解析 chat 模型（project > global），无解 → 422 + 诊断日志（#936 A 项唯一守卫）。

    只返回模型名（str）——只消费模型名的旁路点用；装配用 `resolve_llm_credentials`
    在其上追加 provider/key/base_url 解析。空 → loguru ERROR 锚「LLM 模型解析失败」+
    HTTPException 422（detail 逐字保留 #821/#929 契约文案）。
    """
    from fastapi import HTTPException

    from inkflow.core.config import config
    from inkflow.domain.services.model_resolution import resolve_model

    model = resolve_model(None, project_model, global_default) or ""
    if not model:
        logger.error(
            "LLM 模型解析失败（未配置）: project_model={} global_default={} "
            "内置路由={}（可 config set default.model provider/model 或项目设置）",
            project_model or "-",
            global_default or "-",
            sorted(config.model_routing),
        )
        raise HTTPException(status_code=422, detail=_EMPTY_MODEL_DETAIL)
    return model


def _lookup_registry_model_type(provider: str, model_name: str) -> str | None:
    """查注册表该 provider 是否含 id==model_name 的条目，命中返回其 type（#936 B 项）。

    无注册表/无该 provider/无该条目/**任何异常** → None（放行，误伤防御；镜像
    `resolve_reasoning_manual` 先例：辅助信息查询失败绝不阻断主路径）。
    """
    try:
        from inkflow.infrastructure.llm.provider_config import _await_registry_entry

        registry = _await_registry_entry(provider)
    except Exception:
        return None
    if registry is None:
        return None
    models = getattr(registry, "models", None)
    if not models:
        return None
    for entry in models:
        if getattr(entry, "id", None) == model_name:
            entry_type = getattr(entry, "type", None)
            return entry_type if isinstance(entry_type, str) else None
    return None


def resolve_llm_credentials(
    global_default: str,
    *,
    project_model: str | None = None,
) -> tuple[str, str, str]:
    """解析 (model, api_key, base_url)：project_model > global_default；无解 → 日志诊断 + 422。

    不再遍历注册表回退（#929 拍板：删除最终 fallback）。422 detail 文案逐字保留
    （#821 契约兼容）。签名向后兼容：既有单参调用点零改动可编译。模型解析（含
    空缺 422）走 `resolve_chat_model` 单一真相（#936 A）。
    """
    from fastapi import HTTPException

    from inkflow.infrastructure.llm.provider_config import (
        get_provider_config,
        parse_model_string,
    )

    model = resolve_chat_model(global_default, project_model=project_model)
    try:
        provider, model_name = parse_model_string(model)
        provider_cfg = get_provider_config(provider)
    except ValueError as exc:
        logger.error(
            "LLM 模型解析失败（provider key 不可用）: model={} 原因={}",
            model,
            exc,
        )
        raise HTTPException(status_code=422, detail=_EMPTY_MODEL_DETAIL) from exc
    # #936 B 项：named model 若注册表确知为 embedding 型 → 422（类型不符，新锚文本）。
    # 查不到该条目/查询异常 → 放行（误伤防御，见 _lookup_registry_model_type）。
    if _lookup_registry_model_type(provider, model_name) == "embedding":
        logger.error(
            "LLM 模型解析失败（类型不符）: model={} provider={} 注册表 type=embedding",
            model,
            provider,
        )
        raise HTTPException(
            status_code=422,
            detail=(
                f"模型 {model_name} 是 embedding 模型，不能作为对话模型使用，"
                "请在设置中改选 chat 模型"
            ),
        )
    # 评审 MAJOR-1（#935）：空串 key 可穿透 get_provider_config（仅 None 抛错）——
    # 旧「绝不带空 key 装配」守卫（#821 意图）必须保留，否则 LLM 客户端缺凭据
    # 500 复活（ADR-051 litellm 轨同语义）。
    if not provider_cfg.api_key:
        logger.error(
            "LLM 模型解析失败（api_key 为空）: model={} provider={}",
            model,
            provider,
        )
        raise HTTPException(status_code=422, detail=_EMPTY_MODEL_DETAIL)
    return model, provider_cfg.api_key, provider_cfg.base_url or ""
