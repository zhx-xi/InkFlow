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

from inkflow.logging.schema import CallerType, log_structured


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
) -> None:
    """记录未捕获异常 ERROR 日志（带耗时 + stack），须在 except 块内调用。"""
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
    )


def instrument(
    fn: Callable[..., object] | None = None,
    *,
    caller_type: CallerType = "api",
    event: str | None = None,
) -> Callable[..., object]:
    """装饰器：支持 @instrument 与 @instrument(caller_type=...) 两种形态。

    入口/成功出口打 DEBUG（出口带 duration_ms），未捕获异常打 ERROR
    （带 stack + error_code="X_UNCAUGHT"）后原样 re-raise。
    caller_name 从 func.__qualname__ 推导；event 默认 func.__name__。
    """

    def decorator(func: Callable[..., object]) -> Callable[..., object]:
        evt = event or func.__name__
        qualname = func.__qualname__
        key = f"log.call.{evt}"

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: object, **kwargs: object) -> object:
                _log_start(caller_type, qualname, evt, key)
                start = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                except Exception:
                    _log_failed(caller_type, qualname, evt, key, start)
                    raise
                _log_done(caller_type, qualname, evt, key, start)
                return result

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: object, **kwargs: object) -> object:
            _log_start(caller_type, qualname, evt, key)
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception:
                _log_failed(caller_type, qualname, evt, key, start)
                raise
            _log_done(caller_type, qualname, evt, key, start)
            return result

        return sync_wrapper

    if fn is None:
        return decorator
    return decorator(fn)
