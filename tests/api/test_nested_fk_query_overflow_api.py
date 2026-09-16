"""#1162 嵌套 FK 查询参数：超范围 UUID 不得 500（真实 DB 轨）。

姊妹文件：
- test_project_filter_endpoints_404_api.py —— #1151（路径里的 project_id）
- test_error_semantics_family_api.py      —— #1139/#1138（父资源主键 / 孤儿行）

本文件覆盖 #1162：**存活项目** + query 参数里的**嵌套 FK** 带 128 位 UUID
（uuid4 必 >= 2**63）→ SQLite OverflowError → 500。

🔴 关键设计约束（第一版修法踩过的坑，本契约即为守护它）：
router 层已把 FK 查询参数 `_parse_id()` 成 `uuid.UUID` 再传 service
（`chapter.py:172`），故 **service 层收到的合法 uuid4 FK 与溢出值无法区分**。
因此：
- 守卫必须落在 **repo 层**（SQL 绑定边界，对齐 #1139 `map_repo.list_pins`）
- **合法 uuid4 作为 FK 过滤值必须正常透传**（不得被守卫吞掉）——
  见 TestValidUuidFkStillPassesThrough（第一版修法在此失败）

受控复现（父侧实测，存活项目）：
  500  /projects/{pid}/chapters?volume_id=<uuid4>
  500  /projects/{pid}/characters?group_id=<uuid4>
  500  /projects/{pid}/maps?root_location_id=<uuid4>
  500  /projects/{pid}/world-settings?parent_id=<uuid4>
  200  /maps/{map_id}/pins?location_id=<uuid4>      ← 内存过滤，无 SQL 绑定，对照组

全枚举依据：OpenAPI 153 条路径中「GET + uuid 型 query 参数」恰好 5 个（见上），
本契约即为完整一族（无第 6 个）。
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


# (路径, 查询参数名, 响应列表字段)
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
        assert resp.status_code != 500, (
            f"GET {url}?{param}=<uuid4> 不得 500，实际 {resp.status_code}: {resp.text[:200]}"
        )
        assert resp.status_code == 200, (
            f"GET {url}?{param}=<uuid4> 应为 200（过滤值不匹配任何行），实际 {resp.status_code}"
        )
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
        assert resp.status_code == 200, (
            f"GET {url}?{param}=<small> 应为 200，实际 {resp.status_code}: {resp.text[:200]}"
        )
        assert resp.json()[list_key] == []


@pytest.mark.api
@pytest.mark.parametrize(
    "template,param,list_key",
    [
        ("/api/v1/projects/{pid}/chapters", "volume_id", "items"),
        ("/api/v1/projects/{pid}/characters", "group_id", "items"),
        ("/api/v1/projects/{pid}/maps", "root_location_id", "items"),
    ],
)
class TestValidUuidFkStillPassesThrough:
    """🔴 第一版修法的守护：合法 uuid4 FK 必须正常透传，不得被守卫吞成空结果。

    router 已把 FK 解析为 uuid.UUID（`chapter.py:172`），service `_to_int_id` 得 `.int`
    → 恒为 128 位。若在 **service 层**加 int64 守卫，会把**所有合法 uuid4 过滤值**
    误判为空结果 —— 这正是第一版修法（commit 2409f4e，已 revert）打红
    `test_map_service.py::test_list_maps_forwards` 与
    `test_character_service.py::test_list_characters_forwards_filters_and_pagination` 的原因。
    守卫必须在 **repo 层**（SQL 绑定边界）。

    本用例：用**真实存在的 uuid4**（DB 自增 int64 生成的 id）做过滤值 → 必须命中。
    """

    async def test_existing_uuid_fk_is_not_swallowed(
        self,
        client,
        db_session,
        override_get_db,
        api_project,
        template,
        param,
        list_key,
    ):
        """真实存在的 uuid4 FK → 200 且命中数据（不得被 int64 守卫误吞）。"""
        pid = api_project["id"]
        if param == "volume_id":
            parent = await client.post(
                f"/api/v1/projects/{pid}/volumes",
                json={"title": "real-vol", "order_index": 1},
            )
            assert parent.status_code == 201, parent.text[:200]
            parent_id = parent.json()["id"]
            child = await client.post(
                f"/api/v1/projects/{pid}/chapters",
                json={"title": "real-ch", "volume_id": parent_id, "content": "x"},
            )
        elif param == "group_id":
            parent = await client.post(
                f"/api/v1/projects/{pid}/character-groups",
                json={"name": "real-grp", "description": "", "sort_order": 0},
            )
            assert parent.status_code == 201, parent.text[:200]
            parent_id = parent.json()["id"]
            child = await client.post(
                f"/api/v1/projects/{pid}/characters",
                json={
                    "name": "real-char",
                    "brief": "",
                    "extra": {"role_rank": "major"},
                    "group_ids": [parent_id],
                },
            )
        else:  # root_location_id
            # world-settings 条目要求分类先存在（422「请先创建分类」否则）
            cat = await client.post(
                f"/api/v1/projects/{pid}/world-categories",
                json={"name": "geo", "kind": "geo"},
            )
            assert cat.status_code == 201, cat.text[:200]
            loc = await client.post(
                f"/api/v1/projects/{pid}/world-settings",
                json={"name": "real-loc", "category": "geo", "content": ""},
            )
            assert loc.status_code == 201, loc.text[:200]
            parent_id = loc.json()["id"]
            child = await client.post(
                f"/api/v1/projects/{pid}/maps",
                data={
                    "name": "real-map",
                    "description": "",
                    "root_location_id": parent_id,
                },
                files={"file": ("m.png", b"\x89PNG\r\n\x1a\n")},
            )
        assert child.status_code == 201, child.text[:200]
        # 前提确认：真实 FK 由 DB 自增分配 → 落在 int64 范围内（不会溢出）
        parent_int = uuid.UUID(parent_id).int
        assert parent_int < 2**63, "前提：DB 自增 int 主键必在 int64 范围内"

        resp = await client.get(template.format(pid=pid), params={param: parent_id})
        assert resp.status_code == 200, resp.text[:200]
        assert resp.json()[list_key], "合法 uuid4 FK 必须命中数据，实际为空（守卫误吞）"


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
        assert resp.status_code != 500, f"不得 500，实际 {resp.status_code}: {resp.text[:200]}"
        assert resp.status_code == 200
