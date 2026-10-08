"""共享 fire-and-forget 后台任务框架（F44 阶段4 #456）。"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable
from typing import Protocol

_TASKS: dict[str, asyncio.Task] = {}


class ClosableSession(Protocol):
    """可显式归还连接的异步会话（结构契约：`AsyncSession.close()`）。"""

    async def close(self) -> None: ...


def spawn_background_task(
    coro: object,
    *,
    key: str | None = None,
) -> asyncio.Task:
    """fire-and-forget：create_task + done_callback 防 GC/防未取异常；key 注册表（完成后弹出）。"""
    task: asyncio.Task = asyncio.create_task(coro)  # type: ignore[arg-type]  # 鸭子类型：调用方保证传 coroutine
    task.add_done_callback(lambda t: t.exception())  # 防 'Task exception was never retrieved'
    if key is not None:
        _TASKS[key] = task
        task.add_done_callback(lambda t: _TASKS.pop(key, None))
    return task


async def run_with_session_release(
    coro: Awaitable[None],
    session: ClosableSession,
) -> None:
    """后台任务体包装：结束后**显式归还**请求 session 的连接（#1530）。

    后台 fire-and-forget 任务常复用请求级 session（`Depends(get_db)` 的请求会话）：
    请求返回时依赖清理会关闭该会话，但任务此后若继续在其上 `execute`，SQLAlchemy
    会重新 checkout 一条连接，而**任务体从不 `close()`** → 连接既不归还也不释放，
    被 GC 回收时打印 `The garbage collector is trying to clean up non-checked-in
    connection`（长会话 / 并发下连接持续被扣住可致池耗尽）。

    本包装保证无论正常结束还是异常，任务跑完即 `close()` 归还连接（幂等：与
    `get_db` 的依赖清理重复调用无副作用）。对照范式见
    `infrastructure/context/summary_background_refresh.py`（后台任务自持 session）。

    Args:
        coro: 后台任务体协程（在请求 session 上执行）。
        session: 该协程使用的请求 session（结构契约：提供 `async close()`）。
    """
    try:
        await coro
    finally:
        with contextlib.suppress(Exception):
            await session.close()


def get_background_task(key: str) -> asyncio.Task | None:
    """查询注册表（key → 运行中任务；未注册/已完成 → None）。"""
    return _TASKS.get(key)
