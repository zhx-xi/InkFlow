"""F27 草稿领域模型 — Agentic 写作闭环的产物保存区（Draft）.

Draft 是 agent 写作的草稿记录（spec §5.3 ADR-D 兜底）:
- 服务层在 run 自然终止且未调用 save_draft 时兜底创建（auto_saved）;
- status 状态机: draft（待确认）→ confirmed / rejected;
- confirmed_at 在确认时回填（UTC）.

依据: specs/f27-writer-agent/spec.md（父侧契约 test_draft_repo.py docstring 同源）。
领域层保持纯净：仅依赖 Pydantic v2 与标准库，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class DraftStatus(StrEnum):
    """草稿状态机（spec §5.3）.

    Attributes:
        DRAFT: 待确认（初始态）.
        CONFIRMED: 已确认（写入章节）.
        REJECTED: 已拒绝（保留记录，供 F28 分析）.
    """

    DRAFT = "draft"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class Draft(BaseModel):
    """一份草稿记录（Agent 写作产物保存区）.

    Attributes:
        id: 草稿 UUID 字符串（uuid4）.
        project_id: 所属项目 UUID.
        chapter_id: 目标章节 UUID（None = 确认时指定）.
        agent_run_id: 产生该草稿的 run id（兜底保存回填，可空）.
        content: 草稿正文.
        status: 草稿状态（默认 draft）.
        summary: 草稿摘要（默认空）.
        created_at: 创建时间（UTC）.
        confirmed_at: 确认时间（draft/rejected 为 None）.
    """

    model_config = {"from_attributes": True}

    id: str
    project_id: uuid.UUID
    chapter_id: uuid.UUID | None = None
    volume_id: uuid.UUID | None = None  # #976: 所属写作卷 UUID（None = 未归卷）
    agent_run_id: str | None = None
    content: str
    status: DraftStatus = DraftStatus.DRAFT
    summary: str = ""
    created_at: datetime
    confirmed_at: datetime | None = None
