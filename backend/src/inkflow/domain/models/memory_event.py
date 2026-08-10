"""F28 diff 事件领域模型 — 用户修改/确认/重新生成行为的事件快照（MemoryEvent）.

MemoryEvent 是偏好学习闭环的事件源（spec §2.2，Q2 独立表）:
- 只从用户主动行为产生（编辑草稿/拒绝草稿/确认草稿）;
- draft_edited 携带 before/after 全文，供 difflib 规则化提取（spec §5.2）;
- draft_rejected/draft_confirmed 不参与提取，只贡献修改率统计（spec §5.7）;
- diff_chars = len(after) - len(before) 由仓储层计算（只读统计用，可负）.

依据: specs/f28-agent-memory/spec.md §2.2/§5.1/§5.2。
领域层保持纯净：仅依赖 Pydantic v2 与标准库，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class MemoryEventType(StrEnum):
    """学习事件类型——用户主动行为的分类.

    Attributes:
        DRAFT_EDITED: 用户确认前手动编辑草稿（before/after 均有值）.
        DRAFT_REJECTED: 用户拒绝草稿（重新生成信号，after 为空）.
        DRAFT_CONFIRMED: 用户直接确认草稿（未编辑，0 修改信号）.
    """

    DRAFT_EDITED = "draft_edited"
    DRAFT_REJECTED = "draft_rejected"
    DRAFT_CONFIRMED = "draft_confirmed"


class MemoryEvent(BaseModel):
    """一次用户修改/确认/重新生成行为的 diff 事件快照（Q2 独立表）.

    Attributes:
        id: 事件 UUID 字符串（uuid4）.
        project_id: 所属项目 UUID.
        draft_id: 关联草稿 id（可空）.
        chapter_id: 目标章节 UUID（可空）.
        agent_run_id: 来源 agent run id（可空）.
        event_type: 事件类型.
        before_content: 修改前内容（edited 必填；rejected/confirmed 可空）.
        after_content: 修改后内容（edited 必填；rejected 可空）.
        diff_chars: 修改量 = len(after) - len(before) 字符数差（可负，只读统计用）.
        created_at: 事件时间（UTC）.
    """

    model_config = {"from_attributes": True}

    id: str
    project_id: uuid.UUID
    draft_id: str | None = None
    chapter_id: uuid.UUID | None = None
    agent_run_id: str | None = None
    event_type: MemoryEventType
    before_content: str | None = None
    after_content: str | None = None
    diff_chars: int = 0
    created_at: datetime
