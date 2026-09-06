"""F27 M6 API RED 契约测试 — agentic/generate + runs/drafts 端点（Mock 服务层，spec §3）.

TDD RED 阶段：路由与 deps 未实现，预期全部失败（deps import 收集期失败 + 端点 404）。

需 pytestmark = pytest.mark.asyncio（既有 API 测试同款，asyncio_mode=auto 双保险）。

══════════════════════════════════════════════════════════════════════════
HTTP 契约（实现者以本文件为准，spec §3.1/§3.3）:
- POST /api/v1/writing/agentic/generate
  body: {"project_id": "<UUID>", "chapter_id": "<UUID>", "outline": "...",
         "context": "...", "min_words": 2000, "style_hint": "..."|null,
         "max_steps": 12|null, "token_budget": 32000|null}（None 字段剔除）
  → 200: {"run_id", "status", "draft_id", "final_content", "word_count",
          "steps": [...], "token_usage_total", "terminated_by"}
  guardrail 双形态均 200（status="terminated_by_guardrail"——ADR-D 产物保留，
  非 HTTP 错误）
  404: 项目/章节不存在（服务层 NotFound 语义）· 422: max_steps 越界（Pydantic）
- GET /api/v1/agent/runs?project_id=<UUID>&limit=20 → {"items": [...], "total": N}
- GET /api/v1/agent/runs/{run_id} → 200 run dict（steps 决策轨迹全量）/ 404
- GET /api/v1/agent/drafts?project_id=<UUID>&status=draft → {"items": [...], "total": N}
- POST /api/v1/agent/drafts/{draft_id}/confirm（body {"chapter_id"} 可选）
  → 200 {"draft_id", "status": "confirmed", "chapter_id"} / 404 草稿不存在 /
  409 状态非 draft（重复确认）
- POST /api/v1/agent/drafts/{draft_id}/reject
  → 200 {"draft_id", "status": "rejected"} / 404
══════════════════════════════════════════════════════════════════════════

依赖装配（deps.py 新增，测试 override 替换）:
- get_agentic_writer_service → AgenticWriterService（async run(request) -> AgentRun）
- get_draft_service → DraftService（async list/confirm/reject）
- get_agent_run_repo → SQLiteAgentRunRepository（async get/list）

RED 预期
--------
deps 无 get_agentic_writer_service/get_draft_service/get_agent_run_repo →
顶部 import 收集期失败（ModuleNotFoundError，1c 形态）；端点未注册 → 404。

asyncio 模式: 本 venv 实测头部 asyncio: mode=Mode.AUTO；全部用例 async def。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from inkflow.api.deps import (
    get_agent_run_repo,
    get_agentic_writer_service,
    get_draft_service,
)
from inkflow.domain.models.agent_run import (
    AgenticWriteRequest,
    AgentRun,
    AgentRunStatus,
)
from inkflow.domain.models.draft import Draft, DraftStatus

pytestmark = pytest.mark.asyncio  # 既有 API 测试同款（test_project_api.py 先例）

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
RUN_ID = "run-0001"
DRAFT_ID = "draft-0001"


def _client():
    """构造 ASGI 测试客户端。"""
    from inkflow.api.app import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _run_dict(**overrides) -> dict:
    run = {
        "id": RUN_ID,
        "project_id": str(PROJECT_ID),
        "chapter_id": str(CHAPTER_ID),
        "mode": "agentic",
        "status": "completed",
        "steps": [
            {
                "index": 0,
                "message_content": "",
                "tool_calls": [
                    {
                        "step_index": 0,
                        "tool_name": "search_characters",
                        "arguments": {"project_id": str(PROJECT_ID)},
                        "result": '{"ok": true, "data": []}',
                        "is_error": False,
                    }
                ],
                "tokens": 120,
            }
        ],
        "final_content": "正文。",
        "draft_id": DRAFT_ID,
        "model": "zhipu/glm-4.5",
        "token_usage_total": 420,
        "terminated_by": "llm",
        "created_at": "2026-08-10T12:00:00",
        "updated_at": "2026-08-10T12:00:05",
    }
    run.update(overrides)
    return run


def _generate_payload() -> dict:
    return {
        "project_id": str(PROJECT_ID),
        "chapter_id": str(CHAPTER_ID),
        "outline": "本章大纲",
        "min_words": 2000,
    }


@pytest.fixture
def overrides():
    """替换 deps 三个服务依赖 → Mock（AsyncMock 方法）。"""
    from inkflow.api.app import app

    writer_svc = MagicMock()
    writer_svc.run = AsyncMock(
        return_value=AgentRun(**{**_run_dict(), "status": AgentRunStatus.COMPLETED})
    )

    draft_svc = MagicMock()
    draft_svc.list = AsyncMock(return_value=([], 0))
    draft_svc.confirm = AsyncMock(
        return_value=Draft(
            id=DRAFT_ID,
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            content="确认后的正文。",
            status=DraftStatus.CONFIRMED,
            created_at="2026-08-10T12:00:00",
            confirmed_at="2026-08-10T12:05:00",
        )
    )
    draft_svc.reject = AsyncMock(
        return_value=Draft(
            id=DRAFT_ID,
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            content="草稿。",
            status=DraftStatus.REJECTED,
            created_at="2026-08-10T12:00:00",
            confirmed_at=None,
        )
    )

    run_repo = MagicMock()
    run_repo.get = AsyncMock(return_value=None)
    run_repo.list = AsyncMock(return_value=([], 0))

    app.dependency_overrides[get_agentic_writer_service] = lambda: writer_svc
    app.dependency_overrides[get_draft_service] = lambda: draft_svc
    app.dependency_overrides[get_agent_run_repo] = lambda: run_repo
    yield {"writer": writer_svc, "draft": draft_svc, "run_repo": run_repo}
    app.dependency_overrides.clear()


# ── agentic/generate ────────────────────────────────────────────────


async def test_agentic_generate_completed(overrides):
    """POST /writing/agentic/generate → 200 completed（含 run_id/draft_id/steps）。"""
    writer = overrides["writer"]
    writer.run.return_value = AgentRun(
        id=RUN_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        status=AgentRunStatus.COMPLETED,
        steps=[],
        final_content="正文。",
        draft_id=DRAFT_ID,
        model="zhipu/glm-4.5",
        token_usage_total=420,
        terminated_by="llm",
        created_at="2026-08-10T12:00:00",
        updated_at="2026-08-10T12:00:05",
    )
    async with _client() as client:
        resp = await client.post(
            "/api/v1/writing/agentic/generate", json=_generate_payload()
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["run_id"] == RUN_ID
    assert data["draft_id"] == DRAFT_ID
    assert data["terminated_by"] == "llm"


async def test_agentic_generate_guardrail_200(overrides):
    """guardrail 终止（max_steps 超限）→ 200 + terminated_by_guardrail（ADR-D 非 HTTP 错误）。"""
    writer = overrides["writer"]
    writer.run.return_value = AgentRun(
        id=RUN_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        status=AgentRunStatus.TERMINATED_BY_GUARDRAIL,
        steps=[],
        final_content="",
        draft_id=None,
        model="zhipu/glm-4.5",
        token_usage_total=420,
        terminated_by="max_steps",
        created_at="2026-08-10T12:00:00",
        updated_at="2026-08-10T12:00:05",
    )
    async with _client() as client:
        resp = await client.post(
            "/api/v1/writing/agentic/generate", json=_generate_payload()
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "terminated_by_guardrail"
    assert resp.json()["terminated_by"] == "max_steps"


async def test_agentic_generate_request_body_passthrough(overrides):
    """请求体字段透传：max_steps/token_budget 显式传递时含在请求（None 剔除）。"""
    writer = overrides["writer"]
    writer.run.return_value = AgentRun(
        id=RUN_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        status=AgentRunStatus.COMPLETED,
        steps=[],
        final_content="正文。",
        model="zhipu/glm-4.5",
        token_usage_total=420,
        terminated_by="llm",
        created_at="2026-08-10T12:00:00",
        updated_at="2026-08-10T12:00:05",
    )
    payload = _generate_payload()
    payload["max_steps"] = 8
    payload["token_budget"] = 16000
    async with _client() as client:
        resp = await client.post("/api/v1/writing/agentic/generate", json=payload)
    assert resp.status_code == 200
    request: AgenticWriteRequest = writer.run.await_args.args[0]
    assert request.max_steps == 8
    assert request.token_budget == 16000
    assert request.min_words == 2000


async def test_agentic_generate_404(overrides):
    """项目/章节不存在 → 404。"""
    from inkflow.domain.services.agentic_writer_service import AgenticWriteNotFoundError

    writer = overrides["writer"]
    writer.run.side_effect = AgenticWriteNotFoundError("章节不存在")
    async with _client() as client:
        resp = await client.post(
            "/api/v1/writing/agentic/generate", json=_generate_payload()
        )
    assert resp.status_code == 404
    # 🔒 强化（#524）：锁 detail（router 将 AgenticWriteNotFoundError 消息透传为 404 detail）
    assert resp.json()["detail"] == "章节不存在"


async def test_agentic_generate_422_invalid_max_steps(overrides):
    """max_steps 越界（0）→ 422（Pydantic 校验，不触达服务）。

    #929 迁移：补 overrides 替身——旧实现下依赖解析恰好成功（keyless 回退捡
    provider），#929 fail-fast 后 keyless 依赖解析必 422（str detail），本用例
    锚的是「参数校验 422」形态（list detail），与 docstring「不触达服务」自洽。
    """
    async with _client() as client:
        payload = _generate_payload()
        payload["max_steps"] = 0
        resp = await client.post("/api/v1/writing/agentic/generate", json=payload)
    assert resp.status_code == 422
    # 🔒 强化（#524）：Pydantic 422 detail 为 list 形态——锁形态区分「参数校验 422」与「业务 422」
    assert isinstance(resp.json()["detail"], list)
    assert any(
        "max_steps" in str(item.get("loc", "")) for item in resp.json()["detail"]
    )


# ── agent runs 端点 ─────────────────────────────────────────────────


async def test_runs_list(overrides):
    """GET /agent/runs → {"items", "total"}。"""
    run_repo = overrides["run_repo"]
    run_repo.list.return_value = ([_run_dict()], 1)
    async with _client() as client:
        resp = await client.get(
            "/api/v1/agent/runs", params={"project_id": str(PROJECT_ID), "limit": 20}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == RUN_ID
    # repo 收到正确参数
    assert run_repo.list.await_args.kwargs["project_id"] == PROJECT_ID


async def test_runs_get(overrides):
    """GET /agent/runs/{run_id} → 200 run dict（steps 决策轨迹）。"""
    run_repo = overrides["run_repo"]
    run_repo.get.return_value = _run_dict()
    async with _client() as client:
        resp = await client.get(f"/api/v1/agent/runs/{RUN_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == RUN_ID
    assert data["steps"][0]["tool_calls"][0]["tool_name"] == "search_characters"


async def test_runs_get_404(overrides):
    """GET /agent/runs/{run_id} 无记录 → 404。"""
    async with _client() as client:
        resp = await client.get(f"/api/v1/agent/runs/{RUN_ID}")
    assert resp.status_code == 404
    # 🔒 强化（#524）：锁 detail（router 静态文案「运行记录不存在」）
    assert resp.json()["detail"] == "运行记录不存在"


# ── agent drafts 端点 ───────────────────────────────────────────────


async def test_drafts_list(overrides):
    """GET /agent/drafts → {"items", "total"}（status 过滤透传）。"""
    draft_svc = overrides["draft"]
    draft_svc.list.return_value = ([], 2)
    async with _client() as client:
        resp = await client.get(
            "/api/v1/agent/drafts",
            params={"project_id": str(PROJECT_ID), "status": "draft"},
        )
    assert resp.status_code == 200
    assert resp.json()["total"] == 2
    assert draft_svc.list.await_args.kwargs["status"] == DraftStatus.DRAFT


async def test_drafts_confirm(overrides):
    """POST /agent/drafts/{id}/confirm → 200 confirmed。"""
    async with _client() as client:
        resp = await client.post(f"/api/v1/agent/drafts/{DRAFT_ID}/confirm")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"
    assert data["draft_id"] == DRAFT_ID


async def test_drafts_confirm_409(overrides):
    """重复确认（状态非 draft）→ 409。"""
    from inkflow.domain.services.draft_service import DraftStateError

    draft_svc = overrides["draft"]
    draft_svc.confirm.side_effect = DraftStateError("草稿已确认")
    async with _client() as client:
        resp = await client.post(f"/api/v1/agent/drafts/{DRAFT_ID}/confirm")
    assert resp.status_code == 409
    # 🔒 强化（#524）：锁 detail（router 将 DraftStateError 消息透传为 409 detail）
    assert resp.json()["detail"] == "草稿已确认"


async def test_drafts_confirm_404(overrides):
    """草稿不存在 → 404。"""
    from inkflow.domain.services.draft_service import DraftNotFoundError

    draft_svc = overrides["draft"]
    draft_svc.confirm.side_effect = DraftNotFoundError("草稿不存在")
    async with _client() as client:
        resp = await client.post(f"/api/v1/agent/drafts/{DRAFT_ID}/confirm")
    assert resp.status_code == 404
    # 🔒 强化（#524）：锁 detail 含「不存在」（DraftNotFoundError 消息透传）
    assert resp.json()["detail"] == "草稿不存在"


async def test_drafts_reject(overrides):
    """POST /agent/drafts/{id}/reject → 200 rejected。"""
    async with _client() as client:
        resp = await client.post(f"/api/v1/agent/drafts/{DRAFT_ID}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


# ── #976: confirm 增 source_outline_id / title（ConfirmRequest 扩展契约） ──


async def test_drafts_confirm_with_source_outline_and_title(overrides):
    """【R】confirm body 含 source_outline_id+title → 200 + svc.confirm 收到 kwargs.

    当前 ConfirmRequest 仅 chapter_id（extra=ignore 吞掉未知键），router 只传
    chapter_id → await_args.kwargs 无 source_outline_id/title → KeyError（RED）。
    """
    draft_svc = overrides["draft"]
    outline_id = "54c2a0e1-1111-4222-8333-444455556666"
    async with _client() as client:
        resp = await client.post(
            f"/api/v1/agent/drafts/{DRAFT_ID}/confirm",
            json={"source_outline_id": outline_id, "title": "T"},
        )
    assert resp.status_code == 200
    kwargs = draft_svc.confirm.await_args.kwargs
    assert kwargs["source_outline_id"] == uuid.UUID(outline_id)
    assert kwargs["title"] == "T"


async def test_drafts_confirm_existing_body_shape_compat(overrides):
    """【G】既有 body 形态（无新键）→ svc.confirm 兼容调用
    （chapter_id/source_outline_id/title 缺省 None）。"""
    draft_svc = overrides["draft"]
    async with _client() as client:
        resp = await client.post(
            f"/api/v1/agent/drafts/{DRAFT_ID}/confirm",
            json={},
        )
    assert resp.status_code == 200
    kwargs = draft_svc.confirm.await_args.kwargs
    assert kwargs.get("chapter_id") is None
    assert kwargs.get("source_outline_id") is None
    assert kwargs.get("title") is None


# ── #275: 孤儿草稿清理端点（prune-orphans） ──


async def test_drafts_prune_orphans(overrides):
    """#275 清理端点: POST /agent/drafts/prune-orphans → 200 {"deleted": N}。

    RED 预期: 端点未注册 → 404 → status_code 断言 FAILED（clean FAILED）。
    """
    from unittest.mock import AsyncMock

    draft_svc = overrides["draft"]
    draft_svc.prune_orphans = AsyncMock(return_value=3)

    async with _client() as client:
        resp = await client.post("/api/v1/agent/drafts/prune-orphans")

    assert resp.status_code == 200
    assert resp.json() == {"deleted": 3}
    draft_svc.prune_orphans.assert_awaited_once_with(dry_run=False)


async def test_drafts_prune_orphans_dry_run(overrides):
    """#275 清理端点: body {"dry_run": true} → svc 收到 dry_run=True。"""
    from unittest.mock import AsyncMock

    draft_svc = overrides["draft"]
    draft_svc.prune_orphans = AsyncMock(return_value=2)

    async with _client() as client:
        resp = await client.post(
            "/api/v1/agent/drafts/prune-orphans", json={"dry_run": True}
        )

    assert resp.status_code == 200
    assert resp.json() == {"deleted": 2}
    draft_svc.prune_orphans.assert_awaited_once_with(dry_run=True)
