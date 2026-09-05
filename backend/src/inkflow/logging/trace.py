"""#931 OTel/W3C traceparent 原语 — TraceContext + id 生成 + 解析 + contextvar。

契约来源
--------
- backend/tests/unit/logging/test_logging_trace_931.py（模块 docstring 为权威规格）：
  冻结 dataclass、secrets 随机 hex、W3C traceparent 严格解析、contextvar
  get/set/reset（与 correlation.py 同形态，标准库 contextvars，无框架依赖）。
- W3C Trace Context：``00-<trace-id 32hex>-<span-id 16hex>-<flags 2hex>``；
  trace/span 全零为无效值；版本仅 00；字段小写 hex；多余段按非法。

设计决策
--------
parse_traceparent 返回「继承 trace、开子 span」的 ctx（parent_span_id = 头 span_id），
调用方（中间件/客户端）负责在无头/非法头时兜底生成新根——绝不抛异常、绝不部分采信。
"""

from __future__ import annotations

import re
import secrets
from contextvars import ContextVar, Token
from dataclasses import dataclass

#: W3C traceparent 严格形态（小写 hex；version=00；恰好 4 段）
_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


@dataclass(frozen=True)
class TraceContext:
    """一次 trace 的 span 上下文（根 span 时 parent_span_id 为空串）。"""

    trace_id: str
    span_id: str
    parent_span_id: str


def new_trace_id() -> str:
    """生成 32 位小写 hex trace_id（secrets 随机，非全零）。"""
    while True:
        value = secrets.token_hex(16)
        if int(value, 16) != 0:
            return value


def new_span_id() -> str:
    """生成 16 位小写 hex span_id（secrets 随机，非全零）。"""
    while True:
        value = secrets.token_hex(8)
        if int(value, 16) != 0:
            return value


def make_traceparent(ctx: TraceContext) -> str:
    """TraceContext → W3C traceparent（flags=01 采样）。"""
    return f"00-{ctx.trace_id}-{ctx.span_id}-01"


def parse_traceparent(value: str | None) -> TraceContext | None:
    """严格解析 traceparent：合法 → 同 trace + 新 span + parent=头 span；否则 None。

    拒绝：非 str / 非 00 版本 / 大写 hex / 全零 trace 或 span / 非恰好 4 段。
    flags 段仅校验为 2 位 hex（01/ff 等均透传接受）。
    """
    if not isinstance(value, str):
        return None
    match = _TRACEPARENT_RE.fullmatch(value)
    if match is None:
        return None
    trace_id, span_id = match.group(1), match.group(2)
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return None
    return TraceContext(
        trace_id=trace_id,
        span_id=new_span_id(),
        parent_span_id=span_id,
    )


#: 当前请求/任务级 trace 上下文（默认 None = 无 trace 上下文）
_trace_context: ContextVar[TraceContext | None] = ContextVar("inkflow_trace_context", default=None)


def get_trace_context() -> TraceContext | None:
    """返回当前 trace 上下文；无上下文时返回 None。"""
    return _trace_context.get()


def set_trace_context(ctx: TraceContext) -> Token[TraceContext | None]:
    """设置当前 trace 上下文，返回真实 contextvars.Token 供 reset。"""
    return _trace_context.set(ctx)


def reset_trace_context(token: Token[TraceContext | None]) -> None:
    """按 set 返回的 token 复位 trace ContextVar。"""
    _trace_context.reset(token)
