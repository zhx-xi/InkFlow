"""P0-11 云端接口 Protocol 单测 — import + Mock 签名验证 + dataclass 实例化。

纯单元测试（无 I/O）。验证契约可被消费方使用：可 import、Mock 可实例化、
方法签名可调用、数据类型默认值符合本地模式。
"""

from __future__ import annotations

import inspect
from datetime import datetime
from unittest.mock import Mock

import pytest

from inkflow.domain.ports.cloud import (
    AuthCredentials,
    AuthProtocol,
    DatabaseProtocol,
    MCPTransport,
    StorageProtocol,
    SyncProtocol,
    SyncResult,
    UserIdentity,
    UserProfile,
    UserProtocol,
)

# ── import 与聚合导出 ──


def test_all_cloud_protocols_importable() -> None:
    """6 个 Protocol 均可从聚合入口 import，且全部在 __all__ 中。"""
    import inkflow.domain.ports.cloud as cloud

    for name in (
        "AuthProtocol",
        "DatabaseProtocol",
        "StorageProtocol",
        "UserProtocol",
        "SyncProtocol",
        "MCPTransport",
    ):
        assert hasattr(cloud, name), f"cloud 包缺少 {name}"
        assert name in cloud.__all__, f"{name} 不在 cloud.__all__ 中"


# ── Mock 签名验证（每个 Protocol 的方法存在且为 async）──


@pytest.mark.parametrize(
    ("protocol", "methods"),
    [
        (AuthProtocol, ["authenticate", "verify_token"]),
        (DatabaseProtocol, ["connect", "execute", "close"]),
        (StorageProtocol, ["save", "load", "delete"]),
        (UserProtocol, ["get_user", "list_users"]),
        (SyncProtocol, ["push", "pull"]),
        (MCPTransport, ["connect", "call", "close"]),
    ],
)
def test_protocol_methods_are_async(protocol: type, methods: list[str]) -> None:
    """每个 Protocol 的方法签名存在且为 async 协程函数。"""
    for name in methods:
        member = getattr(protocol, name)
        assert callable(member), f"{protocol.__name__}.{name} 应可调用"
        assert inspect.iscoroutinefunction(member), f"{protocol.__name__}.{name} 应为 async 函数"


# ── dataclass 实例化与本地模式默认值 ──


def test_auth_credentials_defaults_local_trust() -> None:
    """AuthCredentials 本地模式默认空凭据（LocalTrust）。"""
    creds = AuthCredentials()
    assert creds.token == ""
    assert creds.user_id == ""


def test_user_identity_requires_user_id() -> None:
    identity = UserIdentity(user_id="u1")
    assert identity.display_name == ""


def test_user_profile_default_tenant_is_local() -> None:
    """UserProfile 本地模式 tenant_id 恒为 "local"（SingleUser）。"""
    profile = UserProfile(user_id="u1", display_name="本地用户")
    assert profile.tenant_id == "local"


def test_sync_result_noop_defaults() -> None:
    """SyncResult 本地 noop 模式默认值。"""
    result = SyncResult(ok=True)
    assert result.rev == ""
    assert result.error == ""


# ── 异步方法可 await（Mock 实例）──


@pytest.mark.asyncio
async def test_mock_instances_awaitable() -> None:
    """Mock(spec=Protocol) 实例的 async 方法可被 await（契约可被消费方调用）。"""
    auth = Mock(spec=AuthProtocol)
    db = Mock(spec=DatabaseProtocol)
    storage = Mock(spec=StorageProtocol)
    user = Mock(spec=UserProtocol)
    sync = Mock(spec=SyncProtocol)
    mcp = Mock(spec=MCPTransport)

    await auth.authenticate(AuthCredentials())
    await auth.verify_token("t")
    await db.connect()
    await db.execute("SELECT 1")
    await db.close()
    await storage.save("k", b"data")
    await storage.load("k")
    await storage.delete("k")
    await user.get_user("u1")
    await user.list_users()
    await sync.push("p1", {"rev": "1"})
    await sync.pull("p1", since=datetime(2026, 1, 1))
    await mcp.connect("stdio")
    await mcp.call("tool", {"arg": 1})
    await mcp.close()
