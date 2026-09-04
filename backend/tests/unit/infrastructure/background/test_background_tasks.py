"""F44 阶段4 共享后台任务框架契约单测（TDD RED 阶段，契约先行）。

权威来源：fix-010-bug-batch 实施计划任务 2 §A（#456 第一部分：F44 阶段4
FastAPI 后台任务——POST /runs 后台化所需的 fire-and-forget 共享框架）。
本文件为新模块 `infrastructure/background/tasks.py` 定义契约——模块当前
不存在 → 顶部 import 收集期失败（RED）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【spawn_background_task 签名】def spawn_background_task(
   coro, *, key: str | None = None) -> asyncio.Task：
   a. 返回 asyncio.Task；create_task 立即调度——调用方不 await 协程也能跑
      （fire-and-forget；await asyncio.sleep(0) 后协程已执行）。
   b. 实现内部 create_task + add_done_callback(lambda t: t.exception())——
      协程抛异常不产生 'Task exception was never retrieved' 警告（done
      回调已取 exception），spawn 调用本身不抛。
   c. key 非 None → 注册到模块级注册表 _TASKS：get_background_task(key)
      返回该 task；任务完成（done 回调）后从注册表弹出（返回 None）。

2. 【get_background_task 签名】def get_background_task(
   key: str) -> asyncio.Task | None：未注册 → None。

【测试要点】真实 asyncio（pytest.mark.asyncio）；异常任务用
async def boom(): raise RuntimeError(...)；每个用例任务必须完成（await /
断言 done）防 pending task 泄漏警告；注册表跨用例残留：各用例用不同 key。

【RED 预期形态】收集期 ImportError: cannot import name 'background'
from 'inkflow.infrastructure'（模块 inkflow.infrastructure.background.tasks
不存在；等价 ModuleNotFoundError 收集错误，exit 2，0 用例运行）。
"""

import asyncio
import warnings

import pytest

from inkflow.infrastructure import background


@pytest.mark.asyncio
async def test_spawn_fire_and_forget_runs_without_await():
    """契约 1a：返回 asyncio.Task；调用方不 await 协程也执行（fire-and-forget）。"""
    ran: list[str] = []

    async def _work() -> None:
        ran.append("done")

    task = background.spawn_background_task(_work())

    assert isinstance(task, asyncio.Task)
    await asyncio.sleep(0)  # 让出事件循环 → 后台任务已执行
    assert ran == ["done"]
    assert task.done()
    await task  # 收尾：已完成任务直接 await 无阻塞（防 pending 泄漏）


@pytest.mark.asyncio
async def test_spawn_with_key_registers_and_pops_after_done():
    """契约 1c：key 注册表加入 + 任务完成后弹出（get_background_task 返回 None）。"""
    ran: list[str] = []

    async def _work() -> None:
        ran.append("done")

    key = "bg-key-registry"
    task = background.spawn_background_task(_work(), key=key)

    assert background.get_background_task(key) is task
    await asyncio.sleep(0)  # 任务执行完成
    assert ran == ["done"]
    await asyncio.sleep(0)  # done 回调（弹出注册表）执行
    assert background.get_background_task(key) is None
    await task


@pytest.mark.asyncio
async def test_spawn_boom_no_unretrieved_warning():
    """契约 1b：异常任务不产生 'Task exception was never retrieved' 警告
    （done_callback 已取 exception）；spawn 调用本身不抛。"""
    async def _boom() -> None:
        raise RuntimeError("后台任务失败")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        task = background.spawn_background_task(_boom())
        await asyncio.sleep(0)  # 任务执行 → 抛异常 → done 回调排队
        await asyncio.sleep(0)  # done 回调（取 exception）执行
        assert task.done()
        del task  # 触发 GC：异常未被取 → 此处发 'never retrieved' 警告

    messages = [str(w.message) for w in caught if issubclass(w.category, RuntimeWarning)]
    assert not any("never retrieved" in m for m in messages)


@pytest.mark.asyncio
async def test_get_background_task_missing_returns_none():
    """契约 2：未注册 key → None。"""
    assert background.get_background_task("bg-key-missing") is None
