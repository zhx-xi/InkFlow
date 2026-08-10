"""F28 DraftService.update 契约测试 — 编辑草稿正文（spec §3 PATCH drafts 服务层）.

F28 新增方法 update（接线 F27 未接线的 draft_repo.update_content + memory_service
事件捕获 + last_learned 传递）。RED 批遗漏本文件（F27 无 test_draft_service.py），
QA 阶段补建（2026-08-11）——TDD 铁律：新方法必须有 unit 级契约，API mock 不算。

设计假设（父侧定稿契约，GREEN 按此实现）:
    class DraftService:
        def __init__(self, *, draft_repo, chapter_service=None, audit_service=None,
                     memory_service=None) -> None:  # memory_service F28 可选注入
            self.last_learned: bool = False

        async def update(self, draft_id: str, content: str) -> Draft:
            # content strip 空 → ValueError("草稿内容不能为空")
            # repo.get 不存在 → DraftNotFoundError("草稿不存在")
            # status != DRAFT → DraftStateError（"草稿已确认"/"草稿已拒绝"）
            # repo.update_content(draft_id, content) → None → DraftNotFoundError（竞态）
            # memory_service 注入时:
            #   await memory_service.record_draft_edit(draft_id=..., project_id=...,
            #     chapter_id=..., before=旧 content, after=新 content, agent_run_id=...)
            #   self.last_learned = bool(getattr(memory_service, "last_learned", False))
            # 返回更新后的 Draft

RED 预期: 全部用例 FAILED（DraftService.update 方法不存在 → AttributeError）——
本文件为 QA 补建，落盘时 update 已由 GREEN 实现，用例应直接通过（补测形态）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.domain.services.draft_service import (
    DraftNotFoundError,
    DraftService,
    DraftStateError,
)

pytestmark = pytest.mark.asyncio

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
DRAFT_ID = "draft-0001"


def _draft(*, content="旧版内容", status=DraftStatus.DRAFT, agent_run_id="run-1") -> Draft:
    """构造 Draft 领域实例."""
    return Draft(
        id=DRAFT_ID,
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        agent_run_id=agent_run_id,
        content=content,
        status=status,
        summary="",
        created_at=datetime(2026, 8, 11, tzinfo=UTC),
        confirmed_at=None,
    )


def _make_service(memory_service=None) -> tuple[DraftService, dict]:
    """构造服务 + 依赖字典；repo 全显式默认值（裸 AsyncMock 陷阱防护，规则 1m）."""
    deps = {
        "draft_repo": AsyncMock(),
        "chapter_service": AsyncMock(),
        "audit_service": AsyncMock(),
    }
    deps["draft_repo"].get.return_value = _draft()
    deps["draft_repo"].update_content.return_value = _draft(content="新版内容更长")
    service = DraftService(
        draft_repo=deps["draft_repo"],
        chapter_service=deps["chapter_service"],
        audit_service=deps["audit_service"],
        memory_service=memory_service,
    )
    return service, deps


def _arg(call, name: str, pos: int | None = None, default=None):
    """从 mock call 宽松取参（关键字优先，位置回退）——不锁传参形态."""
    if name in call.kwargs:
        return call.kwargs[name]
    if pos is not None and len(call.args) > pos:
        return call.args[pos]
    return default


# ── 契约 1: update 成功路径 ──


async def test_update_success_persists_content() -> None:
    """update 成功: 先 get 校验 → update_content 落库 → 返回更新后 Draft."""
    service, deps = _make_service()
    result = await service.update(DRAFT_ID, "新版内容更长")
    deps["draft_repo"].get.assert_awaited_once_with(DRAFT_ID)
    deps["draft_repo"].update_content.assert_awaited_once()
    call = deps["draft_repo"].update_content.await_args
    assert _arg(call, "draft_id", 0) == DRAFT_ID
    assert _arg(call, "content", 1) == "新版内容更长"
    assert result.content == "新版内容更长"


async def test_update_empty_content_raises() -> None:
    """update 空内容（strip 后为空）→ ValueError（镜像 create 语义）."""
    service, _ = _make_service()
    with pytest.raises(ValueError, match="草稿内容不能为空"):
        await service.update(DRAFT_ID, "   ")


# ── 契约 2: 错误面 ──


async def test_update_missing_draft_404() -> None:
    """update 草稿不存在 → DraftNotFoundError（404 映射）."""
    service, deps = _make_service()
    deps["draft_repo"].get.return_value = None
    with pytest.raises(DraftNotFoundError):
        await service.update(DRAFT_ID, "新版内容更长")
    deps["draft_repo"].update_content.assert_not_awaited()


async def test_update_confirmed_draft_409() -> None:
    """update 已确认草稿 → DraftStateError（"草稿已确认"）."""
    service, deps = _make_service()
    deps["draft_repo"].get.return_value = _draft(status=DraftStatus.CONFIRMED)
    with pytest.raises(DraftStateError, match="草稿已确认"):
        await service.update(DRAFT_ID, "新版内容更长")


async def test_update_rejected_draft_409() -> None:
    """update 已拒绝草稿 → DraftStateError（"草稿已拒绝"）."""
    service, deps = _make_service()
    deps["draft_repo"].get.return_value = _draft(status=DraftStatus.REJECTED)
    with pytest.raises(DraftStateError, match="草稿已拒绝"):
        await service.update(DRAFT_ID, "新版内容更长")


async def test_update_race_deleted_404() -> None:
    """update 竞态: get 通过但 update_content 返回 None → DraftNotFoundError."""
    service, deps = _make_service()
    deps["draft_repo"].update_content.return_value = None
    with pytest.raises(DraftNotFoundError):
        await service.update(DRAFT_ID, "新版内容更长")


# ── 契约 3: memory_service 事件捕获（F28 核心接线） ──


async def test_update_with_memory_service_captures_event() -> None:
    """注入 memory_service: update 后调用 record_draft_edit（before=旧内容 after=新内容）."""
    memory = MagicMock()
    memory.record_draft_edit = AsyncMock(return_value=SimpleNamespace(id="evt-1"))
    memory.last_learned = True
    service, _ = _make_service(memory_service=memory)
    await service.update(DRAFT_ID, "新版内容更长")
    memory.record_draft_edit.assert_awaited_once()
    call = memory.record_draft_edit.await_args
    assert _arg(call, "draft_id", 0) == DRAFT_ID
    assert _arg(call, "project_id", 1) == PROJECT_ID
    assert _arg(call, "before", 4) == "旧版内容"
    assert _arg(call, "after", 5) == "新版内容更长"
    assert _arg(call, "agent_run_id", 6) == "run-1"


async def test_update_learned_flag_propagates() -> None:
    """last_learned 传递: memory_service.last_learned=True → service.last_learned=True."""
    memory = MagicMock()
    memory.record_draft_edit = AsyncMock(return_value=SimpleNamespace(id="evt-1"))
    memory.last_learned = True
    service, _ = _make_service(memory_service=memory)
    await service.update(DRAFT_ID, "新版内容更长")
    assert service.last_learned is True


async def test_update_learned_flag_false_default() -> None:
    """last_learned 默认 False（memory_service 未注入时 update 不置位）."""
    service, _ = _make_service()
    await service.update(DRAFT_ID, "新版内容更长")
    assert service.last_learned is False
