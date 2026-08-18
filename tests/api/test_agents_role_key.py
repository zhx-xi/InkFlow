"""#473 R1 Agent role_key 透出契约测试（角色集合单一来源前置）。

拆分自 tests/api/test_agents_api.py——追加 TestRoleKeyExposure 后该文件
980 行超 900 行护栏（CI check_file_length），role_key 契约独立成文件，
自带 _seed_agent helper 副本（与父文件同构）。

契约（#473 R1，与 test_agents_api.py 设计假设 #17 一致）：
- GET /api/v1/agents 列表 与 GET /api/v1/agents/{id} 详情 对内置 Agent 透出
  role_key 字段（str | None）——builtin=True 且名字匹配 BUILTIN_AGENT_SPECS
  出厂表 → 链角色键映射（架构师=architect、写手=writer、审校员=auditor、
  修订师=reviser）；非链内置（世界观顾问/润色师）与自定义 Agent → null
  （前端 AgentChainCard 按 role_key 派生内置角色行，不再 hardcode 名称/
  图标/描述；config.agent_* 持久化契约不变）。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app

ENDPOINT = "/api/v1/agents"
"""Agent 端点前缀（spec §3.1，镜像父文件）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 中间件直通（镜像父文件）。"""


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，镜像父文件：delenv token → 直通）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _seed_agent(db_session, *, name: str, builtin: bool = False):
    """经 ORM 注入一条 Agent 记录（镜像父文件 helper，最小字段集）。"""
    from inkflow.infrastructure.database.models.agent import AgentORM

    row = AgentORM(name=name, builtin=builtin)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.mark.asyncio
@pytest.mark.api
class TestRoleKeyExposure:
    """内置 Agent role_key 透出契约（#473 R1，角色集合单一来源前置）。

    前端 AgentChainCard 按 role_key 派生内置角色行；列表端点与详情端点
    都透出（GET /api/v1/agents / GET /api/v1/agents/{id}）。
    """

    async def test_list_builtin_chain_roles_expose_role_key(
        self, client, db_session, override_get_db
    ):
        """seed 4 链内置（架构师/写手/审校员/修订师）→ 列表透出 role_key 映射。"""
        for name in ("架构师", "写手", "审校员", "修订师"):
            await _seed_agent(db_session, name=name, builtin=True)

        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        by_name = {it["name"]: it for it in resp.json()["items"]}
        for name, role_key in (
            ("架构师", "architect"),
            ("写手", "writer"),
            ("审校员", "auditor"),
            ("修订师", "reviser"),
        ):
            assert (
                by_name[name].get("role_key") == role_key
            ), f"{name} role_key 映射错误"

    async def test_list_non_chain_builtin_role_key_exposed_v15(
        self, client, db_session, override_get_db
    ):
        """v1.5 #484 内置可选角色（世界观顾问/润色师）→ role_key = worldview/polisher（§5.7.1）。

        v1.5 由 None 扩展为非 None（6 内置皆可进链）；本用例随 #473 R1 契约升级，
        替换 v1.4「非链内置 role_key 为 None」语义。
        """
        for name in ("世界观顾问", "润色师"):
            await _seed_agent(db_session, name=name, builtin=True)

        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        by_name = {it["name"]: it for it in resp.json()["items"]}
        # sentinel 区分「字段缺失」vs「值为 null」——缺失时 get 返回 'MISSING' 才 FAIL
        # （防确认型假绿：字段未透出时「is None」断言天然通过）
        assert by_name["世界观顾问"].get("role_key", "MISSING") == "worldview"
        assert by_name["润色师"].get("role_key", "MISSING") == "polisher"

    async def test_list_custom_agent_role_key_none(
        self, client, db_session, override_get_db
    ):
        """自定义 Agent → role_key 为 None（非内置无链映射）。"""
        await _seed_agent(db_session, name="自定义甲")

        resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["builtin"] is False
        # sentinel 区分「字段缺失」vs「值为 null」（防确认型假绿）
        assert item.get("role_key", "MISSING") is None

    async def test_detail_exposes_role_key(self, client, db_session, override_get_db):
        """详情端点同样透出 role_key（内置链角色 → 映射；自定义 → None）。"""
        builtin_row = await _seed_agent(db_session, name="架构师", builtin=True)
        custom_row = await _seed_agent(db_session, name="自定义乙")

        resp = await client.get(f"{ENDPOINT}/{builtin_row.id}")
        assert resp.status_code == 200
        assert resp.json().get("role_key") == "architect"

        resp = await client.get(f"{ENDPOINT}/{custom_row.id}")
        assert resp.status_code == 200
        # sentinel 区分「字段缺失」vs「值为 null」（防确认型假绿）
        assert resp.json().get("role_key", "MISSING") is None
