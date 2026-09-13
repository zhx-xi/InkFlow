"""#1139 + #1138 错误语义一族 RED 契约测试 — 真实 DB 轨。

（#1139 过滤/删除型 UUID 溢出 → 404；#1138 create_* 校验项目存在 → 404 + 无孤儿行）

姊妹文件 test_uuid_path_param_overflow_api.py 覆盖 #1106 主键查询路径（已修）。
本文件把覆盖面推到 #1106 未覆盖的两类路径：

#1139（受控复现 main@ebbd40b，传随机 uuid4() = 128 位超 int64）：
  500! GET /api/v1/maps/{uuid4}/pins          ← 过滤条件型（list_pins(map_id)）
  500! GET /api/v1/maps/{uuid4}/children      ← 过滤条件型（children(map_id)）
  500! GET /api/v1/world-settings/{uuid4}/descendants
  500! DELETE /api/v1/maps/{uuid4}            ← delete 型
  500! DELETE /api/v1/characters/{uuid4}
  500! DELETE /api/v1/timeline/events/{uuid4}
  200* GET /api/v1/outlines/{uuid4}/plot-points       ← 静默 200（应 404）
  200* GET /api/v1/characters/{uuid4}/relations       ← 静默 200（应 404）
  * service 内部判定父不存在后 return []，router 不检查 → 200 + 空数组

根因：#1106 只给「主键查询」方法（repo.get）加了 int64 守卫 → 返回 None → 404。
过滤型方法签名里 int 是过滤条件（list_pins(map_id) 返回 [] 非 None），
delete 型直接在 128 位 int 上做 SQL 绑定 → OverflowError → 500。
静默 200 型是 service 已判定父不存在却丢弃信息（return [] 而非抛错）。

契约（本项目「资源缺失」语义 = 随机 UUID 等价语义，族内先例 #578/#631/#1106）：
- 上述 8 端点：随机 uuid4（必不存在）→ 404，非 500 / 非 200
- 对照组（已正确的 6 个）→ 仍 404（防回归，勿动）
- 反例守护：合法父资源 + 空子列表 → 200 + []（「无 pin」不得误判为 404）

#1138（受控复现，projects 表 0 行 → create_* 仍 201 落孤儿行）：
  201 POST /api/v1/projects/{不存在uuid}/world-settings
  201 POST /api/v1/projects/{不存在uuid}/world-categories
  201 POST /api/v1/projects/{不存在uuid}/character-groups
  201 POST /api/v1/projects/{不存在uuid}/volumes
契约：→ 404「项目不存在」且新表行数 = 0（DB 断言，孤儿行零容忍）。
反例形态：foreshadowing_service._ensure_project + MapService.create_map（先 get 再判）。

测试形态：真实 DB 轨（client + db_session + override_get_db），不 patch service ——
真实 service + 真实 repo 走 128 位 int 绑定路径（镜像 test_uuid_path_param_overflow_api.py）。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from inkflow.api.app import app
from inkflow.infrastructure.database.models.chapter import VolumeORM
from inkflow.infrastructure.database.models.character import CharacterGroupORM
from inkflow.infrastructure.database.models.world import (
    WorldCategoryORM,
    WorldSettingORM,
)

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


# ── #1139 受损端点：过滤型 / delete 型 ──────────────────────────────

FILTER_OVERFLOW_ENDPOINTS = [
    "/api/v1/maps/{id}/pins",
    "/api/v1/maps/{id}/children",
    "/api/v1/world-settings/{id}/descendants",
]
"""过滤条件型路径（repo 方法签名中 int 是过滤条件，溢出 → 500）。"""

DELETE_OVERFLOW_ENDPOINTS = [
    "/api/v1/maps/{id}",
    "/api/v1/characters/{id}",
    "/api/v1/timeline/events/{id}",
]
"""delete 型路径（128 位 int 直接做 SQL 绑定 → OverflowError → 500）。"""

SILENT_200_ENDPOINTS = [
    "/api/v1/outlines/{id}/plot-points",
    "/api/v1/characters/{id}/relations",
]
"""静默 200 型路径（service 判定父不存在后 return []，router 不检查 → 200）。"""

CONTROL_ENDPOINTS = [
    "/api/v1/world-settings/{id}/ancestors",
    "/api/v1/sessions/{id}/logs",
    "/api/v1/volumes/{id}/chapters",
    "/api/v1/chapters/{id}/versions",
    "/api/v1/outlines/{id}/points",
]
"""对照组：已正确的端点（#1106 修法适用或本就没有溢出路径）→ 不得回归。"""


