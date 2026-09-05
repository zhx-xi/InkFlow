"""F57 @instrument 装饰器 — 函数入口 / 出口 / 异常的结构化日志包装。

对应 specs/f57-logging-i18n/spec.md §4.1：functools.wraps 保签名、
async 感知分派、异常记录后原样 re-raise、message_key 统一 log.call.*。
"""

from __future__ import annotations

import functools
import inspect
import time
import traceback
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, overload

from inkflow.logging.schema import CallerType, log_structured

_P = ParamSpec("_P")
_R = TypeVar("_R")

#: 大文本字段键名集合：此类字段的值不进入失败日志的 params 摘要（防刷屏/泄全文）。
#: 含 description（大纲/角色等长文本描述，RED 契约锁定排除），子串命中。
_BIG_TEXT_KEYS: frozenset[str] = frozenset(
    {"content", "text", "prompt", "body", "draft", "markdown", "html", "code", "description"}
)

#: 摘要 str 值截断后追加的省略号（U+2026 单字符）。
_ELLIPSIS = "…"


def _trunc(value: str) -> str:
    """截断长字符串：超过 100 字符时取前 100 字符并追加省略号。"""
    if len(value) <= 100:
        return value
    return value[:100] + _ELLIPSIS


def _is_big_text_key(key: str) -> bool:
    """判断字段名是否命中大文本键 token（子串匹配，如 project_description 命中）。"""
    lowered = key.lower()
    return any(token in lowered for token in _BIG_TEXT_KEYS)


def _scalar_summary(
    args: tuple[Any, ...], kwargs: dict[str, Any], func: Callable[..., Any]
) -> dict[str, Any]:
    """按调用签名顺序提取标量实参摘要（最多 8 键）。

    - 用 inspect.signature(func).bind 还原实参到形参名；bind 失败（如 partial/兼容
      形参不齐）时降级为只取 kwargs，不抛新异常。
    - str/int/float/bool 标量入摘要；None/dict/list/其它复杂对象跳过；Pydantic
      模型（鸭子判定 hasattr(model_fields)）展开其 model_fields 中标量字段，
      大文本键（_BIG_TEXT_KEYS 子串命中，如 description）排除，str 值截断 ≤100+…。
    """
    summary: dict[str, Any] = {}
    try:
        bound = inspect.signature(func).bind(*args, **kwargs)
        argparams: dict[str, Any] = dict(bound.arguments)
    except TypeError:
        argparams = dict(kwargs)
    for key, value in argparams.items():
        if len(summary) >= 8:
            break
        value_type = type(value)
        if hasattr(value_type, "model_fields"):
            for field_name in value_type.model_fields:
                if len(summary) >= 8:
                    break
                if _is_big_text_key(field_name):
                    continue
                field_value = getattr(value, field_name, None)
                if isinstance(field_value, str):
                    summary[field_name] = _trunc(field_value)
                elif isinstance(field_value, (int, float, bool)):
                    summary[field_name] = field_value
            continue
        if isinstance(value, str):
            if _is_big_text_key(key):
                continue
            summary[key] = _trunc(value)
        elif isinstance(value, (int, float, bool)):
            summary[key] = value
    return summary


def _log_start(caller_type: CallerType, caller_name: str, evt: str, key: str) -> None:
    """记录函数入口 DEBUG 日志。"""
    log_structured(
        level="DEBUG",
        caller_type=caller_type,
        caller_name=caller_name,
        event=evt,
        message_key=key,
        message=f"{evt} started",
    )


def _log_done(caller_type: CallerType, caller_name: str, evt: str, key: str, start: float) -> None:
    """记录函数成功出口 DEBUG 日志（带耗时）。"""
    log_structured(
        level="DEBUG",
        caller_type=caller_type,
        caller_name=caller_name,
        event=evt,
        message_key=key,
        message=f"{evt} completed",
        duration_ms=(time.perf_counter() - start) * 1000,
    )


