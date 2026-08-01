"""云端演进接口 — 数据库访问（DatabaseProtocol）。

本地实现（Phase 1-3）: SQLiteAdapter（aiosqlite）
云端实现（Phase 4+）: PostgreSQLAdapter

仅定义接口，不实现任何云端功能（PRD §6.5 / spec p0-11-cloud-protocols）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class DatabaseProtocol(Protocol):
    """数据库访问接口。

    本地实现: SQLiteAdapter — 现有 async engine + session factory 的薄封装。
    云端实现: PostgreSQLAdapter — 连接池 + 事务管理。

    ``execute`` 为通用 SQL 执行入口，对上层 Repository 透明。
    """

    async def connect(self) -> None: ...

    async def execute(
        self,
        statement: str,
        params: Mapping[str, Any] | None = None,
    ) -> Any: ...

    async def close(self) -> None: ...