@pytest.mark.api
@pytest.mark.parametrize(
    "template",
    FILTER_OVERFLOW_ENDPOINTS + DELETE_OVERFLOW_ENDPOINTS + SILENT_200_ENDPOINTS,
)
class TestNonPrimaryKeyUuidOverflow:
    """#1139 过滤型/delete 型/静默 200 型端点：随机 UUID → 404。

    修复前（当前 main）：
    - 过滤型/delete 型 → SQLite OverflowError → 500 ≠ 404 → FAIL
    - 静默 200 型 → 200 + 空数组 ≠ 404 → FAIL
    """

    async def test_random_uuid_returns_404(
        self, client, db_session, override_get_db, template
    ):
        """随机 uuid4（128 位溢出）→ 404（不得 500 / 不得静默 200）。"""
        url = template.format(id=_overflow_uuid())
        method = (
            "DELETE"
            if url in {t.format(id="x") for t in DELETE_OVERFLOW_ENDPOINTS}
            else "GET"
        )
        resp = await client.request(method, url)
        assert (
            resp.status_code == 404
        ), f"{method} {url} 应为 404（父资源不存在），实际 {resp.status_code}: {resp.text[:200]}"

    async def test_small_int_uuid_not_found_returns_404(
        self, client, db_session, override_get_db, template
    ):
        """合法小整数 UUID（int64 范围内但不存在）→ 404（范围校验不得误伤）。"""
        url = template.format(id=uuid.UUID(int=987654321))
        method = (
            "DELETE"
            if url in {t.format(id="x") for t in DELETE_OVERFLOW_ENDPOINTS}
            else "GET"
        )
        resp = await client.request(method, url)
        assert (
            resp.status_code == 404
        ), f"{method} {url} 应为 404（资源不存在），实际 {resp.status_code}: {resp.text[:200]}"


@pytest.mark.api
@pytest.mark.parametrize("template", CONTROL_ENDPOINTS)
class TestControlEndpointsNoRegression:
    """对照 5 端点：随机 UUID → 仍 404（防回归；这些路径本就正确）。"""

    async def test_random_uuid_returns_404(
        self, client, db_session, override_get_db, template
    ):
        """对照组随机 uuid4 → 404（修复不得使已正确路径退化）。"""
        url = template.format(id=_overflow_uuid())
        resp = await client.get(url)
        assert (
            resp.status_code == 404
        ), f"{url} 应为 404（资源不存在），实际 {resp.status_code}: {resp.text[:200]}"


