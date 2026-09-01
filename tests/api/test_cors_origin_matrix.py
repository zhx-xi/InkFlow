"""#872 非功能安全 C5③：CORS 来源矩阵契约锁（spec §2.3.2 / ADR-021，S3a 补测）。

CORS 中间件白名单来自 config.server_cors_origins（localhost:5173/127.0.0.1:5173/
localhost:8765/127.0.0.1:8765/null）。本文件把「安全语义」钉成契约：
- 非法 Origin → 响应**不**带 ACAO 头（浏览器拒绝跨域读取）
- 白名单 Origin → 回显 ACAO
- 预检（OPTIONS）跨域：白名单→200+ACAO；非法→非 2xx 且无 ACAO
- 已弃用/未列入的 localhost 端口（如 9999）→ 无 ACAO

注：行为已正确（empirically verified），本文件是**契约锁**（补缺失测试），非缺陷修复。
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app

_ALLOWED = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8765",
    "http://127.0.0.1:8765",
]
_ILLEGAL = [
    "http://evil.com",
    "https://attacker.example",
    "http://localhost:9999",  # 未列入白名单端口
    "http://192.168.1.10:8000",
]


@pytest.fixture
async def cclient() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=httpx.Timeout(30.0),
    ) as c:
        yield c


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", _ALLOWED)
async def test_allowed_origin_echoes_acao(cclient, origin):
    """白名单 Origin → 200 + ACAO 回显（浏览器跨域放行）。"""
    resp = await cclient.get("/health", headers={"Origin": origin})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", _ILLEGAL)
async def test_illegal_origin_has_no_acao(cclient, origin):
    """非法 Origin → 响应**不含** ACAO 头（浏览器拒绝跨域读取，CORS 核心安全语义）。"""
    resp = await cclient.get("/health", headers={"Origin": origin})
    assert resp.status_code == 200  # AC 响应本身可返回，但严禁 ACAO
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_preflight_allowed_origin_returns_acao(cclient):
    """OPTIONS 预检（白名单 Origin）→ 200 + ACAO + 允许方法/头。"""
    resp = await cclient.options(
        "/api/v1/chat/stream",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-inkflow-token",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "POST" in resp.headers.get("access-control-allow-methods", "")


@pytest.mark.asyncio
async def test_preflight_illegal_origin_rejected(cclient):
    """OPTIONS 预检（非法 Origin）→ 非 2xx 且无 ACAO（CORS 预检拒绝）。"""
    resp = await cclient.options(
        "/api/v1/chat/stream",
        headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-inkflow-token",
        },
    )
    assert resp.status_code != 200
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_null_origin_allowed(cclient):
    """null Origin（Electron 生产 file:// 加载，spec §2.3.2）→ 回显 null（允许）。"""
    resp = await cclient.get("/health", headers={"Origin": "null"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "null"
