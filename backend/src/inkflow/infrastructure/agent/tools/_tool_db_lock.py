"""#837 Agent 工具 DB 访问串行化锁——模块级单例（共享）。

所有走 db 的 agent 工具（读/写/删除/审计）在同一请求共享同一 AsyncSession
（deps_chat_agent.py 每请求一个 db）。deepagents 用 Send API 并行分发多个
tool_calls 时，工具在单一事件循环交错执行同一 session → 事务状态机破坏。

方案 A：一个模块级 asyncio.Lock 单例，跨所有工具实例共享；各工具模块以
`from ... import _tool_db_lock as _tool_db_lock_mod` 引用模块并
`async with _tool_db_lock_mod._tool_db_lock:` 包裹整个工具 func 体
（模块属性引用，测试可重置——勿用 `from ... import _tool_db_lock` 值绑定）。
"""

from __future__ import annotations

import asyncio

_tool_db_lock = asyncio.Lock()
