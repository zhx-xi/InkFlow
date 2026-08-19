"""F44 v1.2 #475 访谈 LLM 动态提问 API 契约测试（TDD RED 阶段，兄弟文件）。

权威来源：specs/f44-long-task-orchestrator/spec.md §3.2（v1.2 响应扩展——
questions[] 含 kind；respond 响应加 confirmed_items/conflicts/confirming；
PlannerRespondRequest 加 confirm）、§3.5（非 confirming 阶段 confirm → 422）、
§13.5 M13（API 测试：confirm 端点 + confirmed_items/conflicts 响应字段）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约）
════════════════════════════════════════════════════════════════════

1. 【响应契约扩展】（§3.2 v1.2）
   - POST /planner → 201：questions[] 每项含 kind（general|targeted|conflict）；
     响应含 confirmed_items / conflicts / confirming（默认空/False）
   - POST /planner/{id}/respond → 200：响应含 confirmed_items / conflicts /
     confirming（PlannerRespondResult 新字段透传）
   - GET /planner/{id} → 200：session.model_dump 含 confirmed_items / conflicts /
     confirming（PlannerSession v1.2 字段）

2. 【请求体扩展】（§5.1 前端契约 / §3.2）
   - PlannerRespondRequest 加 confirm: bool = False；
     respond 端点把 data.confirm 透传给 svc.respond(..., confirm=data.confirm)

3. 【异常映射】（§3.5 v1.2）
   - 非 confirming 阶段 confirm → svc.respond 抛 ValueError → 422

4. 【mock 策略】同 test_books_api.py：dependency_overrides 注入 AsyncMock
   PlannerService；mock 返回值必须是合法领域对象（UUID 用 uuid4()）；
   PlannerRespondResult 实例带 v1.2 新字段（RED 期 Pydantic extra=ignore
   忽略 → 端点不输出 → 断言失败；GREEN 后透传）。

5. 【RED 预期形态】端点未透传 confirm/未输出 v1.2 字段 → 断言失败；
   confirm 透传用例锁定 svc.respond 调用签名。
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
from inkflow.domain.models.writing_plan import WritingPlan
from inkflow.domain.services.planner_service import PlannerRespondResult

BASE = "/api/v1/agent/books"

SAMPLE_SESSION_ID = uuid.uuid4()
SAMPLE_PROJECT_ID = uuid.uuid4()

_CONFIRMED = [
    {"key": "题材", "value": "悬疑 + 时间悖论科幻", "source": "user"},
    {"key": "篇幅", "value": "10 万字", "source": "user"},
    {"key": "主题", "value": "时间旅者自我救赎", "source": "llm_inferred"},
]


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


def _sample_session_v12() -> PlannerSession:
    """带 v1.2 字段的会话（RED 期 extra=ignore 忽略，GREEN 后生效）。"""
    return PlannerSession(
        id=SAMPLE_SESSION_ID,
        project_id=SAMPLE_PROJECT_ID,
        status="drafting",
        one_liner="写一本关于时间旅者的悬疑小说",
        round=1,
        asked_questions=[
            {
                "id": "q1",
                "text": "题材：悬疑为主，还是悬疑+科幻混合？",
                "template": "悬疑为主，但加入 ___ 元素",
                "kind": "general",
            },
            {
                "id": "q4",
                "text": "时间旅者的穿越机制是设备还是能力？",
                "template": "穿越通过 ___ 实现",
                "kind": "targeted",
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


def _respond_result_v12(
    completed: bool = False,
    confirming: bool = False,
    plan: WritingPlan | None = None,
) -> PlannerRespondResult:
    """带 v1.2 字段的 respond 结果（GREEN 后字段生效）。"""
    return PlannerRespondResult(
        session_id=SAMPLE_SESSION_ID,
        round=2,
        completed=completed,
        questions=[],
        confirmed_items=list(_CONFIRMED),
        conflicts=[
            {
                "round": 1,
                "question_id": "q5",
                "answer": "配角 5 个",
                "conflict_with": "篇幅/复杂度合理性",
                "resolution": "pending",
            }
        ],
        confirming=confirming,
        writing_plan=plan,
    )


# ── POST /planner：v1.2 响应字段 ───────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_start_response_has_v12_fields(client, override_planner):
    """启动访谈 → 201：questions 含 kind + confirmed_items/conflicts/confirming。"""
    planner = override_planner
    planner.start.return_value = _sample_session_v12()

    resp = await client.post(
        f"{BASE}/planner",
        json={
            "project_id": str(SAMPLE_PROJECT_ID),
            "one_liner": "写一本关于时间旅者的悬疑小说",
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["confirmed_items"] == []
    assert body["conflicts"] == []
    assert body["confirming"] is False
    kinds = {q.get("kind") for q in body["questions"]}
    assert "general" in kinds and "targeted" in kinds


# ── POST /planner/{id}/respond：v1.2 响应字段 + confirm 透传 ───────


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_respond_response_has_v12_fields(client, override_planner):
    """回复 → 200：响应含 confirmed_items/conflicts/confirming（新字段透传）。"""
    planner = override_planner
    planner.respond.return_value = _respond_result_v12()

    resp = await client.post(
        f"{BASE}/planner/{SAMPLE_SESSION_ID}/respond",
        json={"answers": {"q1": "悬疑为主，加入时间悖论"}, "auto": False},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["confirmed_items"] == _CONFIRMED
    assert body["conflicts"][0]["conflict_with"] == "篇幅/复杂度合理性"
    assert body["conflicts"][0]["resolution"] == "pending"
    assert body["confirming"] is False


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_respond_confirm_true_passed_to_service(
    client, override_planner
):
    """末尾总体确认：respond body {confirm: true} → svc.respond 收到 confirm=True。"""
    planner = override_planner
    plan = WritingPlan(
        id=uuid.uuid4(),
        project_id=SAMPLE_PROJECT_ID,
        title="写一本关于时间旅者的悬疑小说",
        status="ready",
        limits={"max_chapters": 1, "max_agent_calls": 1},
        progress={},
        execution_refs={},
    )
    planner.respond.return_value = _respond_result_v12(
        completed=True, confirming=True, plan=plan
    )

    resp = await client.post(
        f"{BASE}/planner/{SAMPLE_SESSION_ID}/respond",
        json={"answers": {}, "confirm": True},
    )

    assert resp.status_code == 200
    assert resp.json()["completed"] is True
    planner.respond.assert_awaited_once_with(
        SAMPLE_SESSION_ID, {}, auto=False, confirm=True
    )


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_respond_confirm_not_confirming_422(client, override_planner):
    """非 confirming 阶段 confirm → 422（§3.5 v1.2 异常映射）。"""
    planner = override_planner
    planner.respond.side_effect = ValueError("非确认阶段")

    resp = await client.post(
        f"{BASE}/planner/{SAMPLE_SESSION_ID}/respond",
        json={"answers": {}, "confirm": True},
    )

    assert resp.status_code == 422


# ── GET /planner/{id}：v1.2 字段 ───────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.api
async def test_planner_get_response_has_v12_fields(client, override_planner):
    """会话状态 → 200：响应含 confirmed_items/conflicts/confirming（审计回溯）。"""
    planner = override_planner
    session = _sample_session_v12()
    session.confirming = True
    session.confirmed_items = list(_CONFIRMED)
    planner.get.return_value = session

    resp = await client.get(f"{BASE}/planner/{SAMPLE_SESSION_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["confirmed_items"] == _CONFIRMED
    assert body["conflicts"] == []
    assert body["confirming"] is True
