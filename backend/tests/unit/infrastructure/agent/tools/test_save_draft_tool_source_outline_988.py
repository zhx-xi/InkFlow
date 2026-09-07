"""#988 创建点契约 — chat 轨 save_draft 工具无 outline 上下文 → 透传 null（跳点实证）.

实证分类（PR 描述引用）: SaveDraftToolDeps 装配期仅 expected_project_id/
expected_chapter_id（真实章 UUID，非大纲节点 id）+ volume_lookup，无 outline 来源
→ 工具路径 GREEN 必保持 source_outline_id=None 透传（不崩工具路径），由确认面
fallback 兜底。本文件锁该语义：工具 create kwargs 恒含 source_outline_id 键且为
None（当前 DraftService.create 无该形参但工具不传该键 → KeyError RED）。

镜像 test_draft_volume_976.py save_draft 工具契约形态（AsyncMock draft_service
+ tool.func 直调）。
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

pytestmark = pytest.mark.asyncio

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
CONTENT = "chat 轨草稿正文。这是用于验证 save_draft 工具 source_outline_id 契约的正文。"


def _make_draft(**overrides) -> Draft:
    kwargs: dict = dict(
        id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content=CONTENT,
        status=DraftStatus.DRAFT,
        created_at=datetime.now(UTC),
        confirmed_at=None,
    )
    kwargs.update(overrides)
    return Draft(**kwargs)


async def test_save_draft_tool_passes_none_source_outline_id():
    """【R】工具路径 create kwargs 恒含 source_outline_id 键且为 None.

    GREEN: DraftService.create 新增 source_outline_id 形参默认 None；工具不传该
    kwarg → repo 收到默认 None。当前 create 无该形参但服务签名未暴露键 →
    draft_service.create.await_args.kwargs["source_outline_id"] KeyError（RED）。
    """
    deps = SaveDraftToolDeps(
        draft_service=AsyncMock(),
        audit_service=AsyncMock(),
        expected_project_id=PROJECT_ID,
        expected_chapter_id=CHAPTER_ID,
    )
    deps.draft_service.create.return_value = _make_draft()
    tool = build_save_draft_tool(deps)

    await tool.func(content=CONTENT)

    assert deps.draft_service.create.await_args is not None
    # chat 轨工具无 outline 来源 → 保持 None（跳点实证：不崩路径，确认面 fallback 兜底）
    assert deps.draft_service.create.await_args.kwargs.get("source_outline_id", "MISSING") is None


async def test_save_draft_tool_explicit_none_volume_lookup_still_none():
    """【G】volume_lookup=None 既有路径零回归（source_outline_id 仍 None）.

    当前即成立（工具不传 outline）；RED 期 PASS 刻意，守护 GREEN 不越界注入臆造来源。
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

    kwargs = deps.draft_service.create.await_args.kwargs
    assert kwargs["volume_id"] is None
    assert kwargs.get("source_outline_id") is None or "source_outline_id" not in kwargs
