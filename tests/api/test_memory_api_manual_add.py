"""#521 「记忆页手动添加/编辑记忆（双作用域）」REST API 契约测试（TDD RED 阶段）.

父侧定稿契约（2026-08-20，实现者以本文件为准）。沿用 memory router 既有前缀
/api/v1/agent，4 个新端点 = POST/PATCH × project/user 双作用域:

1) POST /api/v1/agent/preferences — 项目偏好手动创建
   body ProjectPreferenceCreate {project_id: UUID 必填, category:
   PreferenceCategory 必填, pattern: str 非空（Field(min_length=1)）, value:
   str 非空, confidence: float|None=None, count: int|None=None}
   → 201 直接返回 ProjectPreference flat dict（无 envelope），字段:
   id/project_id/category/pattern/value/confidence/count/source_events/
   created_at/updated_at
   router 调 svc.create_preference(**body.model_dump())
2) POST /api/v1/agent/user-preferences — 用户级偏好手动创建
   body UserPreferenceCreate {category: PreferenceCategory 必填, pattern:
   str 非空, value: str 非空, confidence=None, count=None}
   → 201 flat UserPreference dict（无 project_id 键），字段:
   id/category/pattern/value/confidence/count/project_count/source_projects/
   source_events/created_at/updated_at
   router 调 svc.create_user_preference(**body.model_dump())
3) PATCH /api/v1/agent/preferences/{preference_id} — 项目偏好编辑
   body PreferenceUpdate {category: PreferenceCategory|None=None, pattern:
   str|None=None, value: str|None=None}（三个全空 → 422）
   → 200 flat ProjectPreference dict；404（PreferenceNotFoundError → detail=
   "偏好不存在"）
4) PATCH /api/v1/agent/user-preferences/{preference_id} — 用户级偏好编辑
   同上 → 200 flat UserPreference dict / 404

service 方法签名（#521 新增，API 测试 mock service 用名）:
- create_preference(*, project_id, category, pattern, value, confidence=None,
  count=None)
- create_user_preference(*, category, pattern, value, confidence=None,
  count=None)
- update_preference(preference_id, *, category=None, pattern=None, value=None)
- update_user_preference(preference_id, *, category=None, pattern=None,
  value=None)
API 测试只锁调用参数宽松断言（_call_arg: 位置 0 或 kwargs 名均可），不锁
GREEN 传参细节。

设计假设（GREEN 对齐点）:
- 201 由 router 显式 status_code=201 实现（201 vs 200 是本文件核心契约，
  防实现者误用 200 假绿）
- PreferenceUpdate 全 None → 422 需 schema 级 model_validator（GREEN 新建
  schema 时实现）；422 断言只锁 status_code==422，不锁错误文案（Pydantic
  版本敏感）
- update 透传形态宽松: 只锁「提供的字段值到达 service」，不锁未提供字段
  是否以 None 透传（GREEN 可用 exclude_unset=True 或全量 None 任一形态）
- 404 映射镜像既有 DELETE 语义: except PreferenceNotFoundError → raise
  HTTPException(status_code=404, detail=str(exc))；detail 锁「偏好不存在」
  防「期望 404 撞未注册 404」假绿
- PreferenceNotFoundError 定义位置 = inkflow.domain.services.memory_service
  （既有，GREEN 复用）

全 mock 轨（零 DB）: app.dependency_overrides[get_memory_service] 替换为
mock service（_override_memory_service，镜像 tests/api/test_memory_api.py）；
客户端 AsyncClient + ASGITransport 直接打真实 app（不触发 lifespan）。

RED 预期
--------
memory router 现状仅注册 GET/DELETE（2026-08-20 实测 app.routes），4 个新
端点全部未注册 → 用例直接打真实 app:
- POST/PATCH 2xx 用例: 路径已存在（GET/DELETE）但方法未注册 → FastAPI 405
  ≠ 201/200 → 断言 FAILED；若路径整体未注册则为 404 ≠ 期望码 → 同样 FAILED
- PATCH 404 用例: 405 ≠ 404 → 状态码断言先 FAILED（防「期望 404 撞未注册
  404」假绿）
- 422 校验用例: 405 ≠ 422 → 断言 FAILED
- 装配断言: 方法感知 (path, method) 对（_memory_route_pairs）——4 对均未
  注册 → FAILED。注意纯路径断言会因既有 GET/DELETE 同路径而假绿，故必须
  带方法（详见 TestAssemblyAssertions docstring）
全部新用例 FAILED（断言失败形态，非 ERROR），无收集错误。

本文件为新增文件，不改动 tests/api/test_memory_api.py（既有 707 行，行数
护栏 ≤900）；纯新增端点，无既有端点向后兼容守护场景。

asyncio: pytestmark = pytest.mark.asyncio（镜像 test_memory_api.py，F27
实测必写）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app

pytestmark = pytest.mark.asyncio  # 镜像 test_memory_api.py（F27 实测必写）

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
PREFERENCE_ID = str(uuid.uuid4())
NEW_PATTERN = "称呼主角为林晚晚"
NEW_VALUE = "林晚晚"
USER_NEW_VALUE = "轻声说"


def _client():
    """构造 ASGI 测试客户端（镜像 test_memory_api.py，不触发 lifespan）。"""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _pref_dict(**overrides) -> dict:
    """ProjectPreference dict（镜像 test_memory_api.py 同款字段口径）。"""
    pref = {
        "id": PREFERENCE_ID,
        "project_id": str(PROJECT_ID),
        "category": "addressing",
        "pattern": "称呼主角为林晚",
        "value": "林晚",
        "confidence": 0.67,
        "count": 2,
        "source_events": ["evt-0001", "evt-0002"],
        "created_at": "2026-08-11T10:00:00",
        "updated_at": "2026-08-11T10:00:00",
    }
    pref.update(overrides)
    return pref


def _user_pref_dict(**overrides) -> dict:
    """UserPreference dict（镜像 test_memory_api.py 同款——全局表无 project_id 键）。"""
    pref = {
        "id": str(uuid.uuid4()),
        "category": "style_word",
        "pattern": "说",
        "value": "低声道",
        "confidence": 0.75,
        "count": 3,
        "project_count": 2,
        "source_projects": [str(uuid.uuid4()), str(uuid.uuid4())],
        "source_events": ["evt-0001", "evt-0002", "evt-0003"],
        "created_at": "2026-08-17T10:00:00",
        "updated_at": "2026-08-17T10:00:00",
    }
    pref.update(overrides)
    return pref


def _memory_route_pairs() -> set[tuple[str, str]]:
    """真实 app 已注册的 (path, method) 对（#521 装配契约，方法感知）。

    镜像 test_memory_api.py 的 _memory_route_paths 提取逻辑（fastapi 0.141.1
    lazy _IncludedRouter → effective_route_contexts() 展开 ctx.path），保持
    同样路径筛选（"preferences" or "memory/stats"，足够覆盖 4 个新端点），
    附加 methods 提取（_EffectiveRouteContext 带 methods 属性，2026-08-20
    实测）。
    """
    pairs: set[tuple[str, str]] = set()
    for route in app.routes:
        if hasattr(route, "path"):
            path = str(getattr(route, "path", ""))
            for method in getattr(route, "methods", []) or []:
                pairs.add((path, method.upper()))
        expand = getattr(route, "effective_route_contexts", None)
        if callable(expand):
            for ctx in expand():
                path = str(getattr(ctx, "path", ""))
                for method in getattr(ctx, "methods", []) or []:
                    pairs.add((path, method.upper()))
    return {(p, m) for (p, m) in pairs if "preferences" in p or "memory/stats" in p}


def _override_memory_service(svc) -> None:
    """dependency_overrides 替换 get_memory_service（镜像 test_memory_api.py）。"""
    from inkflow.api.deps import get_memory_service

    app.dependency_overrides[get_memory_service] = lambda: svc


def _call_arg(call, name: str, index: int) -> object:
    """宽松取参：位置或关键字（镜像 test_memory_api.py，兼容两种 GREEN 传参形态）。"""
    args, kwargs = call.await_args
    return args[index] if len(args) > index else kwargs[name]


@pytest.fixture
def memory_svc():
    """Mock MemoryService——4 个 #521 新增方法显式默认值（规则 1m 裸 AsyncMock
    分支陷阱防护；本文件用例只触达这 4 个方法，既有 list/remove/stats 不涉及）。"""
    svc = MagicMock()
    svc.create_preference = AsyncMock(return_value=_pref_dict(pattern=NEW_PATTERN, value=NEW_VALUE))
    svc.create_user_preference = AsyncMock(
        return_value=_user_pref_dict(id=PREFERENCE_ID, value=USER_NEW_VALUE)
    )
    svc.update_preference = AsyncMock(return_value=_pref_dict())
    svc.update_user_preference = AsyncMock(return_value=_user_pref_dict(id=PREFERENCE_ID))
    return svc


@pytest.fixture
def clean_overrides():
    """用例结束清理 dependency_overrides（防跨用例污染，镜像 test_memory_api.py）。"""
    yield
    app.dependency_overrides.clear()


class TestCreateProjectPreferenceEndpoint:
    """POST /api/v1/agent/preferences — 项目偏好手动创建（#521）.

    RED: 端点未注册（该路径现仅 GET）→ POST → FastAPI 405 ≠ 201/422 →
    断言 FAILED（镜像 TestPreferencesEndpoint 形态）。
    """

    async def test_create_preference_201(self, memory_svc, clean_overrides):
        """POST 201: flat ProjectPreference dict（10 字段）+ create_preference
        收到 project_id/category/pattern/value。"""
        _override_memory_service(memory_svc)
        body = {
            "project_id": str(PROJECT_ID),
            "category": "addressing",
            "pattern": NEW_PATTERN,
            "value": NEW_VALUE,
            "confidence": 0.67,
            "count": 2,
        }
        async with _client() as client:
            resp = await client.post("/api/v1/agent/preferences", json=body)
        assert resp.status_code == 201
        data = resp.json()
        for key in (
            "id",
            "project_id",
            "category",
            "pattern",
            "value",
            "confidence",
            "count",
            "source_events",
            "created_at",
            "updated_at",
        ):
            assert key in data
        assert data["id"] == PREFERENCE_ID
        assert data["project_id"] == str(PROJECT_ID)
        assert data["pattern"] == NEW_PATTERN
        assert data["value"] == NEW_VALUE
        assert _call_arg(memory_svc.create_preference, "project_id", 0) == PROJECT_ID
        assert _call_arg(memory_svc.create_preference, "category", 1) == "addressing"
        assert _call_arg(memory_svc.create_preference, "pattern", 2) == NEW_PATTERN
        assert _call_arg(memory_svc.create_preference, "value", 3) == NEW_VALUE

    async def test_create_preference_422_missing_project_id(self, memory_svc, clean_overrides):
        """POST 422: project_id 缺失（Pydantic 必填校验，不触达 service）。"""
        _override_memory_service(memory_svc)
        async with _client() as client:
            resp = await client.post(
                "/api/v1/agent/preferences",
                json={
                    "category": "addressing",
                    "pattern": NEW_PATTERN,
                    "value": NEW_VALUE,
                },
            )
        assert resp.status_code == 422

    async def test_create_preference_422_empty_pattern(self, memory_svc, clean_overrides):
        """POST 422: pattern 空串（Field(min_length=1) 校验，不触达 service）。"""
        _override_memory_service(memory_svc)
        async with _client() as client:
            resp = await client.post(
                "/api/v1/agent/preferences",
                json={
                    "project_id": str(PROJECT_ID),
                    "category": "addressing",
                    "pattern": "",
                    "value": NEW_VALUE,
                },
            )
        assert resp.status_code == 422


class TestCreateUserPreferenceEndpoint:
    """POST /api/v1/agent/user-preferences — 用户级偏好手动创建（#521）.

    RED: 端点未注册（该路径现仅 GET）→ POST → FastAPI 405 ≠ 201/422 →
    断言 FAILED。
    """

    async def test_create_user_preference_201(self, memory_svc, clean_overrides):
        """POST 201: flat UserPreference dict（11 字段，无 project_id 键）。"""
        _override_memory_service(memory_svc)
        body = {
            "category": "style_word",
            "pattern": "说",
            "value": USER_NEW_VALUE,
            "confidence": 0.75,
            "count": 3,
        }
        async with _client() as client:
            resp = await client.post("/api/v1/agent/user-preferences", json=body)
        assert resp.status_code == 201
        data = resp.json()
        for key in (
            "id",
            "category",
            "pattern",
            "value",
            "confidence",
            "count",
            "project_count",
            "source_projects",
            "source_events",
            "created_at",
            "updated_at",
        ):
            assert key in data
        assert "project_id" not in data  # 全局表无 project_id 键
        assert data["id"] == PREFERENCE_ID
        assert data["pattern"] == "说"
        assert data["value"] == USER_NEW_VALUE
        assert _call_arg(memory_svc.create_user_preference, "category", 0) == "style_word"
        assert _call_arg(memory_svc.create_user_preference, "pattern", 1) == "说"
        assert _call_arg(memory_svc.create_user_preference, "value", 2) == USER_NEW_VALUE

    async def test_create_user_preference_422_invalid_category(self, memory_svc, clean_overrides):
        """POST 422: category 非法值（"bogus" 非 PreferenceCategory 枚举，Pydantic 拒绝）。"""
        _override_memory_service(memory_svc)
        async with _client() as client:
            resp = await client.post(
                "/api/v1/agent/user-preferences",
                json={"category": "bogus", "pattern": "说", "value": USER_NEW_VALUE},
            )
        assert resp.status_code == 422


class TestPatchProjectPreferenceEndpoint:
    """PATCH /api/v1/agent/preferences/{preference_id} — 项目偏好编辑（#521）.

    RED: 端点未注册（该路径现仅 DELETE）→ PATCH → FastAPI 405 ≠ 200/404/422
    → 断言 FAILED；404 用例 RED 下先挂在状态码（405≠404），GREEN 后锁 detail
    「偏好不存在」（防「期望 404 撞未注册 404」假绿）。
    """

    async def test_patch_preference_200(self, memory_svc, clean_overrides):
        """PATCH 200: flat ProjectPreference dict + update_preference 收到 id
        与更新字段（pattern/value）。"""
        _override_memory_service(memory_svc)
        memory_svc.update_preference.return_value = _pref_dict(pattern=NEW_PATTERN, value=NEW_VALUE)
        async with _client() as client:
            resp = await client.patch(
                f"/api/v1/agent/preferences/{PREFERENCE_ID}",
                json={"pattern": NEW_PATTERN, "value": NEW_VALUE},
            )
        assert resp.status_code == 200
        data = resp.json()
        for key in (
            "id",
            "project_id",
            "category",
            "pattern",
            "value",
            "confidence",
            "count",
            "source_events",
            "created_at",
            "updated_at",
        ):
            assert key in data
        assert data["id"] == PREFERENCE_ID
        assert data["pattern"] == NEW_PATTERN
        assert data["value"] == NEW_VALUE
        assert _call_arg(memory_svc.update_preference, "preference_id", 0) == PREFERENCE_ID
        assert _call_arg(memory_svc.update_preference, "pattern", 2) == NEW_PATTERN
        assert _call_arg(memory_svc.update_preference, "value", 3) == NEW_VALUE

    async def test_patch_preference_404(self, memory_svc, clean_overrides):
        """PATCH 404: 偏好不存在（PreferenceNotFoundError → detail="偏好不存在"）。"""
        from inkflow.domain.services.memory_service import PreferenceNotFoundError

        _override_memory_service(memory_svc)
        memory_svc.update_preference.side_effect = PreferenceNotFoundError("偏好不存在")
        async with _client() as client:
            resp = await client.patch(
                f"/api/v1/agent/preferences/{PREFERENCE_ID}",
                json={"value": NEW_VALUE},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "偏好不存在"

    async def test_patch_preference_422_empty_body(self, memory_svc, clean_overrides):
        """PATCH 422: body 全空 {}（PreferenceUpdate model_validator 全 None → 422）。"""
        _override_memory_service(memory_svc)
        async with _client() as client:
            resp = await client.patch(f"/api/v1/agent/preferences/{PREFERENCE_ID}", json={})
        assert resp.status_code == 422


class TestPatchUserPreferenceEndpoint:
    """PATCH /api/v1/agent/user-preferences/{preference_id} — 用户级偏好编辑（#521）.

    RED: 端点未注册（该路径现仅 DELETE）→ PATCH → FastAPI 405 ≠ 200/404 →
    断言 FAILED；404 用例 RED 下先挂在状态码，GREEN 后锁 detail。
    """

    async def test_patch_user_preference_200(self, memory_svc, clean_overrides):
        """PATCH 200: flat UserPreference dict（无 project_id）+ update_user_preference
        收到 id 与更新字段（value）。"""
        _override_memory_service(memory_svc)
        memory_svc.update_user_preference.return_value = _user_pref_dict(
            id=PREFERENCE_ID, value=USER_NEW_VALUE
        )
        async with _client() as client:
            resp = await client.patch(
                f"/api/v1/agent/user-preferences/{PREFERENCE_ID}",
                json={"value": USER_NEW_VALUE},
            )
        assert resp.status_code == 200
        data = resp.json()
        for key in (
            "id",
            "category",
            "pattern",
            "value",
            "confidence",
            "count",
            "project_count",
            "source_projects",
            "source_events",
            "created_at",
            "updated_at",
        ):
            assert key in data
        assert "project_id" not in data
        assert data["id"] == PREFERENCE_ID
        assert data["value"] == USER_NEW_VALUE
        assert _call_arg(memory_svc.update_user_preference, "preference_id", 0) == PREFERENCE_ID
        assert _call_arg(memory_svc.update_user_preference, "value", 3) == USER_NEW_VALUE

    async def test_patch_user_preference_404(self, memory_svc, clean_overrides):
        """PATCH 404: 偏好不存在（PreferenceNotFoundError → detail="偏好不存在"）。"""
        from inkflow.domain.services.memory_service import PreferenceNotFoundError

        _override_memory_service(memory_svc)
        memory_svc.update_user_preference.side_effect = PreferenceNotFoundError("偏好不存在")
        async with _client() as client:
            resp = await client.patch(
                f"/api/v1/agent/user-preferences/{PREFERENCE_ID}",
                json={"value": USER_NEW_VALUE},
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "偏好不存在"


class TestAssemblyAssertions:
    """#521 装配契约: 4 个新端点必须在真实 app 注册（方法感知断言）.

    路径复用陷阱: POST /preferences 与既有 GET /preferences 同路径、PATCH
    /preferences/{preference_id} 与既有 DELETE 同路径——纯路径断言在 RED
    阶段会因既有 GET/DELETE 而假绿（路径已存在 ≠ 新方法已注册），故必须锁
    (path, method) 对（_memory_route_pairs，2026-08-20 实测
    _EffectiveRouteContext 带 methods 属性）。

    RED: 4 对均未注册 → 断言 FAILED。
    """

    def test_manual_add_routes_registered_in_app(self):
        """装配: POST preferences / POST user-preferences / PATCH ×2 均已注册。"""
        pairs = _memory_route_pairs()
        assert (
            "/api/v1/agent/preferences",
            "POST",
        ) in pairs, f"缺 POST /api/v1/agent/preferences: {sorted(pairs)}"
        assert (
            "/api/v1/agent/user-preferences",
            "POST",
        ) in pairs, f"缺 POST /api/v1/agent/user-preferences: {sorted(pairs)}"
        assert any(p.startswith("/api/v1/agent/preferences/") and m == "PATCH" for p, m in pairs), (
            f"缺 PATCH /api/v1/agent/preferences/{{id}}: {sorted(pairs)}"
        )
        assert any(
            p.startswith("/api/v1/agent/user-preferences/") and m == "PATCH" for p, m in pairs
        ), f"缺 PATCH /api/v1/agent/user-preferences/{{id}}: {sorted(pairs)}"
