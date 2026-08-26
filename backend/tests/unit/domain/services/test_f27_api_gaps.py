"""F27 覆盖率缺口补测 C — agent_runs API 边界 + 二/三轮服务与 CLI 分支.

原 test_f27_coverage_gaps.py 拆分（1131 行超 monster-file 900 护栏，2026-08-10）。
代码已实现（GREEN），补测直接通过（非 RED）。

asyncio 模式: pyproject asyncio_mode = "auto"；文件级 pytestmark 双保险。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.asyncio

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
DRAFT_ID = "draft-0001"
RUN_ID = "run-0001"


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ── agent_runs API 边界（reject 404/409 + _parse_id 防御） ──────────


async def test_agent_runs_parse_id_invalid_404():
    """_parse_id 非法 UUID → 404（防御分支）。"""
    from fastapi import HTTPException

    from inkflow.api.routers.agent_runs import _parse_id

    with pytest.raises(HTTPException) as exc_info:
        _parse_id("not-a-uuid")
    assert exc_info.value.status_code == 404


async def test_agent_runs_reject_404():
    """reject 草稿不存在 → 404（端点错误面）。"""
    from httpx import ASGITransport, AsyncClient

    from inkflow.api.app import app
    from inkflow.api.deps import get_draft_service
    from inkflow.domain.services.draft_service import DraftNotFoundError

    draft_svc = MagicMock()
    draft_svc.reject = AsyncMock(side_effect=DraftNotFoundError("草稿不存在"))
    app.dependency_overrides[get_draft_service] = lambda: draft_svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"/api/v1/agent/drafts/{DRAFT_ID}/reject")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "草稿不存在"
    finally:
        app.dependency_overrides.clear()


async def test_agent_runs_reject_409():
    """reject 状态非 draft → 409。"""
    from httpx import ASGITransport, AsyncClient

    from inkflow.api.app import app
    from inkflow.api.deps import get_draft_service
    from inkflow.domain.services.draft_service import DraftStateError

    draft_svc = MagicMock()
    draft_svc.reject = AsyncMock(side_effect=DraftStateError("草稿已确认"))
    app.dependency_overrides[get_draft_service] = lambda: draft_svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"/api/v1/agent/drafts/{DRAFT_ID}/reject")
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.clear()


# ── 第二轮缺口补测（coverage 98.37/94.90 → 门禁 98.5/95.0） ─────────


# draft_service 剩余分支（get/list 透传 + audit/chapter None）


async def test_draft_get_and_list_passthrough():
    """get/list 透传 repo（覆盖 103-104/124-130）。"""
    from inkflow.domain.services.draft_service import DraftService

    repo = AsyncMock()
    repo.get.return_value = None
    repo.list.return_value = ([], 0)
    svc = DraftService(draft_repo=repo)
    assert await svc.get("nope") is None
    items, total = await svc.list(PROJECT_ID, status=None)
    assert items == [] and total == 0
    repo.list.assert_awaited_once_with(PROJECT_ID, status=None, offset=0, limit=50)


async def test_draft_create_without_audit_service():
    """audit_service=None 时 create 不落审计（覆盖 90->99 分支）。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftService

    repo = AsyncMock()
    repo.create.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    svc = DraftService(draft_repo=repo, audit_service=None)
    draft = await svc.create(project_id=PROJECT_ID, content="x")
    assert draft.id == DRAFT_ID


async def test_draft_confirm_without_chapter_service():
    """chapter_service=None 时 confirm 跳过章节写入（仅状态流转，覆盖 None 分支）。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftService

    repo = AsyncMock()
    repo.get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    repo.update_status.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.CONFIRMED,
        created_at=_utcnow(),
        confirmed_at=_utcnow(),
    )
    svc = DraftService(draft_repo=repo, chapter_service=None, audit_service=None)
    confirmed = await svc.confirm(DRAFT_ID)
    assert confirmed.status == DraftStatus.CONFIRMED


async def test_draft_reject_without_audit_service():
    """audit_service=None 时 reject 不落审计。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftService

    repo = AsyncMock()
    repo.get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    repo.update_status.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.REJECTED,
        created_at=_utcnow(),
    )
    svc = DraftService(draft_repo=repo, audit_service=None)
    rejected = await svc.reject(DRAFT_ID)
    assert rejected.status == DraftStatus.REJECTED


