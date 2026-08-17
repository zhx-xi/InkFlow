"""F45 M2 语义总结领域模型 — 一次 LLM 语义总结的产物（SemanticSummary/SummaryScope）.

依据: specs/f45-memory-evolution/spec.md §2.3。镜像 domain/models/user_preference.py
风格: 领域层保持纯净，仅依赖 Pydantic v2 与标准库，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class SummaryScope(StrEnum):
    """语义总结的归属范围（M2 两层归属落地）. """

    PROJECT = "project"  # 项目级风格偏好（称谓规则/结构习惯/文风）
    USER = "user"  # 用户级通用风格（句长/冗余/叙述对话比例）


class SemanticSummary(BaseModel):
    """一次 LLM 语义总结的产物（锚定 difflib 证据，不自由发挥）.

    Attributes:
        id: 总结 UUID 字符串（uuid4）.
        scope: 归属范围（project/user）.
        project_id: scope=project 时的项目 UUID；scope=user 时为 None.
        content: 抽象风格指令文本（LLM 产出，如「叙述偏好：用角色全名而非代词」）.
        anchor_hash: 锚点集合哈希（difflib 证据指纹——锚点未变化时复用总结，
            锚点变化触发重新总结，防陈旧）.
        anchor_count: 锚点数（证据量，可解释性）.
        model: 生成模型（config.llm_default_model 读取，不硬编码）.
        created_at: 创建时间（UTC）.
        updated_at: 最后更新时间（UTC）.
    """

    model_config = {"from_attributes": True}

    id: str
    scope: SummaryScope
    project_id: uuid.UUID | None = None
    content: str
    anchor_hash: str
    anchor_count: int
    model: str
    created_at: datetime
    updated_at: datetime
