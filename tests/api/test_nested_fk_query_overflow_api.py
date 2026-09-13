"""#1162 嵌套 FK 查询参数：超范围 UUID → 空结果（不得 500）。真实 DB 轨。

姊妹文件：
- test_project_filter_endpoints_404_api.py —— #1151（路径里的 project_id）
- test_error_semantics_family_api.py      —— #1139/#1138（父资源主键 / 孤儿行）

本文件覆盖 #1162：**存活项目** + query 参数里的**嵌套 FK** 带 128 位 UUID
（uuid4 必 >= 2**63）→ SQLite OverflowError → 500。

契约语义（与 #1151 不同，务必区分）：
- #1151：**父资源**（project）不存在 → **404**
- #1162：父资源存在，**过滤条件值**超范围 → 该值不可能命中任何行
  → **200 + 空结果**（不是 404：资源是项目，项目就在那儿）

受控复现（make 实测，存活项目）：
  500  /projects/{pid}/chapters?volume_id=<uuid4>
  500  /projects/{pid}/characters?group_id=<uuid4>
  500  /projects/{pid}/maps?root_location_id=<uuid4>
  500  /projects/{pid}/world-settings?parent_id=<uuid4>
  200  /maps/{map_id}/pins?location_id=<uuid4>      ← 内存过滤，无溢出，对照组

全枚举依据：OpenAPI 153 条路径中「GET + uuid 型 query 参数」恰好 5 个（见上），
故本契约即为完整一族（无第 6 个）。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app

pytestmark = pytest.mark.asyncio  # F27 实测必写（asyncio_mode=auto 双保险）

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 直通（无 token 模式）。"""


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，无 token 模式）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _overflow_uuid() -> uuid.UUID:
    """随机 uuid4（128 位，必 > int64 上限 → 必不存在于任何表）。"""
    value = uuid.uuid4()
    assert value.int >= 2**63, "前提：uuid4 必然超出 SQLite 64 位 INTEGER 范围"
    return value


# (路径, 查询参数名, 响应中列表字段)
NESTED_FK_ENDPOINTS = [
    ("/api/v1/projects/{pid}/chapters", "volume_id", "items"),
    ("/api/v1/projects/{pid}/characters", "group_id", "items"),
    ("/api/v1/projects/{pid}/maps", "root_location_id", "items"),
    ("/api/v1/projects/{pid}/world-settings", "parent_id", "items"),
]
"""#1162 受损端点：存活项目的嵌套 FK 过滤参数（OpenAPI 全枚举的完整一族）。"""


@pytest.mark.api
@pytest.mark.parametrize("template,param,list_key", NESTED_FK_ENDPOINTS)
class TestNestedFkOverflowNoServerError:
    """#1162：嵌套 FK 过滤值超 int64 → 不得 500（空结果语义）。"""

    async def test_overflow_fk_does_not_500(
        self,
        client,
        db_session,
        override_get_db,
        api_project,
        template,
        param,
        list_key,
    ):
        """存活项目 + 超范围 FK → 200 且列表为空（修复前 = 500）。"""
        url = template.format(pid=api_project["id"])
        resp = await client.get(url, params={param: str(_overflow_uuid())})
        assert (
            resp.status_code != 500
        ), f"GET {url}?{param}=<uuid4> 不得 500，实际 {resp.status_code}: {resp.text[:200]}"
        assert (
            resp.status_code == 200
        ), f"GET {url}?{param}=<uuid4> 应为 200（过滤值不匹配任何行），实际 {resp.status_code}"
        assert resp.json()[list_key] == [], "超范围过滤值不得命中任何行"

    async def test_in_range_missing_fk_returns_empty(
        self,
        client,
        db_session,
        override_get_db,
        api_project,
        template,
        param,
        list_key,
    ):
        """合法 int64 范围但不存在的 FK → 200 + 空列表（范围校验不得误伤）。"""
        url = template.format(pid=api_project["id"])
        resp = await client.get(url, params={param: str(uuid.UUID(int=987654321))})
        assert (
            resp.status_code == 200
        ), f"GET {url}?{param}=<small> 应为 200，实际 {resp.status_code}: {resp.text[:200]}"
        assert resp.json()[list_key] == []


