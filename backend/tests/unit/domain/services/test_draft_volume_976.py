"""#976 草稿常显 — DraftService.create 卷绑定 + save_draft 工具 volume_lookup RED 契约测试.

被测模块（当前未实现，对照当前实现全部 RED）:
- DraftService.create 尚不接收 volume_id 形参（draft_service.py:67-75）→ TypeError（【R】）
- SaveDraftToolDeps 无 volume_lookup 字段（save_draft_tool.py:56-68 dataclass）→ TypeError（【R】）
- save_draft 工具 create 调用未透传 volume_id kwarg（save_draft_tool.py:114-120）→ KeyError（【R】）

GREEN 必实现（父侧定稿契约 §2.2/§2.4）:
- DraftService.create(*, project_id, chapter_id=None, content, summary="", agent_run_id=None,
  volume_id=None) —— 透传 volume_id 给 repo.create
- SaveDraftToolDeps 增 volume_lookup:
  Callable[[uuid.UUID, uuid.UUID|None], str|None] | None = None；
  工具内解析 vol = deps.volume_lookup(pid, chid) if deps.volume_lookup else None，
  uuid.UUID(vol) 容错传 create（volume_id=None 透传）。

asyncio 模式: pyproject asyncio_mode = "auto"；文件级 pytestmark 双保险。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.infrastructure.agent.tools.save_draft_tool import (
    SaveDraftToolDeps,
    build_save_draft_tool,
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
CONTENT = "第一章 测试内容。这是草稿正文，用于验证 save_draft 工具契约。"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_draft(**overrides) -> Draft:
    """构造领域 Draft（当前无 volume_id 字段，extra=ignore 静默丢弃；GREEN 后透传）。"""
    kwargs = dict(
        id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content=CONTENT,
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
        confirmed_at=None,
    )
    kwargs.update(overrides)
    return Draft(**kwargs)


# ── 契约: DraftService.create 卷绑定透传 ──


async def test_draft_service_create_passes_volume_id_to_repo():
    """【R】DraftService.create(volume_id=X) → repo.create 收到 volume_id=X kwarg.

    当前 create 无 volume_id 形参 → TypeError（RED）。
    """
    from inkflow.domain.services.draft_service import DraftService

    repo = AsyncMock()
    repo.create.return_value = _make_draft(volume_id=uuid.UUID(int=5))
    svc = DraftService(draft_repo=repo)

    await svc.create(
        project_id=PROJECT_ID,
        chapter_id=None,
        content=CONTENT,
        volume_id=uuid.UUID(int=5),
    )

    assert repo.create.await_args.kwargs["volume_id"] == uuid.UUID(int=5)


# ── 契约: save_draft 工具 volume_lookup 注入 ──


async def test_save_draft_tool_volume_lookup_injected_passes_to_create():
    """【R】deps.volume_lookup 注入返回 str(uuid.UUID(int=5)) → draft_service.create 收 volume_id.

    当前 SaveDraftToolDeps 无 volume_lookup 字段 → 构造 TypeError（RED）。
    """
    deps = SaveDraftToolDeps(
        draft_service=AsyncMock(),
        audit_service=AsyncMock(),
        expected_project_id=PROJECT_ID,
        expected_chapter_id=CHAPTER_ID,
        volume_lookup=AsyncMock(return_value=str(uuid.UUID(int=5))),
    )
    deps.draft_service.create.return_value = _make_draft(volume_id=uuid.UUID(int=5))
    tool = build_save_draft_tool(deps)

    await tool.func(content=CONTENT)

    assert deps.draft_service.create.await_args is not None  # create 已调用
    assert deps.draft_service.create.await_args.kwargs["volume_id"] == uuid.UUID(int=5)
    assert uuid.UUID(str(uuid.UUID(int=5))) == uuid.UUID(int=5)  # 锚：前端 Volume.id 形态


async def test_save_draft_tool_no_volume_lookup_passes_none():
    """【R】volume_lookup=None → draft_service.create 收到 volume_id is None.

    当前 deps 无 volume_lookup 字段 → 构造 TypeError（RED）。
    """
    deps = SaveDraftToolDeps(
        draft_service=AsyncMock(),
        audit_service=AsyncMock(),
        expected_project_id=PROJECT_ID,
        expected_chapter_id=CHAPTER_ID,
        volume_lookup=None,
    )
    deps.draft_service.create.return_value = _make_draft()
    tool = build_save_draft_tool(deps)

    await tool.func(content=CONTENT)

    assert deps.draft_service.create.await_args is not None
    assert deps.draft_service.create.await_args.kwargs["volume_id"] is None
