"""云端演进接口 — 认证（AuthProtocol）。

本地实现（Phase 1-3）: LocalTrust（免认证，恒通过）
云端实现（Phase 4+）: JWTAuth（OAuth 2.1）

仅定义接口，不实现任何云端功能（PRD §6.5 / spec p0-11-cloud-protocols）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AuthCredentials:
    """认证凭据。本地模式可为空（LocalTrust）。"""

    token: str = ""
    user_id: str = ""


@dataclass(frozen=True)
class UserIdentity:
    """认证后的用户身份。"""

    user_id: str
    display_name: str = ""


class AuthProtocol(Protocol):
    """认证接口。

    本地实现: LocalTrust — ``authenticate`` 恒返回默认身份，``verify_token`` 返回默认身份。
    云端实现: JWTAuth — OAuth 2.1 签发/校验 JWT。
    """

    async def authenticate(self, credentials: AuthCredentials) -> UserIdentity: ...

    async def verify_token(self, token: str) -> UserIdentity: ...
