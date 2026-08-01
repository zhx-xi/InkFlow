"""云端演进接口聚合导出 — domain/ports/cloud。

仅定义接口（typing.Protocol + dataclass），不实现任何云端功能。
本地路径（Phase 1-3）不引用本模块；Phase 4+ 云端实现消费这些契约。
"""

from __future__ import annotations

from inkflow.domain.ports.cloud.auth import (
    AuthCredentials,
    AuthProtocol,
    UserIdentity,
)
from inkflow.domain.ports.cloud.database import DatabaseProtocol
from inkflow.domain.ports.cloud.mcp_transport import MCPTransport
from inkflow.domain.ports.cloud.storage import StorageProtocol
from inkflow.domain.ports.cloud.sync import SyncProtocol, SyncResult
from inkflow.domain.ports.cloud.user import UserProfile, UserProtocol

__all__ = [
    # auth
    "AuthProtocol",
    "AuthCredentials",
    "UserIdentity",
    # database
    "DatabaseProtocol",
    # storage
    "StorageProtocol",
    # user
    "UserProtocol",
    "UserProfile",
    # sync
    "SyncProtocol",
    "SyncResult",
    # mcp transport
    "MCPTransport",
]
