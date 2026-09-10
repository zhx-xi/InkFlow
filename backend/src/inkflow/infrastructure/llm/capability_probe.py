"""F59-M2 能力探针（spec §5.4/§5.5）—— 三极链 + 超能力软降级。

- supports_reasoning_for_model: 手动覆盖 > 模型级 supports_reasoning 表 >
  provider 级 get_supported_openai_params 兜底；探针永不抛异常。
- apply_reasoning_effort: 构造点统一入口——default/None 不发送；支持则注入；
  不支持且非 none 则剥离并发 WARNING；探测不支持且 none → 剥离且不告警
  （#1054：模型本就不思考，none 天然满足）。
  决策点包含翻译器门禁：探测链判 True 但 litellm 翻译器无 reasoning 参数时
  软降级（reason=translator_unsupported），绝不冒泡（#1044 D4）。
- to_chat_model_kwargs: 为 ChatLiteLLM 传输形态适配器——构造点必须串联
  apply_reasoning_effort 与 to_chat_model_kwargs 两者（#1044 D1）。
"""

from __future__ import annotations

import litellm

from inkflow.logging import log_structured

# 思考参数族：litellm 翻译器声明任一即视为可承载（§5.4 第 3 级）
_REASONING_PARAM_KEYS: frozenset[str] = frozenset({"thinking", "reasoning_effort"})


def _provider_supported_params(
    model_full: str, provider: str | None = None
) -> list[str] | None:
    """litellm 参数翻译器声明的可传参数（去 provider 前缀查询表）；空/异常 → None。"""
    try:
        segments = model_full.split("/", 1)
        params = litellm.get_supported_openai_params(
            segments[-1],
            custom_llm_provider=provider or (segments[0] if segments else None),
        )
    except Exception:
        return None
    else:
        return params or None


def _translator_supports_reasoning(model_full: str, provider: str | None = None) -> bool:
    """litellm 翻译器是否接受思考参数；空/异常 → False（绝不冒泡）。"""
    params = _provider_supported_params(model_full, provider)
    if not params:
        return False
    return any(key in params for key in _REASONING_PARAM_KEYS)


def _warn_downgrade(model_full: str, effort: str, reason: str) -> None:
    """§5.5 软降级 WARNING（message_key 不变；params 新增 reason 供排查分流）。"""
    log_structured(
        level="WARNING",
        caller_type="llm",
        caller_name="capability_probe.apply_reasoning_effort",
        event="reasoning_downgrade",
        message_key="log.check.reasoning_downgrade",
        message=(
            f"reasoning effort downgraded: model={model_full} effort={effort} reason={reason}"
        ),
        params={"model": model_full, "effort": effort, "reason": reason},
    )


def supports_reasoning_for_model(
    model_full: str,
    provider: str | None = None,
    manual: bool | None = None,
) -> bool:
    """三极能力链（§5.4）—— 返回纯 bool，绝不泄漏上游网关类型。

    1. 注册表手动覆盖（manual is not None）→ 短接，不触碰上游 SDK；
    2. 模型级 supports_reasoning(全名) → True 即停；
    3. provider 级 get_supported_openai_params(去前缀名) 含
       thinking / reasoning_effort 任一 → True；否则 False。
    任意内部异常 → False（GET /provider-configs 逐条计算不得打穿）。
    """
    if manual is not None:
        return bool(manual)
    try:
        if litellm.supports_reasoning(model_full):
            return True
    except Exception:
        return False
    try:
        return _translator_supports_reasoning(model_full, provider)
    except Exception:
        return False


def apply_reasoning_effort(
    kwargs: dict[str, object],
    *,
    model_full: str,
    effort: str | None,
    provider: str | None = None,
    manual: bool | None = None,
) -> dict[str, object]:
    """构造点统一注入入口（§5.2/§5.5）—— 返回新 dict，绝不就地改输入。

    - effort 为 None / "default" → 返回副本且不含 reasoning_effort 键；
    - 能力支持 → out["reasoning_effort"] = effort（含 "none" 透传）；
    - 能力不支持且 effort 非 {"default", "none"} → 剥离 + WARNING（软降级）；
    - 能力不支持且 effort == "none" → 剥离且不告警（#1054：none 天然满足；
      翻译器无该参数时注入即断流）。
    """
    out = dict(kwargs)
    if effort is None or effort == "default":
        return out
    supported = supports_reasoning_for_model(
        model_full,
        provider=provider,
        manual=manual,
    )
    if not supported:
        if effort == "none":
            # #1054：模型本就不思考，none 天然满足 → 剥离且不告警（翻译器
            # 不含该参数时注入即 UnsupportedParamsError 断流）
            return out
        _warn_downgrade(model_full, effort, "capability_unsupported")
        return out
    if manual is None and not _translator_supports_reasoning(model_full, provider):
        # #1044 D4：探测链判 True 但翻译器无该参数 → SDK 本地 UnsupportedParamsError（断流）
        _warn_downgrade(model_full, effort, "translator_unsupported")
        return out
    out["reasoning_effort"] = effort
    return out


def to_chat_model_kwargs(kwargs: dict[str, object]) -> dict[str, object]:
    """决策 dict → ChatLiteLLM 构造 kwargs（#1044 D1）。
    ChatLiteLLM（langchain-litellm 0.7.1）pydantic 字段面无 reasoning_effort、
    未配 extra → 顶层 kwargs 被静默丢弃；参数进 litellm 的唯一通道是 model_kwargs
    （litellm.py:475 **self.model_kwargs）。无决策键时原样返回副本。

    #1039 Q1=A：allowed_openai_params 同法搬进 model_kwargs——manual 覆盖注入
    时旁路 litellm SDK 本地门禁（表 False 模型直抛 UnsupportedParamsError）；
    该键仅由构造点在 manual is True 注入成功时塞入，自动路径不含。
    """
    out = dict(kwargs)
    effort = out.pop("reasoning_effort", None)
    allowed = out.pop("allowed_openai_params", None)
    if effort is None and allowed is None:
        return out
    existing = out.get("model_kwargs")
    model_kwargs: dict[str, object] = dict(existing) if isinstance(existing, dict) else {}
    if effort is not None:
        model_kwargs["reasoning_effort"] = effort
    if allowed is not None:
        model_kwargs["allowed_openai_params"] = allowed
    out["model_kwargs"] = model_kwargs
    return out
