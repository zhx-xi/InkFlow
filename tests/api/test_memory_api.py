"""F28 M5 API RED 契约测试 — agent memory 端点（偏好/统计）+ PATCH drafts 编辑端点（spec §3）.

父侧定稿契约（2026-08-11，实现者以本文件为准）:
- PATCH /api/v1/agent/drafts/{draft_id}  body={"content": str}（必填非空）
  → 200 {"draft_id": str, "status": "draft", "word_count": int, "learned": bool}
  → 404 草稿不存在（DraftNotFoundError）/ 409 状态非 draft（DraftStateError）/
    422 content 为空（Pydantic 校验，镜像 DraftService.create 语义）
  行为: DraftService.update(draft_id, content)（F28 新增方法：更新 content +
  保持 draft 状态 + memory_learning=true 时落编辑事件 + learned=本次是否触发
  新偏好落库）
- GET /api/v1/agent/preferences?project_id=UUID [&category=addressing|style_word|
  structure|other] → 200 {"items": [ProjectPreference dict], "total": N}
  dict 含 id/project_id/category/pattern/value/confidence/count/source_events/
  created_at/updated_at
- DELETE /api/v1/agent/preferences/{preference_id}
  → 200 {"preference_id": str, "deleted": true} / 404（PreferenceNotFoundError）
- GET /api/v1/agent/memory/stats?project_id=UUID → 200 {"project_id": str,
  "agentic": {...}, "learned_preferences": int,
  "baseline_ref": "docs/agent-baseline-2026-08-10.md"}

混合轨（规则 1c）: memory router（inkflow.api.routers.memory）整模块不存在——
顶部只 import 确定存在的符号（app/get_draft_service/Draft/DraftNotFoundError
等）；memory 端点用例在**用例体内** lazy import router + get_memory_service
（用例体 ImportError = FAILED 非 ERROR，禁顶部——顶部会拖垮同文件 PATCH
用例）；PATCH drafts 端点未接线 → 直接打 app → FastAPI 404/405 ≠ 期望 →
断言 FAILED（该批保持断言失败形态 RED）。

依赖注入: 镜像 tests/api/test_f27_agentic_api.py —— app.dependency_overrides
[get_draft_service] / [get_memory_service] 替换为 mock service（全 mock 轨，
零 DB）；get_memory_service 在 deps 不存在（RED），用例体 lazy import。

RED 预期
--------
- PATCH drafts 5 用例: 断言 FAILED（404/405 Method Not Allowed ≠ 期望码）
- memory 端点 5 用例: 用例体 ImportError → FAILED
- 无收集错误、无 ERROR；既有 agent_runs 测试不受影响

asyncio: pytestmark = pytest.mark.asyncio（F27 实测必写，漏写 GREEN 后 async
用例批量报错）；客户端镜像 test_f27_agentic_api.py（AsyncClient +
ASGITransport，不触发 lifespan——全 mock 轨无需 DB）。

契约疑问（GREEN 阶段需定稿）:
- learned 值来源: update 返回值形态（Draft vs (Draft, bool)）未定稿——本文件
  仅锁定 learned 字段存在且为 bool，不锁 True/False 具体值
- PreferenceNotFoundError 定义位置假设 = domain/services/memory_service.py
  （spec §8 编排服务），GREEN 落地时核对
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app
from inkflow.api.deps import get_draft_service
from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.domain.services._word_count import count_words
from inkflow.domain.services.draft_service import DraftNotFoundError, DraftStateError

pytestmark = pytest.mark.asyncio  # F27 实测必写（asyncio_mode=auto 双保险）

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
DRAFT_ID = "draft-0001"
PREFERENCE_ID = str(uuid.uuid4())
UPDATED_CONTENT = "修改后的章节正文内容。"


def _client():
    """构造 ASGI 测试客户端（镜像 test_f27_agentic_api.py，不触发 lifespan）。"""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _draft_dict(**overrides) -> dict:
    """Draft 构造参数字典（kw 覆盖默认，1i 同款防 multiple values）。"""
    base = {
        "id": DRAFT_ID,
        "project_id": PROJECT_ID,
        "chapter_id": CHAPTER_ID,
        "agent_run_id": "run-0001",
        "content": UPDATED_CONTENT,
        "status": DraftStatus.DRAFT,
        "summary": "",
        "created_at": "2026-08-11T10:00:00",
        "confirmed_at": None,
    }
    base.update(overrides)
    return base


def _draft(**overrides) -> Draft:
    """构造 Draft 领域实例（F27 既有模型，顶部 import 可解析）。"""
    return Draft(**_draft_dict(**overrides))


def _pref_dict(**overrides) -> dict:
    """ProjectPreference dict（category/pattern/value/confidence/count/source_events）."""
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


def _stats_payload(**overrides) -> dict:
    """memory/stats 响应口径（spec §3.2 示例逐字段）。"""
    stats = {
        "project_id": str(PROJECT_ID),
        "agentic": {
            "chapters": 5,
            "direct_confirms": 2,
            "avg_diff_chars": 320,
            "modify_rate": 0.6,
            "regenerate_rate": 0.2,
        },
        "learned_preferences": 3,
        "baseline_ref": "docs/agent-baseline-2026-08-10.md",
    }
    stats.update(overrides)
    return stats


def _memory_route_paths() -> set[str]:
    """真实 app 已注册的 memory 相关路由路径（#245 装配契约）。

    不再手动 include_router——F28 缺陷 #245 实锤：router 文件存在但
    app.py 未注册，旧测试手动安装 router 绕过了真实装配（CI 盲区）。
    本 helper 从真实 app.routes 提取路径，供装配断言 + 用例直接打真实 app。
    fastapi 0.141.1 的 include_router 为惰性注册：app.routes 中为
    _IncludedRouter 包装对象（无 path 属性），真实路径经
    effective_route_contexts() 展开（ctx.path）——两条路径都覆盖。
    """
    paths: set[str] = set()
    for route in app.routes:
        if hasattr(route, "path"):
            paths.add(str(getattr(route, "path", "")))
        expand = getattr(route, "effective_route_contexts", None)
        if callable(expand):
            for ctx in expand():
                paths.add(str(getattr(ctx, "path", "")))
    return {p for p in paths if "preferences" in p or "memory/stats" in p}


def _override_memory_service(svc) -> None:
    """dependency_overrides 替换 get_memory_service（RED: deps 无此函数 → ImportError）."""
    from inkflow.api.deps import get_memory_service

    app.dependency_overrides[get_memory_service] = lambda: svc


def _call_arg(call, name: str, index: int) -> object:
    """宽松取参：位置或关键字（规则 1o 同款，兼容两种 GREEN 传参形态）。"""
    args, kwargs = call.await_args
    return args[index] if len(args) > index else kwargs[name]


@pytest.fixture
def draft_svc():
    """Mock DraftService——update 显式默认值（F28 新增方法，当前不存在）。"""
    svc = MagicMock()
    svc.update = AsyncMock(return_value=_draft())
    return svc


@pytest.fixture
def override_draft_svc(draft_svc):
    """dependency_overrides 替换 get_draft_service → mock DraftService."""
    app.dependency_overrides[get_draft_service] = lambda: draft_svc
    yield draft_svc
    app.dependency_overrides.clear()


@pytest.fixture
def memory_svc():
    """Mock MemoryService——全方法显式默认值（裸 AsyncMock 分支陷阱防护，规则 1m）."""
    svc = MagicMock()
    svc.list_preferences = AsyncMock(return_value=([], 0))
    svc.remove_preference = AsyncMock(return_value=None)
    svc.stats = AsyncMock(return_value=_stats_payload())
    return svc


@pytest.fixture
def clean_overrides():
    """用例结束清理 dependency_overrides（防跨用例污染）。"""
    yield
    app.dependency_overrides.clear()


class TestPatchDraftEndpoint:
    """PATCH /api/v1/agent/drafts/{draft_id} — 编辑草稿正文（接线 F27 update_content）.

    RED: 端点未注册 → FastAPI 404/405 ≠ 期望码 → 断言 FAILED（无需 lazy import）。
    """

    async def test_patch_draft_200(self, override_draft_svc):
        """PATCH 200: draft_id/status/word_count/learned 四字段口径。"""
        async with _client() as client:
            resp = await client.patch(
                f"/api/v1/agent/drafts/{DRAFT_ID}", json={"content": UPDATED_CONTENT}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["draft_id"] == DRAFT_ID
        assert data["status"] == "draft"
        assert data["word_count"] == count_words(UPDATED_CONTENT)
        assert isinstance(data["learned"], bool)
        # update 收到 (draft_id, content)
        assert _call_arg(override_draft_svc.update, "draft_id", 0) == DRAFT_ID
        assert _call_arg(override_draft_svc.update, "content", 1) == UPDATED_CONTENT

    async def test_patch_draft_404(self, override_draft_svc):
        """PATCH 404: 草稿不存在（DraftNotFoundError 映射，复用 F27 语义）.

        detail 断言提供 RED 区分力: 端点未注册时 FastAPI 默认 404 detail
        为 "Not Found" ≠ "草稿不存在" → 用例 FAILED（防「期望 404 恰好撞上
        未注册 404」假绿）；GREEN 后映射 detail=str(exc) 匹配 → PASS。
        """
        override_draft_svc.update.side_effect = DraftNotFoundError("草稿不存在")
        async with _client() as client:
            resp = await client.patch(
                f"/api/v1/agent/drafts/{DRAFT_ID}", json={"content": UPDATED_CONTENT}
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "草稿不存在"

    async def test_patch_draft_409(self, override_draft_svc):
        """PATCH 409: 草稿状态非 draft（DraftStateError，confirmed/rejected 不可编辑）。"""
        override_draft_svc.update.side_effect = DraftStateError("草稿已确认")
        async with _client() as client:
            resp = await client.patch(
                f"/api/v1/agent/drafts/{DRAFT_ID}", json={"content": UPDATED_CONTENT}
            )
        assert resp.status_code == 409

    async def test_patch_draft_422_empty_content(self, override_draft_svc):
        """PATCH 422: content 空串（Pydantic 校验，不触达服务）。"""
        async with _client() as client:
            resp = await client.patch(
                f"/api/v1/agent/drafts/{DRAFT_ID}", json={"content": ""}
            )
        assert resp.status_code == 422

    async def test_patch_draft_422_missing_content(self, override_draft_svc):
        """PATCH 422: content 缺失（必填字段）。"""
        async with _client() as client:
            resp = await client.patch(f"/api/v1/agent/drafts/{DRAFT_ID}", json={})
        assert resp.status_code == 422


class TestPreferencesEndpoint:
    """GET/DELETE /api/v1/agent/preferences — 项目已学偏好列表/删除.

    #245 修正（rc1 验证实测）：端点必须在**真实 app 装配**（app.py
    include_router(memory.router)）——旧设计用例体 lazy import + 手动
    include_router 绕过装配（CI 盲区）；现用例直接打真实 app，装配缺失
    时 404 ≠ 期望码 → FAILED（RED 形态）。
    """

    async def test_preferences_list_200(self, memory_svc, clean_overrides):
        """GET preferences → 200: {"items", "total"} + ProjectPreference 字段口径。"""
        memory_svc.list_preferences.return_value = ([_pref_dict()], 1)
        _override_memory_service(memory_svc)
        async with _client() as client:
            resp = await client.get(
                "/api/v1/agent/preferences", params={"project_id": str(PROJECT_ID)}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        item = data["items"][0]
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
            assert key in item
        assert item["pattern"] == "称呼主角为林晚"
        assert item["category"] == "addressing"
        # service 收到 project_id
        assert memory_svc.list_preferences.await_args.kwargs["project_id"] == PROJECT_ID

    async def test_preferences_list_200_domain_object(
        self, memory_svc, clean_overrides
    ):
        """GET preferences 返回真实领域对象 → _dump model_dump 分支（QA 补测 2026-08-11）.

        覆盖 router _dump 的 model_dump 路径（dict 透传之外的领域对象形态）。
        """
        from datetime import UTC, datetime

        from inkflow.domain.models.preference import (
            PreferenceCategory,
            ProjectPreference,
        )

        pref = ProjectPreference(
            id=PREFERENCE_ID,
            project_id=PROJECT_ID,
            category=PreferenceCategory.ADDRESSING,
            pattern="称呼主角为林晚",
            value="林晚",
            confidence=0.67,
            count=2,
            source_events=["evt-0001"],
            created_at=datetime(2026, 8, 11, tzinfo=UTC),
            updated_at=datetime(2026, 8, 11, tzinfo=UTC),
        )
        memory_svc.list_preferences.return_value = ([pref], 1)
        _override_memory_service(memory_svc)
        async with _client() as client:
            resp = await client.get(
                "/api/v1/agent/preferences", params={"project_id": str(PROJECT_ID)}
            )
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["pattern"] == "称呼主角为林晚"
        assert item["category"] == "addressing"
        assert item["count"] == 2

    async def test_preferences_list_category_filter(self, memory_svc, clean_overrides):
        """GET preferences?category=addressing → 过滤参数透传 service。"""
        _override_memory_service(memory_svc)
        async with _client() as client:
            resp = await client.get(
                "/api/v1/agent/preferences",
                params={"project_id": str(PROJECT_ID), "category": "addressing"},
            )
        assert resp.status_code == 200
        assert memory_svc.list_preferences.await_args.kwargs["category"] == "addressing"

    async def test_preferences_delete_200(self, memory_svc, clean_overrides):
        """DELETE preferences/{id} → 200: {"preference_id", "deleted": true}。"""
        _override_memory_service(memory_svc)
        async with _client() as client:
            resp = await client.delete(f"/api/v1/agent/preferences/{PREFERENCE_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["preference_id"] == PREFERENCE_ID
        assert data["deleted"] is True
        assert (
            _call_arg(memory_svc.remove_preference, "preference_id", 0) == PREFERENCE_ID
        )

    async def test_preferences_delete_404(self, memory_svc, clean_overrides):
        """DELETE 404: 偏好不存在（PreferenceNotFoundError 映射）。"""
        from inkflow.domain.services.memory_service import PreferenceNotFoundError

        _override_memory_service(memory_svc)
        memory_svc.remove_preference.side_effect = PreferenceNotFoundError("偏好不存在")
        async with _client() as client:
            resp = await client.delete(f"/api/v1/agent/preferences/{PREFERENCE_ID}")
        assert resp.status_code == 404


class TestMemoryStatsEndpoint:
    """GET /api/v1/agent/memory/stats — 修改率统计（验收判据①对照机制）.

    #245 修正：真实 app 装配断言（同 TestPreferencesEndpoint）。
    """

    async def test_memory_stats_200(self, memory_svc, clean_overrides):
        """stats 200: project_id/agentic 口径/learned_preferences/baseline_ref。"""
        _override_memory_service(memory_svc)
        async with _client() as client:
            resp = await client.get(
                "/api/v1/agent/memory/stats", params={"project_id": str(PROJECT_ID)}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == str(PROJECT_ID)
        assert data["agentic"] == {
            "chapters": 5,
            "direct_confirms": 2,
            "avg_diff_chars": 320,
            "modify_rate": 0.6,
            "regenerate_rate": 0.2,
        }
        assert data["learned_preferences"] == 3
        assert data["baseline_ref"] == "docs/agent-baseline-2026-08-10.md"
        assert memory_svc.stats.await_args.kwargs["project_id"] == PROJECT_ID


class TestMemoryAssembly:
    """#245 装配契约：memory router 必须在真实 app 注册（不再手动安装）。

    rc1 验证实测（2026-08-11）：router 文件存在但 app.py 未 include_router
    → CLI `memory list/remove/stats` 全部 404、openapi 无路径。旧测试手动
    include_router 绕过真实装配（CI 盲区）。本类锁定真实装配防回归；
    同文件其余用例已移除 _install_memory_router 调用（依赖真实装配）。
    """

    def test_memory_routes_registered_in_app(self):
        """app.routes 含 preferences 列表/删除 + memory/stats 三端点。"""
        paths = _memory_route_paths()
        assert "/api/v1/agent/preferences" in paths, f"缺 preferences 列表路由: {paths}"
        assert "/api/v1/agent/memory/stats" in paths, f"缺 memory/stats 路由: {paths}"
        assert any(
            p.startswith("/api/v1/agent/preferences/") for p in paths
        ), f"缺 preferences 删除路由: {paths}"