# agentic_writer_service 剩余边界分支


async def test_agentic_invoke_returns_non_dict():
    """invoke 返回非 dict → history 为空 → steps 空 + completed 防御（覆盖 238/254/263）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _WeirdAgent:
        async def invoke(self, messages, config=None):
            return "not a dict"

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=lambda _request: _WeirdAgent(),
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    # 无 AI 消息 → empty_content 护栏（历史无 AI 消息 → _is_empty_final True）
    assert run.status == AgentRunStatus.TERMINATED_BY_GUARDRAIL


async def test_agentic_request_with_context_and_style():
    """请求带 context + style_hint → 初始消息含上下文与风格（覆盖 244/247）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _CaptureAgent:
        def __init__(self):
            self.seen = []

        async def invoke(self, messages, config=None):
            self.seen.append(list(messages))
            return {
                "messages": [
                    {
                        "type": "ai",
                        "content": "正文。",
                        "response_metadata": {"usage": {"total_tokens": 5}},
                    }
                ]
            }

    agent = _CaptureAgent()
    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=lambda _request: agent,
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
            context="前文摘要",
            min_words=1500,
            style_hint="冷峻硬汉风",
        )
    )
    assert run.status == AgentRunStatus.COMPLETED
    initial = agent.seen[0][0]["content"]
    assert "前文摘要" in initial
    assert "1500" in initial
    assert "冷峻硬汉风" in initial


async def test_agentic_token_usage_weird_metadata():
    """usage 非 dict / total_tokens 非法 → token 提取防御（覆盖 88/91-92）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _WeirdMetaAgent:
        async def invoke(self, messages, config=None):
            return {
                "messages": [
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "name": "search_characters",
                                "args": {"project_id": str(PROJECT_ID)},
                            }
                        ],
                        "response_metadata": {"usage": "not-a-dict"},
                    },
                    {"type": "tool", "name": "search_characters", "content": '{"ok": true}'},
                    {
                        "type": "ai",
                        "content": "正文。",
                        "response_metadata": {"usage": {"total_tokens": "NaN"}},
                    },
                ]
            }

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=lambda _request: _WeirdMetaAgent(),
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    assert run.status == AgentRunStatus.COMPLETED
    assert run.token_usage_total == 0  # 防御：非法 usage 均计 0


async def test_agentic_tool_result_missing():
    """tool_call 无后续同名 tool 消息 → result 空串（覆盖 318->317/320）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _NoResultAgent:
        async def invoke(self, messages, config=None):
            # tool_call 后无对应 tool 消息（异常历史形态）
            return {
                "messages": [
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "name": "search_characters",
                                "args": {"project_id": str(PROJECT_ID)},
                            }
                        ],
                    },
                    {
                        "type": "ai",
                        "content": "正文。",
                        "response_metadata": {"model": "zhipu/glm-4.5"},
                    },
                ]
            }

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=lambda _request: _NoResultAgent(),
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    assert run.status == AgentRunStatus.COMPLETED
    assert run.model == "zhipu/glm-4.5"  # 覆盖 _extract_model 命中分支（338）
    results = [tc.result for step in run.steps for tc in step.tool_calls]
    assert any(r == "" for r in results)


