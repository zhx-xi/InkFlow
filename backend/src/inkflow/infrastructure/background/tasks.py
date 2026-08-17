"""共享 fire-and-forget 后台任务框架（F44 阶段4 #456）。"""

from __future__ import annotations

import asyncio

_TASKS: dict[str, asyncio.Task] = {}


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


def get_background_task(key: str) -> asyncio.Task | None:
    """查询注册表（key → 运行中任务；未注册/已完成 → None）。"""
    return _TASKS.get(key)
