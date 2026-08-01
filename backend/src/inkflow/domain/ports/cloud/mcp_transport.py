"""云端演进接口 — Agent 传输层（MCPTransport）。

本地实现（Phase 1-3）: stdio（本地进程通信）
云端实现（Phase 4+）: Streamable HTTP

仅定义接口，不实现任何云端功能（PRD §6.5 / spec p0-11-cloud-protocols）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class MCPTransport(Protocol):
    """MCP 传输层接口。

    本地实现: stdio — ``endpoint`` 为本地可执行命令。
    云端实现: Streamable HTTP — ``endpoint`` 为远程 URL。
    """

    async def connect(self, endpoint: str) -> None: ...

    async def call(self, tool: str, args: Mapping[str, Any]) -> Any: ...

    async def close(self) -> None: ...
