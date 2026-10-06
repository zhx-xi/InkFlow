"""#1481 建项目自动建根 — API 层契约测试（真实装配，非 mock service）.

用 `override_get_db` + 真实 `deps.get_project_service`（注入 root_initializer），
验证「项目创建 → 根必存在」在 HTTP 契约面成立。

RED 形态（当前实现）：POST /projects 后世界观列表 total == 0 → 断言 FAIL。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app

# 显式 asyncio 标记：`../tests/api` 运行（cwd=backend）时 rootdir=仓库根，
# backend/pyproject.toml 的 asyncio_mode=auto 不生效（同 tests/api 既有文件惯例）
pytestmark = [pytest.mark.asyncio, pytest.mark.api]

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"


@pytest_asyncio.fixture
async def client(monkeypatch, override_get_db):
    """ASGI 客户端（函数级，无 token 模式；同一 in-memory db_session）."""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_project(client: AsyncClient, name: str) -> str:
    """POST /projects → 返回项目 id."""
    resp = await client.post("/api/v1/projects", json={"name": name})
    assert resp.status_code == 201, resp.text[:200]
    return str(resp.json()["id"])


class TestProjectCreationSeedsWorldRoot:
    """「每项目唯一根」不变量在项目创建即成立（#1481）."""

    async def test_post_project_then_world_list_has_exactly_one_root(self, client) -> None:
        """POST /projects → GET world-settings 立即含**恰好 1 个**根（category==""）."""
        pid = await _create_project(client, "自带根的书")

        listing = await client.get(f"/api/v1/projects/{pid}/world-settings")
        assert listing.status_code == 200, listing.text[:200]
        body = listing.json()

        assert body["total"] == 1, "新建项目应立即自带恰好 1 个世界观根条目"
        root = body["items"][0]
        assert root["name"] == "世界观总纲"
        assert root["category"] == ""
        assert root["parent_id"] is None

    async def test_two_projects_each_have_own_root(self, client) -> None:
        """两个新项目各自独立一根（不串根）."""
        pids = [await _create_project(client, name) for name in ("甲书", "乙书")]

        for pid in pids:
            listing = await client.get(f"/api/v1/projects/{pid}/world-settings")
            assert listing.status_code == 200
            assert listing.json()["total"] == 1

    async def test_root_is_usable_as_parent_for_child_entry(self, client) -> None:
        """#1481 复现路径闭环：建项目 → 注册分类 → 根下建条目 → 201（不再手工先建根）."""
        pid = await _create_project(client, "闭环书")

        root = (await client.get(f"/api/v1/projects/{pid}/world-settings")).json()["items"][0]

        cat = await client.post(
            f"/api/v1/projects/{pid}/world-categories",
            json={"name": "门派设定", "kind": "abstract"},
        )
        assert cat.status_code == 201, cat.text[:200]

        child = await client.post(
            f"/api/v1/projects/{pid}/world-settings",
            json={
                "name": "门派甲",
                "category": "门派设定",
                "content": "x",
                "parent_id": root["id"],
            },
        )
        assert child.status_code == 201, child.text[:200]
        assert child.json()["parent_id"] == root["id"]

    async def test_category_precheck_still_422_and_no_second_root(self, client) -> None:
        """#834/#1321 不回归：未注册分类条目 → 422，且**不产生第二个根**（根仍恰好 1）."""
        pid = await _create_project(client, "单根书")

        resp = await client.post(
            f"/api/v1/projects/{pid}/world-settings",
            json={"name": "未注册分类条目", "category": "不存在分类"},
        )
        assert resp.status_code == 422, resp.text[:200]

        roots = await client.get(f"/api/v1/projects/{pid}/world-settings?parent_id=none")
        assert roots.status_code == 200
        assert roots.json()["total"] == 1, "422 未落库；根必须仍恰好 1 个（不回归 #834）"
