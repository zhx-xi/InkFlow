"""#1151 项目过滤型端点：project 不存在 → 404（真实 DB 轨）。

姊妹文件 test_error_semantics_family_api.py 覆盖 #1139（过滤/delete/静默 200 型，
以 **父资源主键** 为过滤条件）与 #1138（create_* 孤儿行）。
本文件把覆盖面推到 #1139 枚举遗漏的一族：**以路径中的 project_id 为过滤条件**、
返回「列表 / 空列表」的端点。

受控复现（0.14.0-rc8 打包产物内核，pid=ffffffff-ffff-4fff-8fff-ffffffffffff → 全 500）：

    GET /api/v1/projects/{pid}/chapters    → 500   ← chapter_repo.list_chapters
    GET /api/v1/projects/{pid}/volumes     → 500   ← chapter_repo.list_volumes
    GET /api/v1/projects/{pid}/characters  → 500   ← character_repo.list
    GET /api/v1/projects/{pid}/outlines    → 500   ← outline_repo.list

根因（与 #1139 同族，两个独立缺口）：

1. **repo 层**：`list_*` 把 `project_id` 直接绑进 SQL WHERE 且无 int64 守卫。
   128 位 UUID int（uuid4 必 >= 2**63）→ SQLite OverflowError → 500。
   对照 #1139 修的 map_repo.list_pins（`if map_id < -(2**63) ...: return []`）。

2. **service 层**：即便溢出被守卫、「合法 int64 但不存在的 UUID」也只是
   静默返回空列表。**空列表 != 项目不存在**，须回查 project_repo 才能定 404 语义
   （#1139 已验收形态 map_service.list_pins：空结果才回查父实体）。
   即根因不只是溢出——「不存在」本身就没有校验。

契约（族内先例 #578/#631/#1106/#1139：资源缺失 → 404）：
- project 过滤型端点 x (随机 uuid4 溢出, 合法小整数不存在) → 404，非 500 / 非 200
- 反例守护：真存活 project + 空子列表 → 200 + []（「无章节」不得误判为 404）
- 对照：真存活 project 有数据 → 200 且返回正确数据
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


# ── 受损端点：以路径 project_id 为过滤条件的列表端点 ─────────────────

PROJECT_FILTER_ENDPOINTS = [
    # issue #1151 原文列出的 4 个
    "/api/v1/projects/{pid}/chapters",
    "/api/v1/projects/{pid}/volumes",
    "/api/v1/projects/{pid}/characters",
    "/api/v1/projects/{pid}/outlines",
    # 同文件同形，父侧枚举新增
    "/api/v1/projects/{pid}/story-arcs",
    "/api/v1/projects/{pid}/character-groups",
    # 跨限界上下文的同根因端点（父侧探针实测，用户拍板 A：一次修完）
    "/api/v1/projects/{pid}/extractions/runs",
    "/api/v1/projects/{pid}/knowledge-relations",
    "/api/v1/projects/{pid}/knowledge-graph",
    "/api/v1/projects/{pid}/maps",
    "/api/v1/projects/{pid}/timeline/events",
    "/api/v1/projects/{pid}/world-settings",
    "/api/v1/projects/{pid}/world-settings/categories",
    "/api/v1/projects/{pid}/world-categories",
]
"""project_id 过滤型列表端点 — 父侧全枚举探针实测的完整一族（14 个）。

判据 = 22 个 `{project_id}` GET 端点中「资源缺失应 404 却非 404」的全部。
**不在列**：`/projects/{pid}` 与 `audit`/`audit-logs`/`export`/`foreshadowings`/
`timeline`/`timeline/check`（已正确 404）、`vector/status`（状态探针语义，
项目缺失返回 no_embedding 是合理降级，用户拍板不动）。
"""


@pytest.mark.api
@pytest.mark.parametrize("template", PROJECT_FILTER_ENDPOINTS)
class TestProjectFilterEndpointsRequireExistingProject:
    """#1151：project 不存在 → 404（不得 500，不得静默 200 + []）。"""

    async def test_overflow_uuid_returns_404(self, client, db_session, override_get_db, template):
        """随机 uuid4（128 位溢出）→ 404。

        修复前：repo 直接绑 128 位 int → SQLite OverflowError → 500。
        """
        url = template.format(pid=_overflow_uuid())
        resp = await client.get(url)
        assert resp.status_code == 404, (
            f"GET {url} should be 404 (project missing), got {resp.status_code}: {resp.text[:200]}"
        )

    async def test_small_int_uuid_not_found_returns_404(
        self, client, db_session, override_get_db, template
    ):
        """合法 int64 范围但不存在 → 404（根因不只是溢出，是缺存在性校验）。"""
        url = template.format(pid=uuid.UUID(int=987654321))
        resp = await client.get(url)
        assert resp.status_code == 404, (
            f"GET {url} should be 404 (project missing), got {resp.status_code}: {resp.text[:200]}"
        )


