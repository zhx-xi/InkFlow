"""#837/#953 Agent 工具 DB 访问串行化锁——按运行事件循环发放（per-loop 锁）。

#837 背景：所有走 db 的 agent 工具（读/写/删除/审计）在同一请求共享同一
AsyncSession（deps_chat_agent.py 每请求一个 db）。deepagents 用 Send API 并行分发
多个 tool_calls 时，工具在单一事件循环交错执行同一 session → 事务状态机破坏。

#953 演进（原 #837 方案 A 模块级单锁）：asyncio.Lock 单例会把自身绑定到首个
acquire 它的事件循环；book run 的 sync 桥（_make_sync_wrapper 在独立 worker 线程
+ 新事件循环上运行工具协程）跨循环 acquire 同一把锁会抛 RuntimeError（bound to
a different event loop）→ book run 崩溃。故改为 per-loop 发放：同循环共享一把锁
（并行 tool_calls 仍被串行化），异循环各自一把（互不阻塞、不跨循环 acquire）。

- get_tool_db_lock()：按当前运行事件循环（asyncio.get_running_loop）取/建 per-loop
  锁（WeakKeyDictionary key=loop 对象，loop 回收锁随散）；无运行中循环（同步线程/
  sync 桥无 loop 分支兜底路径）→ 返回模块属性 _tool_db_lock 现值。
- 消费方工具模块以
  `from ... import _tool_db_lock as _tool_db_lock_mod` 引用模块并
  `async with _tool_db_lock_mod.get_tool_db_lock():` 包裹整个工具 func 体
  （模块属性引用，测试可重置——勿用 `from ... import _tool_db_lock` 值绑定）。
- 旧模块属性 `_tool_db_lock` 保留为兜底锁：兼容既有 test_tool_db_lock.py autouse
  fixture `_lock_mod._tool_db_lock = asyncio.Lock()` 的重置形态（零破坏）。
"""

from __future__ import annotations

import asyncio
import weakref

_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)
_tool_db_lock = asyncio.Lock()


def get_tool_db_lock() -> asyncio.Lock:
    """按当前运行事件循环发放锁：同循环共享一把、异循环各自一把。

    无运行中循环（同步线程，如 harness sync 桥无 loop 分支）→ 返回模块属性
    `_tool_db_lock` 现值（进程内唯一兜底锁，兼容既有测试的重置形态）。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return _tool_db_lock
    lock = _locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _locks[loop] = lock
    return lock
