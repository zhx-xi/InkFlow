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


# ── #976: confirm 自动建章（chapter_creator / outline_bindder 注入） ──────────


def _make_draft_976(
    *,
    chapter_id=None,
    summary="测试",
    content="草稿正文。",
    volume_id=None,
    status="draft",
    confirmed_at=None,
):
    """构造带 volume_id 的 Draft（#976 卷绑定草稿）.

    当前 Draft 无 volume_id 字段（extra=ignore 静默丢弃），GREEN 后透传。
    """
    from inkflow.domain.models.draft import Draft, DraftStatus

    return Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=chapter_id,
        content=content,
        status=DraftStatus(status),
        summary=summary,
        created_at=_utcnow(),
        confirmed_at=confirmed_at,
        volume_id=volume_id,
    )


def _make_chapter_creator_976(*, new_id=uuid.UUID(int=42), volume_id=None):
    """构造 chapter_creator mock（create_chapter 返回 Chapter 域对象，鸭子签名）."""
    from inkflow.domain.models.chapter import Chapter, ChapterStatus

    creator = AsyncMock()
    creator.create_chapter.return_value = Chapter(
        id=new_id,
        project_id=PROJECT_ID,
        volume_id=volume_id,
        title="自动建章",
        content="",
        status=ChapterStatus.DRAFT,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    return creator


async def test_draft_confirm_auto_create_chapter():
    """【R】confirm 无目标 + chapter_creator 注入 → create_chapter + update_chapter(FINAL) +
    repo.update_chapter_binding。"""
    from inkflow.domain.models.chapter import ChapterStatus
    from inkflow.domain.models.draft import DraftStatus

    summary = "这是草稿摘要标题"  # 8 字
    vol_id = uuid.UUID(int=5)
    creator = _make_chapter_creator_976(volume_id=vol_id)
    binder = AsyncMock()
    svc, deps = _make_draft_service(chapter_creator=creator, outline_bindder=binder)
    deps["repo"].get.return_value = _make_draft_976(
        chapter_id=None, summary=summary, volume_id=vol_id
    )
    deps["repo"].update_status.return_value = _make_draft_976(
        chapter_id=uuid.UUID(int=42), summary=summary, status="confirmed", confirmed_at=_utcnow()
    )

    confirmed = await svc.confirm(DRAFT_ID)

    assert confirmed.status == DraftStatus.CONFIRMED
    # chapter_creator.create_chapter(project_id, title, volume_id, content)
    call = creator.create_chapter.await_args
    assert call.args[0] == PROJECT_ID
    assert call.args[1] == summary  # 标题 = summary[:30]（8 字未截断）
    assert call.kwargs["volume_id"] == vol_id  # 草稿 volume_id 透传
    assert call.kwargs["content"] == ""
    # chapter_service.update_chapter(target, ChapterUpdate(content, FINAL))
    deps["chapter"].update_chapter.assert_awaited_once()
    dto = deps["chapter"].update_chapter.await_args.args[1]
    assert dto.status == ChapterStatus.FINAL
    # repo.update_chapter_binding(draft_id, new_chapter_id)
    deps["repo"].update_chapter_binding.assert_awaited_once_with(DRAFT_ID, uuid.UUID(int=42))


async def test_draft_confirm_auto_create_title_from_content_when_summary_empty():
    """【R】summary 空串 → create_chapter 标题取 content.strip()[:30]."""
    content = "  第一章草稿正文内容。够长足够验证标题。  "
    creator = _make_chapter_creator_976()
    svc, deps = _make_draft_service(chapter_creator=creator, outline_bindder=AsyncMock())
    deps["repo"].get.return_value = _make_draft_976(
        chapter_id=None, summary="", content=content
    )
    deps["repo"].update_status.return_value = _make_draft_976(
        status="confirmed", confirmed_at=_utcnow()
    )

    await svc.confirm(DRAFT_ID)

    assert creator.create_chapter.await_args.args[1] == content.strip()[:30]


async def test_draft_confirm_auto_create_title_truncated_to_30():
    """【R】超长 summary（40 字）→ create_chapter 标题 == 前 30 字符."""
    long_summary = "超" * 40
    creator = _make_chapter_creator_976()
    svc, deps = _make_draft_service(chapter_creator=creator, outline_bindder=AsyncMock())
    deps["repo"].get.return_value = _make_draft_976(
        chapter_id=None, summary=long_summary
    )
    deps["repo"].update_status.return_value = _make_draft_976(
        status="confirmed", confirmed_at=_utcnow()
    )

    await svc.confirm(DRAFT_ID)

    assert creator.create_chapter.await_args.args[1] == long_summary[:30]


async def test_draft_confirm_auto_create_explicit_title_precedence():
    """【R】显式 title 参数优先于 summary 派生 → create_chapter 标题 == 自定义."""
    creator = _make_chapter_creator_976()
    svc, deps = _make_draft_service(chapter_creator=creator, outline_bindder=AsyncMock())
    deps["repo"].get.return_value = _make_draft_976(chapter_id=None, summary="摘要")
    deps["repo"].update_status.return_value = _make_draft_976(
        status="confirmed", confirmed_at=_utcnow()
    )

    await svc.confirm(DRAFT_ID, title="自定义标题")

    assert creator.create_chapter.await_args.args[1] == "自定义标题"


async def test_draft_confirm_auto_create_outline_bindder_called():
    """【R】source_outline_id 传值 → outline_bindder await 一次
    （str(outline_id), str(new_chapter_id)）。"""
    outline_id = uuid.UUID(int=51)
    binder = AsyncMock()
    creator = _make_chapter_creator_976()
    svc, deps = _make_draft_service(chapter_creator=creator, outline_bindder=binder)
    deps["repo"].get.return_value = _make_draft_976(chapter_id=None, summary="摘要")
    deps["repo"].update_status.return_value = _make_draft_976(
        status="confirmed", confirmed_at=_utcnow()
    )

    await svc.confirm(DRAFT_ID, source_outline_id=outline_id)

    binder.assert_awaited_once()
    assert binder.await_args.args == (str(outline_id), str(uuid.UUID(int=42)))


async def test_draft_confirm_no_target_no_creator_raises():
    """【G】chapter_creator 未注入（默认）且无目标 → 旧 DraftStateError（409 兼容）."""
    from inkflow.domain.services.draft_service import DraftStateError

    svc, deps = _make_draft_service()  # 不注入 chapter_creator
    deps["repo"].get.return_value = _make_draft_976(chapter_id=None)

    with pytest.raises(DraftStateError):
        await svc.confirm(DRAFT_ID)


async def test_draft_confirm_bound_chapter_does_not_auto_create():
    """【G】草稿带 volume_id 且 target 已有 chapter_id（绑定章）→ 正常 update_chapter，不建章.

    当前 Draft 无 volume_id（extra=ignore 静默丢弃），构造传 volume_id 不报错（实测）。
    因 chapter_creator 注入现 TypeError（RED 侧），本守护用例不注入 creator，锚定「绑定章
    → update_chapter 路径」而非自动建章路径（_make_draft_service 已注入默认 chapter_service）。
    """
    from inkflow.domain.models.chapter import ChapterStatus

    svc, deps = _make_draft_service()
    deps["repo"].get.return_value = _make_draft_976(
        chapter_id=CHAPTER_ID, volume_id=uuid.UUID(int=5)
    )
    deps["repo"].update_status.return_value = _make_draft_976(
        chapter_id=CHAPTER_ID, status="confirmed", confirmed_at=_utcnow()
    )

    confirmed = await svc.confirm(DRAFT_ID)

    assert confirmed.chapter_id == CHAPTER_ID
    deps["chapter"].update_chapter.assert_awaited_once()
    dto = deps["chapter"].update_chapter.await_args.args[1]
    assert dto.status == ChapterStatus.FINAL
