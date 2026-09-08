"""F59-M2 能力探针（spec §5.4/§5.5）—— 三极链 + 超能力软降级。

- supports_reasoning_for_model: 手动覆盖 > 模型级 supports_reasoning 表 >
  provider 级 get_supported_openai_params 兜底；探针永不抛异常。
- apply_reasoning_effort: 构造点统一入口——default/None 不发送；支持则注入；
  不支持且非 none 则剥离并发 WARNING；none 透传（显式关闭语义）。
"""

from __future__ import annotations

import litellm

from inkflow.logging import log_structured


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
        segments = model_full.split("/", 1)
        model_without_prefix = segments[-1]
        params = litellm.get_supported_openai_params(
            model_without_prefix,
            custom_llm_provider=provider or (segments[0] if segments else None),
        )
        if not params:
            return False
        supported = {"thinking", "reasoning_effort"}
        return any(key in params for key in supported)
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
    - 能力不支持且 effort == "none" → 透传（显式关闭由上游处理，不告警）。
    """
    out = dict(kwargs)
    if effort is None or effort == "default":
        return out
    supported = supports_reasoning_for_model(
        model_full,
        provider=provider,
        manual=manual,
    )
    if not supported and effort != "none":
        log_structured(
            level="WARNING",
            caller_type="llm",
            caller_name="capability_probe.apply_reasoning_effort",
            event="reasoning_downgrade",
            message_key="log.check.reasoning_downgrade",
            message=f"reasoning effort downgraded: model={model_full} effort={effort}",
            params={"model": model_full, "effort": effort},
        )
        return out
    out["reasoning_effort"] = effort
    return out
