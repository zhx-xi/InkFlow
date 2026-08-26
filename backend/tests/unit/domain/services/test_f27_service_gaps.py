"""F27 覆盖率缺口补测 A — DraftService/AuditLogService/AgenticWriterService 边界分支.

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


def _draft(**overrides) -> dict:
    d = {
        "id": DRAFT_ID,
        "project_id": PROJECT_ID,
        "chapter_id": CHAPTER_ID,
        "content": "草稿正文。",
        "status": "draft",
        "summary": "测试",
        "created_at": _utcnow(),
        "confirmed_at": None,
    }
    d.update(overrides)
    return d


# ── DraftService 全流程（mock 依赖） ────────────────────────────────


def _make_draft_service(**overrides):
    from inkflow.domain.services.draft_service import DraftService

    repo = AsyncMock()
    chapter = AsyncMock()
    audit = AsyncMock()
    svc = DraftService(draft_repo=repo, chapter_service=chapter, audit_service=audit, **overrides)
    return svc, {"repo": repo, "chapter": chapter, "audit": audit}


async def test_draft_create_empty_content_rejected():
    """create 空 content → ValueError（service 层校验，ADR-F 约束①）。"""
    svc, _ = _make_draft_service()
    with pytest.raises(ValueError, match="不能为空"):
        await svc.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content="   ")


async def test_draft_create_success_with_audit():
    """create 成功 → repo.create 一次 + audit draft_saved。"""
    from inkflow.domain.models.draft import Draft, DraftStatus

    svc, deps = _make_draft_service()
    deps["repo"].create.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="草稿正文。",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    draft = await svc.create(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content="草稿正文。")
    assert draft.id == DRAFT_ID
    deps["repo"].create.assert_awaited_once()
    deps["audit"].record.assert_awaited_once()
    assert "draft_saved" in str(deps["audit"].record.await_args)


async def test_draft_confirm_not_found():
    """confirm 草稿不存在 → DraftNotFoundError。"""
    from inkflow.domain.services.draft_service import DraftNotFoundError

    svc, deps = _make_draft_service()
    deps["repo"].get.return_value = None
    with pytest.raises(DraftNotFoundError):
        await svc.confirm(DRAFT_ID)


async def test_draft_confirm_state_error():
    """confirm 状态非 draft → DraftStateError（重复确认 409 语义）。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftStateError

    svc, deps = _make_draft_service()
    deps["repo"].get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.CONFIRMED,
        created_at=_utcnow(),
        confirmed_at=_utcnow(),
    )
    with pytest.raises(DraftStateError):
        await svc.confirm(DRAFT_ID)


async def test_draft_confirm_no_target_chapter():
    """confirm 无目标章节（draft 与参数均无）→ DraftStateError。"""
    from inkflow.domain.models.draft import Draft, DraftStatus
    from inkflow.domain.services.draft_service import DraftStateError

    svc, deps = _make_draft_service()
    deps["repo"].get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=None,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    with pytest.raises(DraftStateError):
        await svc.confirm(DRAFT_ID)


async def test_draft_confirm_success():
    """confirm 成功 → chapter_service.update_chapter + CONFIRMED + audit。"""
    from inkflow.domain.models.chapter import ChapterStatus
    from inkflow.domain.models.draft import Draft, DraftStatus

    svc, deps = _make_draft_service()
    deps["repo"].get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="确认正文。",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    deps["repo"].update_status.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="确认正文。",
        status=DraftStatus.CONFIRMED,
        created_at=_utcnow(),
        confirmed_at=_utcnow(),
    )
    confirmed = await svc.confirm(DRAFT_ID)
    assert confirmed.status == DraftStatus.CONFIRMED
    # 经 chapter_service.update_chapter（内容 + status=FINAL，service 层不碰 ORM）
    deps["chapter"].update_chapter.assert_awaited_once()
    dto = deps["chapter"].update_chapter.await_args.args[1]
    assert dto.content == "确认正文。"
    assert dto.status == ChapterStatus.FINAL
    deps["repo"].update_status.assert_awaited_once()
    deps["audit"].record.assert_awaited_once()
    assert "draft_confirmed" in str(deps["audit"].record.await_args)


async def test_draft_reject_success():
    """reject 成功 → REJECTED + audit draft_rejected。"""
    from inkflow.domain.models.draft import Draft, DraftStatus

    svc, deps = _make_draft_service()
    deps["repo"].get.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
    )
    deps["repo"].update_status.return_value = Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content="x",
        status=DraftStatus.REJECTED,
        created_at=_utcnow(),
    )
    rejected = await svc.reject(DRAFT_ID)
    assert rejected.status == DraftStatus.REJECTED
    deps["audit"].record.assert_awaited_once()
    assert "draft_rejected" in str(deps["audit"].record.await_args)


