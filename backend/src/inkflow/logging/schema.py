"""F57 日志结构化 schema — 脱敏 / 关联 ID / 结构化记录 / loguru 发布入口。

对应 specs/f57-logging-i18n/spec.md §2.2（日志结构字段 + caller_type 枚举 +
必填/可选）与 §12 M1（结构化 schema + 脱敏契约）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast

from loguru import logger
from pydantic import BaseModel, Field

CALLER_TYPES: tuple[str, ...] = ("api", "agent", "llm", "tool", "cli", "mcp", "frontend")

#: caller_type 枚举类型（spec §2.2）
CallerType = Literal["api", "agent", "llm", "tool", "cli", "mcp", "frontend"]

_SENSITIVE_KEYNAME_TOKENS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "key",
        "token",
        "secret",
        "password",
        "authorization",
        "credential",
        "bearer",
        "auth",
    }
)


def _is_sensitive_key(key: str) -> bool:
    """判断键名是否命中敏感词 token（大小写不敏感，子串匹配）。"""
    lowered = key.lower()
    return any(token in lowered for token in _SENSITIVE_KEYNAME_TOKENS)


def _is_sensitive(key: object, sensitive_keys: set[str] | None) -> bool:
    """命中自定义敏感键集合或默认敏感词 token 时返回 True。"""
    if not isinstance(key, str):
        return False
    if sensitive_keys is not None:
        return key in sensitive_keys
    return _is_sensitive_key(key)


def _mask_value(value: object, *, mask: str, sensitive_keys: set[str] | None) -> object:
    """递归脱敏单个值：dict / list 继续处理，其余值原样返回。"""
    if isinstance(value, (dict, list)):
        return mask_fields(value, mask=mask, sensitive_keys=sensitive_keys)
    return value


def mask_fields(
    params: dict | list,
    *,
    mask: str = "****",
    sensitive_keys: set[str] | None = None,
) -> dict | list:
    """脱敏：返回新对象（不改原输入）。sensitive_keys 传入时仅这些键脱敏；
    否则按敏感词 token 判定。递归处理嵌套 dict / list。"""
    if isinstance(params, dict):
        result: dict = {}
        for key, value in params.items():
            if _is_sensitive(key, sensitive_keys):
                result[key] = mask
            else:
                result[key] = _mask_value(value, mask=mask, sensitive_keys=sensitive_keys)
        return result
    return [_mask_value(item, mask=mask, sensitive_keys=sensitive_keys) for item in params]


def bind_correlation(
    correlation_id: str | None = None,
    *,
    trace_id: str | None = None,
    span_id: str | None = None,
) -> dict[str, str]:
    """返回 {correlation_id, trace_id, span_id} 子集（None 值键不出现）。"""
    result: dict[str, str] = {}
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    if trace_id is not None:
        result["trace_id"] = trace_id
    if span_id is not None:
        result["span_id"] = span_id
    return result


class StructuredLogRecord(BaseModel):
    """结构化日志记录（spec §2.2）：必填基础字段 + 可选追踪/业务字段。"""

    model_config = {}  # pydantic v2 默认配置：多余字段忽略

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    level: str
    logger: str
    caller_type: CallerType
    caller_name: str
    event: str
    message_key: str
    params: dict = Field(default_factory=dict)
    correlation_id: str
    trace_id: str | None = None
    span_id: str | None = None
    project_id: int | None = None
    entity_id: str | None = None
    duration_ms: float | None = None
    error_code: str | None = None
    stack: str | None = None


def log_structured(
    *,
    level: str,
    caller_type: CallerType,
    caller_name: str,
    event: str,
    message_key: str,
    message: str = "",
    params: dict | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    project_id: int | None = None,
    entity_id: str | None = None,
    duration_ms: float | None = None,
    error_code: str | None = None,
    stack: str | None = None,
) -> None:
    """构建 StructuredLogRecord → 脱敏 params → logger.bind(extra).log(level, message)。

    extra = model_dump 去掉 timestamp/level/logger 且剔除值为 None 的可选字段；
    correlation_id 缺省时落空串（模型必填，装饰器链路可不传）。
    """
    masked_params = cast(dict, mask_fields(params or {}))
    record = StructuredLogRecord(
        level=level,
        logger="inkflow",
        caller_type=caller_type,
        caller_name=caller_name,
        event=event,
        message_key=message_key,
        params=masked_params,
        correlation_id=correlation_id if correlation_id is not None else "",
        trace_id=trace_id,
        span_id=span_id,
        project_id=project_id,
        entity_id=entity_id,
        duration_ms=duration_ms,
        error_code=error_code,
        stack=stack,
    )
    bound = record.model_dump(
        exclude={"timestamp", "level", "logger"},
        exclude_none=True,
    )
    logger.bind(**bound).log(level, message)
