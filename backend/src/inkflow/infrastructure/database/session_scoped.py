"""按调用开短会话的仓储代理（#1539）。

长活单例服务（如索引重建编排 `IndexRebuildService`，模块级缓存以共享进度状态）
需要仓储依赖，但**不得常驻数据库连接**：本代理在一次方法调用内新建 session、返回前
即归还连接（不跨调用复用会话），令模块单例「只保留服务对象、不持有 session」。

同族范式：`infrastructure/background/tasks.py::run_with_session_release`（#1530，
请求 session 显式归还）与 `infrastructure/context/summary_background_refresh.py`
（后台任务自持 `async with` 生命周期）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class SessionScopedRepository:
    """仓储代理：每次方法调用新建 session 并在返回前归还连接（#1539）。

    Args:
        repo_factory: `session -> 仓储实例`（如 `SQLiteProjectRepository`）。
        session_factory: 返回会话的对象（可调用于 `async with`，如 `async_session_factory`）。

    结构契约：转发任意**非私有**协程方法（`get` / `list_all` / ...）到当次调用独立
    会话上的仓储实例，故仅需调用方实际用到的方法存在即可（如
    `ProjectRepositoryProtocol.get` / `.list_all`）。`Any` 为动态转发所需
    （透传任意仓储方法签名），非泛化抽象。
    """

    def __init__(
        self,
        repo_factory: Callable[..., Any],  # 仓储类构造：session → 实例
        session_factory: Callable[..., Any],  # 会话工厂：返回异步上下文管理器
    ) -> None:
        self._repo_factory = repo_factory
        self._session_factory = session_factory

    def __getattr__(self, name: str) -> Any:
        """转发任意非私有方法；每次调用独立会话、返回前归还连接（#1539）。"""
        if name.startswith("_"):
            raise AttributeError(name)

        async def _call(*args: Any, **kwargs: Any) -> Any:
            async with self._session_factory() as session:
                return await getattr(self._repo_factory(session), name)(*args, **kwargs)

        return _call