async def test_draft_reject_not_found():
    """reject 草稿不存在 → DraftNotFoundError。"""
    from inkflow.domain.services.draft_service import DraftNotFoundError

    svc, deps = _make_draft_service()
    deps["repo"].get.return_value = None
    with pytest.raises(DraftNotFoundError):
        await svc.reject(DRAFT_ID)


# ── AuditLogService ─────────────────────────────────────────────────


async def test_audit_log_record_success():
    """record 成功 → repo.add 收到构造好的 AuditLog（actor 拼 summary 前缀）。"""
    from inkflow.domain.services.audit_log_service import AuditLogService

    repo = AsyncMock()
    svc = AuditLogService(repo)
    await svc.record(
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        severity_summary="draft_saved",
        summary="草稿保存 10 字",
        degraded=True,
        actor="agent:writer",
    )
    repo.add.assert_awaited_once()
    added = repo.add.await_args.args[0]
    assert added.project_id == PROJECT_ID
    assert added.chapter_id == CHAPTER_ID
    assert added.severity_summary == "draft_saved"
    assert "[agent:writer]" in added.summary
    assert added.degraded is True


async def test_audit_log_record_silent_on_error():
    """repo.add 抛错 → 返回 None 不抛出（记录失败不影响主流程）。"""
    from inkflow.domain.services.audit_log_service import AuditLogService

    repo = AsyncMock()
    repo.add.side_effect = RuntimeError("db down")
    svc = AuditLogService(repo)
    result = await svc.record(project_id=PROJECT_ID, severity_summary="x")
    assert result is None


# ── agentic_writer_service 异常分支 + BaseMessage 双形态 ────────────


async def test_agentic_invoke_error_failed():
    """agent.invoke 抛错 → status=FAILED + save 被调 + 不抛出（ADR-D 防御）。"""
    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    async def _boom(messages, config=None):
        raise RuntimeError("provider timeout")

    agent = MagicMock()
    agent.invoke = _boom
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
        )
    )
    assert run.status == AgentRunStatus.FAILED
    deps["run_repo"].save.assert_awaited()
    deps["audit_service"].record.assert_awaited()
    assert "run_failed" in str(deps["audit_service"].record.await_args)


async def test_agentic_base_message_object_form():
    """BaseMessage 对象形态（非 dict）的消息历史也能映射 steps（_msg_type/_tool_calls 双形态）。"""
    from langchain_core.messages import AIMessage, ToolMessage

    from inkflow.domain.models.agent_run import AgentRunStatus
    from inkflow.domain.services.agentic_writer_service import (
        AgenticWriteRequest,
        AgenticWriterService,
    )

    class _ObjAgent:
        """invoke 返回 langchain BaseMessage 对象列表（真实 deepagents 形态）。"""

        async def invoke(self, messages, config=None):
            return {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call_1",
                                "name": "search_characters",
                                "args": {"project_id": str(PROJECT_ID)},
                            }
                        ],
                        response_metadata={"usage": {"total_tokens": 120}},
                    ),
                    ToolMessage(
                        content='{"ok": true, "data": ["角色A"]}',
                        name="search_characters",
                        tool_call_id="call_1",
                    ),
                    AIMessage(
                        content="最终正文。",
                        response_metadata={"usage": {"total_tokens": 300}},
                    ),
                ]
            }

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=lambda _request: _ObjAgent(),
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
    assert run.terminated_by == "llm"
    assert run.final_content == "最终正文。"
    # 工具调用 result 从 ToolMessage 回填（对象形态）
    tool_names = [tc.tool_name for step in run.steps for tc in step.tool_calls]
    assert "search_characters" in tool_names
    results = [tc.result for step in run.steps for tc in step.tool_calls]
    assert any("角色A" in r for r in results)
    assert run.token_usage_total == 420  # 120 + 300（对象形态 usage 提取）


async def test_final_content_empty_history() -> None:
    """#275 覆盖率补测: _final_content 对无 AI 消息的历史返回空串（L265 分支）."""
    from inkflow.domain.services.agentic_writer_service import AgenticWriterService

    deps = {
        "draft_service": AsyncMock(),
        "audit_service": AsyncMock(),
        "run_repo": AsyncMock(),
    }
    svc = AgenticWriterService(
        agent_factory=lambda _request: AsyncMock(),
        draft_service=deps["draft_service"],
        audit_service=deps["audit_service"],
        run_repo=deps["run_repo"],
    )

    result = svc._final_content(
        [{"type": "tool", "name": "search_characters", "content": '{"ok": true}'}]
    )

    assert result == ""