@pytest.mark.api
class TestEmptyChildListNotMisjudged:
    """反例守护：合法父资源 + 空子列表 → 200 + []（「无 pin」≠「父不存在」）。"""

    async def test_existing_map_with_no_pins_returns_200_empty(
        self, client, db_session, override_get_db, sample_project
    ):
        """真实地图 + 无 pin → GET /maps/{id}/pins → 200 且 items 为空。"""
        created = await client.post(
            f"/api/v1/projects/{sample_project.id}/maps",
            data={"name": "空图探针", "description": ""},
            files={"file": ("main.png", b"\x89PNG\r\n\x1a\n")},
        )
        assert created.status_code == 201, created.text[:200]
        map_id = created.json()["id"]

        resp = await client.get(f"/api/v1/maps/{map_id}/pins")
        assert (
            resp.status_code == 200
        ), f"合法地图应为 200，实际 {resp.status_code}: {resp.text[:200]}"
        assert resp.json() == {"items": [], "total": 0}

    async def test_existing_map_with_no_children_returns_200_empty(
        self, client, db_session, override_get_db, sample_project
    ):
        """真实地图 + 无子图 → GET /maps/{id}/children → 200 且 items 为空。"""
        created = await client.post(
            f"/api/v1/projects/{sample_project.id}/maps",
            data={"name": "无子探针", "description": ""},
            files={"file": ("main.png", b"\x89PNG\r\n\x1a\n")},
        )
        assert created.status_code == 201, created.text[:200]
        map_id = created.json()["id"]

        resp = await client.get(f"/api/v1/maps/{map_id}/children")
        assert (
            resp.status_code == 200
        ), f"合法地图应为 200，实际 {resp.status_code}: {resp.text[:200]}"
        assert resp.json() == {"items": [], "total": 0}

    async def test_existing_outline_with_no_points_returns_200_empty(
        self, client, db_session, override_get_db, sample_project
    ):
        """真实大纲 + 无情节点 → GET /outlines/{id}/plot-points → 200 且 items 为空。"""
        created = await client.post(
            f"/api/v1/projects/{sample_project.id}/outlines",
            json={"name": "空大纲探针", "level": "overall"},
        )
        assert created.status_code == 201, created.text[:200]
        outline_id = created.json()["id"]

        resp = await client.get(f"/api/v1/outlines/{outline_id}/plot-points")
        assert (
            resp.status_code == 200
        ), f"合法大纲应为 200，实际 {resp.status_code}: {resp.text[:200]}"
        assert resp.json() == {"items": [], "total": 0}


# ── #1138 create_* 孤儿行 ────────────────────────────────────────────

ORPHAN_CREATE_CASES = [
    (
        "/api/v1/projects/{pid}/world-settings",
        {"name": "孤儿世界观", "category": "", "content": ""},
        "world_settings",
    ),
    (
        "/api/v1/projects/{pid}/world-categories",
        {"name": "孤儿分类", "kind": "geo"},
        "world_categories",
    ),
    (
        "/api/v1/projects/{pid}/character-groups",
        {"name": "孤儿分组", "description": "", "sort_order": 0},
        "character_groups",
    ),
    (
        "/api/v1/projects/{pid}/volumes",
        {"title": "孤儿卷"},
        "volumes",
    ),
]
"""#1138 四个 create_* 端点：path project_id 由调用方提供，服务层需自校验存在性。"""


@pytest.mark.api
@pytest.mark.parametrize("template,body,table", ORPHAN_CREATE_CASES)
class TestCreateRequiresExistingProject:
    """#1138 create_* 必须校验 project 存在 → 404 且不落孤儿行。"""

    async def test_missing_project_returns_404_no_orphan_row(
        self, client, db_session, override_get_db, template, body, table
    ):
        """不存在的 project_id（随机 uuid4）→ 404「项目不存在」且目标表 0 行。"""
        orm_map = {
            "world_settings": WorldSettingORM,
            "world_categories": WorldCategoryORM,
            "character_groups": CharacterGroupORM,
            "volumes": VolumeORM,
        }
        orm_cls = orm_map[table]

        async def _count() -> int:
            result = await db_session.execute(select(func.count()).select_from(orm_cls))
            return int(result.scalar_one())

        before = await _count()
        assert before == 0, f"前提：{table} 应为空表（projects 亦 0 行）"

        url = template.format(pid=_overflow_uuid())
        resp = await client.post(url, json=body)

        assert (
            resp.status_code == 404
        ), f"POST {url} 项目不存在应为 404，实际 {resp.status_code}: {resp.text[:200]}"
        after = await _count()
        assert (
            after == 0
        ), f"POST {url} 不得写入孤儿行：{table} 由 {before} → {after} 行"