@pytest.mark.api
class TestNestedFkFilteringStillWorks:
    """反例守护：真实 FK → 200 且正确命中（过滤功能不得被修坏）。"""

    async def test_volume_filter_returns_only_that_volume(
        self, client, db_session, override_get_db, api_project
    ):
        """两卷各一章：按 volume_id 过滤 → 只返回该卷的章。"""
        pid = api_project["id"]
        v1 = await client.post(
            f"/api/v1/projects/{pid}/volumes", json={"title": "v1", "order_index": 1}
        )
        v2 = await client.post(
            f"/api/v1/projects/{pid}/volumes", json={"title": "v2", "order_index": 2}
        )
        assert v1.status_code == 201 and v2.status_code == 201
        v1_id, v2_id = v1.json()["id"], v2.json()["id"]

        for vid, title in ((v1_id, "c-in-v1"), (v2_id, "c-in-v2")):
            created = await client.post(
                f"/api/v1/projects/{pid}/chapters",
                json={"title": title, "volume_id": vid, "content": "x"},
            )
            assert created.status_code == 201, created.text[:200]

        filtered = await client.get(
            f"/api/v1/projects/{pid}/chapters", params={"volume_id": v1_id}
        )
        assert filtered.status_code == 200
        body = filtered.json()
        assert body["total"] == 1, f"应只命中 v1 的章节，实际 {body['total']}"
        assert body["items"][0]["title"] == "c-in-v1"

        # 不带过滤 → 两章都在（确认过滤是唯一变量）
        unfiltered = await client.get(f"/api/v1/projects/{pid}/chapters")
        assert unfiltered.json()["total"] == 2

    async def test_group_filter_returns_only_that_group(
        self, client, db_session, override_get_db, api_project
    ):
        """分组过滤：指派到 group 的角色被命中，未指派的不出现."""
        pid = api_project["id"]
        grp = await client.post(
            f"/api/v1/projects/{pid}/character-groups",
            json={"name": "g1", "description": "", "sort_order": 0},
        )
        assert grp.status_code == 201, grp.text[:200]
        gid = grp.json()["id"]

        in_group = await client.post(
            f"/api/v1/projects/{pid}/characters",
            json={
                "name": "in-group",
                "brief": "",
                "extra": {"role_rank": "major"},
                "group_ids": [gid],
            },
        )
        assert in_group.status_code == 201, in_group.text[:200]
        out_group = await client.post(
            f"/api/v1/projects/{pid}/characters",
            json={"name": "out-group", "brief": "", "extra": {"role_rank": "minor"}},
        )
        assert out_group.status_code == 201, out_group.text[:200]

        filtered = await client.get(
            f"/api/v1/projects/{pid}/characters", params={"group_id": gid}
        )
        assert filtered.status_code == 200
        names = [c["name"] for c in filtered.json()["items"]]
        assert names == ["in-group"], f"应只命中 in-group，实际 {names}"


@pytest.mark.api
class TestMapPinsLocationFilterControl:
    """对照组：maps/{map_id}/pins?location_id 走内存过滤 → 本就无溢出，不得回归。"""

    async def test_location_id_overflow_does_not_500(
        self, client, db_session, override_get_db, api_project
    ):
        """存活地图 + 超范围 location_id → 不得 500（内存过滤，无 SQL 绑定）。"""
        pid = api_project["id"]
        created = await client.post(
            f"/api/v1/projects/{pid}/maps",
            data={"name": "pin-map", "description": ""},
            files={"file": ("m.png", b"\x89PNG\r\n\x1a\n")},
        )
        assert created.status_code == 201, created.text[:200]
        map_id = created.json()["id"]

        resp = await client.get(
            f"/api/v1/maps/{map_id}/pins", params={"location_id": str(_overflow_uuid())}
        )
        assert (
            resp.status_code != 500
        ), f"不得 500，实际 {resp.status_code}: {resp.text[:200]}"
        assert resp.status_code == 200