@pytest.mark.api
class TestExistingProjectEmptyListNotMisjudged:
    """反例守护：真存活项目 + 空子列表 → 200 + []（不得矫枉过正）。"""

    async def test_empty_chapters_returns_200_empty(
        self, client, db_session, override_get_db, api_project
    ):
        """存活项目 + 无章节 → 200 且 items 空、total=0。"""
        resp = await client.get(f"/api/v1/projects/{api_project['id']}/chapters")
        assert resp.status_code == 200, f"live project should be 200, got {resp.status_code}"
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    async def test_empty_volumes_returns_200_empty(
        self, client, db_session, override_get_db, api_project
    ):
        """存活项目 + 无卷 → 200 且 items 空。"""
        resp = await client.get(f"/api/v1/projects/{api_project['id']}/volumes")
        assert resp.status_code == 200, f"live project should be 200, got {resp.status_code}"
        assert resp.json()["items"] == []

    async def test_empty_characters_returns_200_empty(
        self, client, db_session, override_get_db, api_project
    ):
        """存活项目 + 无角色 → 200 且 items 空、total=0。"""
        resp = await client.get(f"/api/v1/projects/{api_project['id']}/characters")
        assert resp.status_code == 200, f"live project should be 200, got {resp.status_code}"
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    async def test_empty_outlines_returns_200_empty(
        self, client, db_session, override_get_db, api_project
    ):
        """存活项目 + 无大纲 → 200 且 items 空、total=0。"""
        resp = await client.get(f"/api/v1/projects/{api_project['id']}/outlines")
        assert resp.status_code == 200, f"live project should be 200, got {resp.status_code}"
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    async def test_empty_story_arcs_returns_200_empty(
        self, client, db_session, override_get_db, api_project
    ):
        """存活项目 + 无弧线 → 200 且 items 空。"""
        resp = await client.get(f"/api/v1/projects/{api_project['id']}/story-arcs")
        assert resp.status_code == 200, f"live project should be 200, got {resp.status_code}"
        assert resp.json()["items"] == []

    async def test_empty_character_groups_returns_200_empty(
        self, client, db_session, override_get_db, api_project
    ):
        """存活项目 + 无分组 → 200 且 items 空。"""
        resp = await client.get(f"/api/v1/projects/{api_project['id']}/character-groups")
        assert resp.status_code == 200, f"live project should be 200, got {resp.status_code}"
        assert resp.json()["items"] == []


@pytest.mark.api
class TestExistingProjectWithDataReturnsData:
    """对照：存活项目有数据 → 200 且返回正确数据（空判定不得吃掉结果）。"""

    async def test_chapters_and_volumes_return_created_data(
        self, client, db_session, override_get_db, api_project
    ):
        """建 1 卷 + 1 章 → volumes/chapters 均 200 且含该数据。"""
        pid = api_project["id"]
        vol = await client.post(
            f"/api/v1/projects/{pid}/volumes",
            json={"title": "vol-one", "order_index": 1},
        )
        assert vol.status_code == 201, vol.text[:200]
        vol_id = vol.json()["id"]

        ch = await client.post(
            f"/api/v1/projects/{pid}/chapters",
            json={"title": "chapter-one", "volume_id": vol_id, "content": "body"},
        )
        assert ch.status_code == 201, ch.text[:200]

        vols = await client.get(f"/api/v1/projects/{pid}/volumes")
        assert vols.status_code == 200
        assert [v["title"] for v in vols.json()["items"]] == ["vol-one"]

        chapters = await client.get(f"/api/v1/projects/{pid}/chapters")
        assert chapters.status_code == 200
        body = chapters.json()
        assert body["total"] == 1
        assert body["items"][0]["title"] == "chapter-one"

    async def test_characters_and_outlines_return_created_data(
        self, client, db_session, override_get_db, api_project
    ):
        """建 1 角色 + 1 大纲 → characters/outlines 均 200 且含该数据。"""
        pid = api_project["id"]
        char = await client.post(
            f"/api/v1/projects/{pid}/characters",
            json={"name": "char-one", "brief": "", "extra": {"role_rank": "major"}},
        )
        assert char.status_code == 201, char.text[:200]

        outline = await client.post(
            f"/api/v1/projects/{pid}/outlines",
            json={"name": "outline-one", "level": "overall"},
        )
        assert outline.status_code == 201, outline.text[:200]

        chars = await client.get(f"/api/v1/projects/{pid}/characters")
        assert chars.status_code == 200
        cbody = chars.json()
        assert cbody["total"] == 1
        assert cbody["items"][0]["name"] == "char-one"

        outlines = await client.get(f"/api/v1/projects/{pid}/outlines")
        assert outlines.status_code == 200
        obody = outlines.json()
        assert obody["total"] == 1
        assert obody["items"][0]["name"] == "outline-one"

    async def test_volume_scoped_chapter_list_returns_data(
        self, client, db_session, override_get_db, api_project
    ):
        """按 volume_id 过滤（非空 volume_id 分支）→ 200 且命中该卷章节。"""
        pid = api_project["id"]
        vol = await client.post(
            f"/api/v1/projects/{pid}/volumes",
            json={"title": "vol-two", "order_index": 1},
        )
        assert vol.status_code == 201, vol.text[:200]
        vol_id = vol.json()["id"]

        ch = await client.post(
            f"/api/v1/projects/{pid}/chapters",
            json={"title": "scoped-chapter", "volume_id": vol_id, "content": "x"},
        )
        assert ch.status_code == 201, ch.text[:200]

        scoped = await client.get(f"/api/v1/projects/{pid}/chapters", params={"volume_id": vol_id})
        assert scoped.status_code == 200
        assert scoped.json()["total"] == 1
