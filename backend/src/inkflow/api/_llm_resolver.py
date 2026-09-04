"""LLM 模型/密钥/base_url 装配解析（#758/#929）。

从 deps.py 抽出以控制 900 行护栏。#929 拍板：删除最终 fallback——解析不到模型
（project/global 全空或 named provider key 不可用）→ logger.error 诊断 + 422，
绝不静默遍历注册表取 models[0]（不筛 type 会把 embedding 模型装配为 chat，
zhipu 400 1213 缺陷通道，issue #929 R1/R2）。
"""

from __future__ import annotations

from loguru import logger


def resolve_llm_credentials(
    global_default: str,
    *,
    project_model: str | None = None,
) -> tuple[str, str, str]:
    """解析 (model, api_key, base_url)：project_model > global_default；无解 → 日志诊断 + 422。

    不再遍历注册表回退（#929 拍板：删除最终 fallback）。422 detail 文案逐字保留
    （#821 契约兼容）。签名向后兼容：既有单参调用点零改动可编译。
    """
    from fastapi import HTTPException

    from inkflow.core.config import config
    from inkflow.domain.services.model_resolution import resolve_model
    from inkflow.infrastructure.llm.provider_config import (
        get_provider_config,
        parse_model_string,
    )

    model = resolve_model(None, project_model, global_default) or ""
    if not model:
        logger.error(
            "LLM 模型解析失败（未配置）: project_model={} global_default={} "
            "内置路由={}（可 config set default.model provider/model 或项目设置）",
            project_model or "-",
            global_default or "-",
            sorted(config.model_routing),
        )
        raise HTTPException(
            status_code=422,
            detail="未配置默认模型，请在设置中配置 LLM Provider 和默认模型",
        )
    try:
        provider, _ = parse_model_string(model)
        provider_cfg = get_provider_config(provider)
    except ValueError as exc:
        logger.error(
            "LLM 模型解析失败（provider key 不可用）: model={} 原因={}",
            model,
            exc,
        )
        raise HTTPException(
            status_code=422,
            detail="未配置默认模型，请在设置中配置 LLM Provider 和默认模型",
        ) from exc
    # 评审 MAJOR-1（#935）：空串 key 可穿透 get_provider_config（仅 None 抛错）——
    # 旧「绝不带空 key 装配」守卫（#821 意图）必须保留，否则 ChatOpenAI 500 复活。
    if not provider_cfg.api_key:
        logger.error(
            "LLM 模型解析失败（api_key 为空）: model={} provider={}",
            model,
            provider,
        )
        raise HTTPException(
            status_code=422,
            detail="未配置默认模型，请在设置中配置 LLM Provider 和默认模型",
        )
    return model, provider_cfg.api_key, provider_cfg.base_url or ""
