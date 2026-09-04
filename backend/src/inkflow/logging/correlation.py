"""B4 请求关联 ID ContextVar — X-Correlation-Id 请求级沿用（#496，contract-496 §3）。

契约来源
--------
- contract-496.md §3：ContextVar + get/set（签名逐字）；默认 ""（无请求上下文时
  log_structured 缺省落空串——现状语义零翻转，test_logging_schema 守护）。
- specs/f496-log-page/spec.md §2.2 B4：解析链 显式参数 > contextvar > ""。

说明
----
contextvar 属标准库（logging 子包内使用），无框架依赖；中间件在 api/ 层消费。
"""

from __future__ import annotations

from contextvars import ContextVar, Token

#: 当前请求关联 ID（默认空串 = 无请求上下文）
_correlation_id: ContextVar[str] = ContextVar("inkflow_correlation_id", default="")


def get_request_correlation_id() -> str:
    """返回当前请求关联 ID；无请求上下文时返回默认空串。"""
    return _correlation_id.get()


def set_request_correlation_id(value: str) -> Token[str]:
    """设置当前请求关联 ID，返回真实 contextvars.Token 供 reset（请求结束时必须 reset）。"""
    return _correlation_id.set(value)


def reset_request_correlation_id(token: Token[str]) -> None:
    """按 set 返回的 token 复位 ContextVar（父侧裁定：标准库 Token 无 .reset 方法）。"""
    _correlation_id.reset(token)
