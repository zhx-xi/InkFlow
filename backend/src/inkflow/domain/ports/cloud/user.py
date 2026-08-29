"""云端演进接口 — 用户管理（UserProtocol）。

本地实现（Phase 1-3）: SingleUser（无用户概念，返回默认本地用户）
云端实现（Phase 4+）: MultiTenant（多租户）

仅定义接口，不实现任何云端功能（PRD §6.5 / spec f52-cloud-protocol）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class UserProfile:
    """用户资料。本地模式 tenant_id 恒为 "local"。"""

    user_id: str
    display_name: str
    tenant_id: str = "local"


class UserProtocol(Protocol):
    """用户管理接口。

    本地实现: SingleUser — ``get_user`` 返回默认本地用户，``list_users`` 返回单元素列表。
    云端实现: MultiTenant — 租户隔离的用户查询。
    """

    async def get_user(self, user_id: str) -> UserProfile | None: ...

    async def list_users(self) -> list[UserProfile]: ...
