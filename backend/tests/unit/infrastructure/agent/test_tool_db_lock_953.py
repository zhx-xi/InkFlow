"""#953 RED-1 单元契约：per-event-loop 锁发放（get_tool_db_lock）。

契约（contract-953.md §1a/§2 RED-1）：
- `_tool_db_lock.py` 新增 `get_tool_db_lock()`，按当前 running loop 发放锁
  （WeakKeyDictionary[AbstractEventLoop, asyncio.Lock]）；同循环共享一把、
  异循环各自一把；无 running loop（同步线程）→ 稳定兜底 `_tool_db_lock`。
- 旧模块属性 `_tool_db_lock` 保留为兜底锁，兼容既有 test_tool_db_lock.py
  autouse fixture 的 `_lock_mod._tool_db_lock = asyncio.Lock()` 重置形态。

RED 阶段 `_tool_db_lock.py` 尚未实现 `get_tool_db_lock`（现仅有模块级单锁）。
故本文件在函数体内经 `from ..._tool_db_lock import _tool_db_lock as _lock_mod`
再 `getattr(_lock_mod, "get_tool_db_lock")` 探测——失败以「该函数缺失」的
AttributeError 呈现（单用例 FAIL），而非模块顶层 import 的收集期错误。
【G】用例（#4）仅验证既有 fixture 重置形态零破坏，RED 阶段即应 PASS。

事件循环细节：pytest-asyncio function-scope 循环，每用例自带重置隔离，
勿依赖跨用例锁状态（见 autouse fixture `_reset_tool_db_lock`）。
"""

from __future__ import annotations

import asyncio

import pytest


class ConcurrencyMonitor:
    """统计经锁保护代码段的并发活跃度（max_active）。与 test_tool_db_lock.py 同形态。"""

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def guard(self, *_args: object, **_kw: object) -> None:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1


def _load_lock_module_and_getter():
    """导入锁模块并在函数体内探测 get_tool_db_lock（RED 缺失 → AttributeError）。

    返回 (模块, get_tool_db_lock 函数)。避免模块顶层 import 造成收集期错误：
    探测失败让单个【R】用例 FAIL 而非整文件收集报错。
    """
    from inkflow.infrastructure.agent.tools import _tool_db_lock as _lock_mod

    return _lock_mod, _lock_mod.get_tool_db_lock


@pytest.fixture(autouse=True)
def _reset_tool_db_lock():
    """每测试后重建模块级兜底锁，隔离跨用例/跨循环状态（镜像 test_tool_db_lock.py）。"""
    yield
    try:
        from inkflow.infrastructure.agent.tools import _tool_db_lock as _lock_mod

        _lock_mod._tool_db_lock = asyncio.Lock()
    except Exception:  # 锁模块不存在时 no-op（沿用既有测试的容错形态）
        pass


class TestToolDbLockPerLoop953:
    """#953 RED-1：per-loop 锁发放契约。"""

    @pytest.mark.asyncio
    async def test_get_tool_db_lock_exists_and_per_loop_distinct(self) -> None:
        """【R】主循环 A 与 `asyncio.to_thread(asyncio.run(...))` 的循环 B 锁不同一对象。

        当前实现=模块级单锁：双循环返回同一对象（跨循环 acquire 会抛
        `bound to a different event loop`）；per-loop 实现应各自独立、不互扰。
        """
        _lock_mod, get_lock = _load_lock_module_and_getter()

        # 主循环 A：取 per-loop 锁对象并持锁（定序：A 持锁→B 起→B acquire）
        a_lock = get_lock()
        a_holding = asyncio.Event()
        a_release = asyncio.Event()

        async def hold_a() -> None:
            async with get_lock():
                a_holding.set()
                await a_release.wait()

        task_a = asyncio.create_task(hold_a())
        await a_holding.wait()

        # B：独立线程 + asyncio.run → 新循环 B，取到的锁应与 A 不同对象
        async def in_loop_b() -> bool:
            b_lock = get_lock()
            assert b_lock is not a_lock, (
                "per-loop 锁应随事件循环而异；当前实现=模块级单锁，"
                "双循环返回同一对象（跨循环 acquire 应抛 bound to a different event loop）。"
            )
            async with b_lock:
                return True

        def run_loop_b() -> bool:
            return asyncio.run(in_loop_b())

        assert await asyncio.to_thread(run_loop_b) is True

        # 释放 A，让持锁协程正常收尾；B 循环 acquire 在上述持有中已验证不抛
        a_release.set()
        await task_a

    @pytest.mark.asyncio
    async def test_same_loop_serialization_preserved(self) -> None:
        """【R】同循环两协程并发 `async with get_tool_db_lock()` → max_active==1。

        串行化语义必须保留（同循环共享一把锁），交错让位不重叠。
        """
        _lock_mod, get_lock = _load_lock_module_and_getter()
        monitor = ConcurrencyMonitor()

        async def guarded() -> None:
            async with get_lock():
                await monitor.guard()

        await asyncio.gather(guarded(), guarded())
        assert monitor.max_active == 1, (
            f"同循环两协程经 get_tool_db_lock() 未串行——max_active={monitor.max_active}，"
            "应为 1（同循环应共享一把锁并交错让位）。"
        )

    def test_no_running_loop_falls_back_to_module_lock(self) -> None:
        """【R】同步线程（无 running loop）→ get_tool_db_lock() 返回兜底 `_tool_db_lock`。

        兜底语义 + 兼容既有 `_lock_mod._tool_db_lock = asyncio.Lock()` 重置形态。
        """
        _lock_mod, get_lock = _load_lock_module_and_getter()
        assert get_lock() is _lock_mod._tool_db_lock, (
            "无 running loop（同步线程）应返回兜底 `_tool_db_lock` 现值。"
        )

    def test_module_attr_resettable_compat(self) -> None:
        """【G】模块属性 `_tool_db_lock` 可重置（既有 fixture 形态零破坏）。

        test_tool_db_lock.py 的 autouse fixture 依赖
        `_lock_mod._tool_db_lock = asyncio.Lock()`，本用例守护该赋值面不被破坏；
        不依赖 get_tool_db_lock（RED 阶段即应 PASS）。
        """
        from inkflow.infrastructure.agent.tools import _tool_db_lock as _lock_mod

        original = _lock_mod._tool_db_lock
        new_lock = asyncio.Lock()
        _lock_mod._tool_db_lock = new_lock
        try:
            assert _lock_mod._tool_db_lock is new_lock, (
                "模块属性 `_tool_db_lock` 应可重置（既有 fixture 形态零破坏）。"
            )
        finally:
            _lock_mod._tool_db_lock = original