async def test_agentic_token_budget_guardrail():
    """累计 tokens 超预算 → token_budget 护栏（覆盖 377）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _TokenHeavyAgent:
        async def invoke(self, messages, config=None):
            return {
                "messages": [
                    {
                        "type": "ai",
                        "content": "正文。",
                        "response_metadata": {"usage": {"total_tokens": 50000}},
                    },
                ]
            }

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=lambda _request: _TokenHeavyAgent(),
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
        token_budget_default=32000,
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    assert run.status == AgentRunStatus.TERMINATED_BY_GUARDRAIL
    assert run.terminated_by == "token_budget"


async def test_agentic_final_tool_calls_defensive_max_steps():
    """最终消息仍含 tool_calls 且无正文 → 防御 max_steps（覆盖 384）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _LoopingAgent:
        async def invoke(self, messages, config=None):
            return {
                "messages": [
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "name": "search_characters",
                                "args": {"project_id": str(PROJECT_ID)},
                            }
                        ],
                    },
                    {"type": "tool", "name": "search_characters", "content": '{"ok": true}'},
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c2",
                                "name": "search_characters",
                                "args": {"project_id": str(PROJECT_ID)},
                            }
                        ],
                    },
                ]
            }

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=lambda _request: _LoopingAgent(),
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
        max_steps_default=12,  # 未超 max_steps（2 步 < 12）
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    # 最终含 tool_calls 无正文 → 防御分支 max_steps
    assert run.status == AgentRunStatus.TERMINATED_BY_GUARDRAIL
    assert run.terminated_by == "max_steps"


# ── 第三轮缺口补测（line 98.46% → 98.5% 门禁） ────────────────────


async def test_draft_confirm_update_status_none_race():
    """confirm 的 update_status 返回 None（确认前被删）→ DraftNotFoundError（覆盖 166）。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftNotFoundError, DraftService

    repo = AsyncMock()
    repo.get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    repo.update_status.return_value = None  # 竞态：确认前被并发删除
    svc = DraftService(draft_repo=repo, audit_service=None)
    with pytest.raises(DraftNotFoundError):
        await svc.confirm(DRAFT_ID)


async def test_draft_reject_state_error():
    """reject 状态非 DRAFT → DraftStateError（覆盖 194-195）。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftService, DraftStateError

    repo = AsyncMock()
    repo.get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.CONFIRMED,
        created_at=_utcnow(),
        confirmed_at=_utcnow(),
    )
    svc = DraftService(draft_repo=repo)
    with pytest.raises(DraftStateError, match="草稿已确认"):
        await svc.reject(DRAFT_ID)


async def test_draft_reject_update_status_none_race():
    """reject 的 update_status 返回 None（拒绝前被删）→ DraftNotFoundError（覆盖 201）。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftNotFoundError, DraftService

    repo = AsyncMock()
    repo.get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    repo.update_status.return_value = None
    svc = DraftService(draft_repo=repo, audit_service=None)
    with pytest.raises(DraftNotFoundError):
        await svc.reject(DRAFT_ID)


def test_build_writer_agent_system_prompt_fallback():
    """render 结果无 messages → 回退 template.system_prompt（覆盖 agentic_writer.py:53）。"""
    from inkflow.infrastructure.agent.agentic_writer import (
        build_writer_agent_system_prompt,
    )

    pm = MagicMock()
    template = MagicMock()
    template.system_prompt = "模板兜底 prompt"
    pm.load.return_value = template
    rendered = MagicMock()
    rendered.messages = []
    pm.render.return_value = rendered
    result = build_writer_agent_system_prompt(pm)
    assert result == "模板兜底 prompt"


async def test_agentic_final_content_with_tool_history():
    """自然终止 + 历史含 tool 消息 → _final_content 遍历跳过非 ai 消息（覆盖 261->260）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _ToolThenContentAgent:
        async def invoke(self, messages, config=None):
            return {
                "messages": [
                    {
                        "type": "ai",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "name": "search_characters",
                                "args": {"project_id": str(PROJECT_ID)},
                            }
                        ],
                    },
                    {"type": "tool", "name": "search_characters", "content": '{"ok": true}'},
                    {"type": "ai", "content": "最终正文。", "response_metadata": {"model": "m"}},
                ]
            }

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=lambda _request: _ToolThenContentAgent(),
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
    )
    run = await svc.run(
        AgenticWriteRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            outline="大纲",
        )
    )
    assert run.status == AgentRunStatus.COMPLETED
    assert run.final_content == "最终正文。"
