"""LLM 模型/密钥/base_url 装配解析（#758）。

从 deps.py 抽出以控制 900 行护栏；get_agentic_writer_service 空默认模型时
回退首个有 key 且含 chat 模型的 provider，仍无 key → HTTPException(422)。
镜像 deps_chat_agent.py get_chat_agent_service 的 L84-96 空默认回退逻辑。
"""

from __future__ import annotations


def resolve_llm_credentials(global_default: str) -> tuple[str, str, str]:
    """解析 (model, api_key, base_url)：resolve_model + 空默认回退注册表。

    global_default 为空时按 _BUILTIN_PROVIDERS 顺序取首个有 key 且含 chat
    模型的 provider；全部无 key → HTTPException(422)（绝不把空 key 传给
    ChatOpenAI → Missing credentials 500）。
    """
    from fastapi import HTTPException

    from inkflow.domain.services.model_resolution import resolve_model
    from inkflow.infrastructure.llm.provider_config import (
        _BUILTIN_PROVIDERS,
        get_provider_config,
        parse_model_string,
    )

    model = resolve_model(None, None, global_default) or ""
    api_key = ""
    base_url = ""
    if model:
        try:
            provider, _ = parse_model_string(model)
            provider_cfg = get_provider_config(provider)
            api_key = provider_cfg.api_key
            base_url = provider_cfg.base_url or ""
        except ValueError:
            pass
    else:
        for provider in _BUILTIN_PROVIDERS:
            try:
                provider_cfg = get_provider_config(provider)
            except ValueError:
                continue
            fallback_model = provider_cfg.default_model
            if not fallback_model and provider_cfg.models:
                fallback_model = provider_cfg.models[0]
            if fallback_model:
                model = fallback_model
                api_key = provider_cfg.api_key
                base_url = provider_cfg.base_url or ""
                break
        if not api_key:
            raise HTTPException(
                status_code=422,
                detail="未配置默认模型，请在设置中配置 LLM Provider 和默认模型",
            )
    return model, api_key, base_url
