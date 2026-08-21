"""#544 书级编排项目可选 + 起点模板 —— planner 起点模式 API 契约测试（TDD RED 阶段，兄弟文件）。

权威来源：issue #544（书级编排项目可选 + 起点模板 new/continue/branch）。
本文件为 `api/routers/books.py` 的 PlannerStartRequest / start_planner
扩展（mode / source_outline_id）定义契约。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【请求体扩展】PlannerStartRequest 新增可选字段（默认值向后兼容）：
   - mode: str = "new"（枚举 new/continue/branch）
   - source_outline_id: uuid.UUID | None = None
   start_planner 把两者透传给 svc.start(mode=..., source_outline_id=...)；
   缺省（不带 mode）→ svc.start 收到 mode="new"、source_outline_id=None。

2. 【异常映射 422】（裁定：校验放 service，router 兜底映射）
   PlannerService.start 负责校验并抛 ValueError（见
   tests/unit/test_planner_service_start_mode.py）：
   - mode 非法 → ValueError("不支持的起点模式: {mode}")
   - mode=branch 且 source_outline_id=None → ValueError("分支起点需要源大纲")
   router 必须把 svc.start 的 ValueError 映射为 422 + detail=str(e)。
   本测试通过 svc.start.side_effect 注入上述 ValueError，同时兼容
   「router 侧 Pydantic 校验」的实现形态（422 detail 同契约）。

3. 【mock 策略】同 test_books_api.py / test_books_api_v12.py：
   dependency_overrides 注入 AsyncMock 版 PlannerService；mock 返回值
   必须是合法领域对象（UUID 用 uuid4()）。

4. 【RED 预期形态】请求体未透传 mode/source_outline_id → svc.start
   调用断言失败（recorded 调用缺 kwargs）；router 未映射 ValueError →
   500（断言 422 失败）。
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import inkflow.api.routers.books  # noqa: F401  # 模块契约断言
from inkflow.api.app import app
from inkflow.api.routers.books import get_planner_service
from inkflow.domain.models.planner_session import PlannerSession

BASE = "/api/v1/agent/books"

SAMPLE_SESSION_ID = uuid.uuid4()
SAMPLE_PROJECT_ID = uuid.uuid4()
SOURCE_OUTLINE_ID = uuid.uuid4()
ONE_LINER = "写一本关于时间旅者的悬疑小说"


@pytest.fixture
def client(monkeypatch):
    """无 token 模式 AsyncClient（INKFLOW_SERVER_TOKEN 未设置直通）。"""
    monkeypatch.delenv("INKFLOW_SERVER_TOKEN", raising=False)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def override_planner(client):
    """注入 AsyncMock 版 PlannerService（依赖 override）。"""
    planner = AsyncMock()

    async def _planner_override():
        return planner

    app.dependency_overrides[get_planner_service] = _planner_override
    yield planner
    app.dependency_overrides.clear()


def _sample_session() -> PlannerSession:
    """合法领域会话（RED 期现有字段即够，GREEN 后新字段默认值兜底）。"""
    return PlannerSession(
        id=SAMPLE_SESSION_ID,
        project_id=SAMPLE_PROJECT_ID,
        status="drafting",
        one_liner=ONE_LINER,
        round=1,
        asked_questions=[
            {
                "id": "q1",
                "text": "题材：悬疑为主，还是悬疑+科幻混合？",
                "template": "悬疑为主，但加入 ___ 元素",
                "kind": "general",
            },
            {
                "id": "q2",
                "text": "篇幅：预计多少字？",
                "template": "约 ___ 字",
                "kind": "general",
            },
        ],
        answers={},
        authorized=[],
        confirmed_items=[],
        conflicts=[],
        confirming=False,
        writing_plan_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ── POST /planner：起点模式透传（#544）─────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_start_default_mode_new(client, override_planner):
    """不带 mode → 201：svc.start 收到 mode="new"、source_outline_id=None。"""
    planner = override_planner
    planner.start.return_value = _sample_session()

    resp = await client.post(
        f"{BASE}/planner",
        json={
            "project_id": str(SAMPLE_PROJECT_ID),
            "one_liner": ONE_LINER,
        },
    )

    assert resp.status_code == 201
    assert resp.json()["session_id"] == str(SAMPLE_SESSION_ID)
    planner.start.assert_awaited_once_with(
        SAMPLE_PROJECT_ID, ONE_LINER, mode="new", source_outline_id=None
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_start_continue_mode_passes_source(client, override_planner):
    """mode=continue + source_outline_id → svc.start 收到两参数原样。"""
    planner = override_planner
    planner.start.return_value = _sample_session()

    resp = await client.post(
        f"{BASE}/planner",
        json={
            "project_id": str(SAMPLE_PROJECT_ID),
            "one_liner": ONE_LINER,
            "mode": "continue",
            "source_outline_id": str(SOURCE_OUTLINE_ID),
        },
    )

    assert resp.status_code == 201
    planner.start.assert_awaited_once_with(
        SAMPLE_PROJECT_ID, ONE_LINER, mode="continue", source_outline_id=SOURCE_OUTLINE_ID
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_start_branch_mode_passes_source(client, override_planner):
    """mode=branch + source_outline_id → svc.start 收到两参数原样。"""
    planner = override_planner
    planner.start.return_value = _sample_session()

    resp = await client.post(
        f"{BASE}/planner",
        json={
            "project_id": str(SAMPLE_PROJECT_ID),
            "one_liner": ONE_LINER,
            "mode": "branch",
            "source_outline_id": str(SOURCE_OUTLINE_ID),
        },
    )

    assert resp.status_code == 201
    planner.start.assert_awaited_once_with(
        SAMPLE_PROJECT_ID, ONE_LINER, mode="branch", source_outline_id=SOURCE_OUTLINE_ID
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_start_branch_without_source_422(client, override_planner):
    """mode=branch 缺 source_outline_id → 422，detail="分支起点需要源大纲"。"""
    planner = override_planner
    planner.start.side_effect = ValueError("分支起点需要源大纲")

    resp = await client.post(
        f"{BASE}/planner",
        json={
            "project_id": str(SAMPLE_PROJECT_ID),
            "one_liner": ONE_LINER,
            "mode": "branch",
        },
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "分支起点需要源大纲"


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_start_invalid_mode_422(client, override_planner):
    """非法 mode → 422，detail="不支持的起点模式: xxx"。"""
    planner = override_planner
    planner.start.side_effect = ValueError("不支持的起点模式: xxx")

    resp = await client.post(
        f"{BASE}/planner",
        json={
            "project_id": str(SAMPLE_PROJECT_ID),
            "one_liner": ONE_LINER,
            "mode": "xxx",
        },
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "不支持的起点模式: xxx"