def _log_failed(
    caller_type: CallerType,
    caller_name: str,
    evt: str,
    key: str,
    start: float,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    func: Callable[..., Any],
    exc: Exception,
) -> None:
    """记录未捕获异常 ERROR 日志（带耗时 + stack + 入参摘要），须在 except 块内调用。"""
    log_structured(
        level="ERROR",
        caller_type=caller_type,
        caller_name=caller_name,
        event=evt,
        message_key=key,
        message=f"{evt} failed",
        duration_ms=(time.perf_counter() - start) * 1000,
        stack=traceback.format_exc(),
        error_code="X_UNCAUGHT",
        params={
            **_scalar_summary(args, kwargs, func),
            "error_type": type(exc).__name__,
            "error": _trunc(str(exc)),
        },
    )


def _log_expected(
    caller_type: CallerType,
    caller_name: str,
    evt: str,
    key: str,
    start: float,
    status_code: int,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    func: Callable[..., Any],
    exc: Exception,
) -> None:
    """记录预期 HTTPException（status_code < 500）：WARN + E_HTTP_<status> + 入参摘要。"""
    log_structured(
        level="WARN",
        caller_type=caller_type,
        caller_name=caller_name,
        event=evt,
        message_key=key,
        message=f"{evt} failed",
        duration_ms=(time.perf_counter() - start) * 1000,
        error_code=f"E_HTTP_{status_code}",
        params={
            **_scalar_summary(args, kwargs, func),
            "http_status": status_code,
            "detail": _trunc(str(getattr(exc, "detail", ""))),
        },
    )


def _log_stream_broken(
    caller_type: CallerType,
    caller_name: str,
    evt: str,
    key: str,
    start: float,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    func: Callable[..., Any],
) -> None:
    """记录 async 生成器流中断：WARN + X_STREAM_BROKEN + 入参摘要（流级失败，非函数级崩溃）。"""
    log_structured(
        level="WARN",
        caller_type=caller_type,
        caller_name=caller_name,
        event=evt,
        message_key=key,
        message=f"{evt} stream broken",
        duration_ms=(time.perf_counter() - start) * 1000,
        error_code="X_STREAM_BROKEN",
        params={**_scalar_summary(args, kwargs, func)},
    )


@overload
def instrument(fn: Callable[_P, _R]) -> Callable[_P, _R]: ...


@overload
def instrument(
    *,
    caller_type: CallerType = "api",
    event: str | None = None,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]: ...


def instrument(
    fn: Callable[..., Any] | None = None,
    *,
    caller_type: CallerType = "api",
    event: str | None = None,
) -> Callable[..., Any]:
    """装饰器：支持 @instrument 与 @instrument(caller_type=...) 两种形态。

    入口/成功出口打 DEBUG（出口带 duration_ms），未捕获异常打 ERROR
    （带 stack + error_code="X_UNCAUGHT"）后原样 re-raise。
    caller_name 从 func.__qualname__ 推导；event 默认 func.__name__。
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        evt = event or func.__name__
        qualname = func.__qualname__
        key = f"log.call.{evt}"

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                _log_start(caller_type, qualname, evt, key)
                start = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    status = getattr(exc, "status_code", None)
                    if isinstance(status, int) and status < 500:
                        _log_expected(
                            caller_type, qualname, evt, key, start, status, args, kwargs, func, exc
                        )
                    else:
                        _log_failed(caller_type, qualname, evt, key, start, args, kwargs, func, exc)
                    raise
                _log_done(caller_type, qualname, evt, key, start)
                return result

            return async_wrapper

        if inspect.isasyncgenfunction(func):

            @functools.wraps(func)
            async def asyncgen_wrapper(*args: Any, **kwargs: Any) -> Any:
                _log_start(caller_type, qualname, evt, key)
                start = time.perf_counter()
                try:
                    async for item in func(*args, **kwargs):
                        yield item
                except Exception:
                    _log_stream_broken(caller_type, qualname, evt, key, start, args, kwargs, func)
                    raise
                _log_done(caller_type, qualname, evt, key, start)

            return asyncgen_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            _log_start(caller_type, qualname, evt, key)
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if isinstance(status, int) and status < 500:
                    _log_expected(
                        caller_type, qualname, evt, key, start, status, args, kwargs, func, exc
                    )
                else:
                    _log_failed(caller_type, qualname, evt, key, start, args, kwargs, func, exc)
                raise
            _log_done(caller_type, qualname, evt, key, start)
            return result

        return sync_wrapper

    if fn is None:
        return decorator
    return decorator(fn)
