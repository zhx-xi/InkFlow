"""上下文管理领域模型 — 分层 Token 预算、数据源类型、组装结果.

ContextLayer 定义三层上下文策略（protected / compressible / dynamic），
ContextSourceType 枚举七种数据源（F28 追加 preference），
ContextItem/ContextBlock/DroppedItem 为组装过程的
中间数据结构，ContextRequest 为 API 输入，ContextAssemblyResult 为最终产出。

依据: specs/f6-context/spec.md §3, ADR-010.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ContextLayer(StrEnum):
    """上下文分层 — 决定注入策略.

    - PROTECTED: 必须包含，不可压缩、不可裁剪
    - COMPRESSIBLE: 可摘要压缩，压缩后仍超预算才裁剪
    - DYNAMIC: 按预算择优选择，放不下直接裁剪
    """

    PROTECTED = "protected"
    COMPRESSIBLE = "compressible"
    DYNAMIC = "dynamic"


class ContextSourceType(StrEnum):
    """上下文数据源类型枚举.

    ┌─────────────────────────┬───────────────┬──────────────────────────┐
    │ 值                      │ 层            │ Phase 1 数据来源          │
    ├─────────────────────────┼───────────────┼──────────────────────────┤
    │ writing_requirements    │ protected     │ F3 调用时必传入参          │
    │ outline                 │ protected     │ project.config.extra      │
    │ character_setting       │ compressible  │ 空实现 (F8 Phase 2)       │
    │ world_setting           │ compressible  │ 空实现 (F9 Phase 2)       │
    │ chapter_summary         │ dynamic       │ LLM 生成 + 缓存表 (本模块) │
    │ foreshadowing           │ dynamic       │ 空实现 (F14 Phase 2)      │
    │ preference              │ protected     │ F28 已学偏好（memory_learning） │
    └─────────────────────────┴───────────────┴──────────────────────────┘
    """

    WRITING_REQUIREMENTS = "writing_requirements"
    OUTLINE = "outline"
    CHARACTER_SETTING = "character_setting"
    WORLD_SETTING = "world_setting"
    CHAPTER_SUMMARY = "chapter_summary"
    FORESHADOWING = "foreshadowing"
    PREFERENCE = "preference"


# ── 层级映射 ────────────────────────────────────────────────────────
SOURCE_LAYER: dict[ContextSourceType, ContextLayer] = {
    ContextSourceType.WRITING_REQUIREMENTS: ContextLayer.PROTECTED,
    ContextSourceType.OUTLINE: ContextLayer.PROTECTED,
    ContextSourceType.CHARACTER_SETTING: ContextLayer.COMPRESSIBLE,
    ContextSourceType.WORLD_SETTING: ContextLayer.COMPRESSIBLE,
    ContextSourceType.CHAPTER_SUMMARY: ContextLayer.DYNAMIC,
    ContextSourceType.FORESHADOWING: ContextLayer.DYNAMIC,
    ContextSourceType.PREFERENCE: ContextLayer.PROTECTED,
}


@dataclass
class ContextItem:
    """单一上下文条目 — 由数据源产出.

    Attributes:
        source: 来源类型.
        title: 注入时的分段标题，如「角色：林晚」「第 3 章摘要」.
        content: 内容文本.
        priority: 同层内优先级（大者先注入），默认 0.
        metadata: 扩展元数据，如 chapter_id / chapter_index / location.
    """

    source: ContextSourceType
    title: str
    content: str
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextBlock:
    """注入块 — 预算分配后的产物.

    Attributes:
        item: 原始上下文条目.
        layer: 所属层.
        token_count: 该 block 占用的 Token 数.
        compressed: 是否已被摘要压缩.
    """

    item: ContextItem
    layer: ContextLayer
    token_count: int
    compressed: bool = False


@dataclass
class DroppedItem:
    """被裁剪的条目及原因.

    Attributes:
        item: 原始条目.
        reason: over_budget / compression_insufficient / layer_cap / summary_failed.
    """

    item: ContextItem
    reason: str


@dataclass
class ChapterSummary:
    """前文摘要缓存 — 映射到 chapter_summaries 表.

    失效规则: chapter.updated_at > summary.updated_at 时缓存过期.
    """

    id: uuid.UUID
    chapter_id: uuid.UUID
    summary: str
    model: str
    created_at: str  # ISO 8601 UTC
    updated_at: str  # ISO 8601 UTC


class TokenBudgetConfig(BaseModel):
    """分层预算配置 — 存储在 project.config.extra["context"] 中.

    Attributes:
        max_ratio: 预算上限 = 模型窗口 × max_ratio (PRD: ≤ 80%).
        layer_ratio: 各层 cap 占比（需 ≤ 1.0，否则自动归一化）.
        summary_model: 摘要专用模型 (None = 用请求的 model).
        summary_max_chapters: dynamic 层最多注入的摘要数.
        compress_target_ratio: 压缩目标比例（压缩后 ≤ 原文 token × ratio）.
    """

    max_ratio: float = Field(default=0.8, ge=0.1, le=1.0)
    layer_ratio: dict[ContextLayer, float] = Field(
        default_factory=lambda: {
            ContextLayer.PROTECTED: 0.30,
            ContextLayer.COMPRESSIBLE: 0.40,
            ContextLayer.DYNAMIC: 0.30,
        }
    )
    summary_model: str | None = None
    summary_max_chapters: int = Field(default=10, ge=1, le=100)
    compress_target_ratio: float = Field(default=0.5, ge=0.1, le=1.0)

    @field_validator("layer_ratio")
    @classmethod
    def _normalize_layer_ratio(cls, v: dict[ContextLayer, float]) -> dict[ContextLayer, float]:
        total = sum(v.values())
        if total > 1.0:
            return {k: val / total for k, val in v.items()}
        return v


class ContextOverride(BaseModel):
    """上下文注入的显式勾选通道（v1.1 #593）.

    - character_ids 非空 → 只注入 metadata.character_id 命中的角色 item；空 → 注入全部
    - foreshadowing_ids 非空 → 只注入 metadata.foreshadowing_id 命中的伏笔 item；空 → 注入全部
    - world_ids 非空 → 只注入 metadata.world_setting_id 命中的世界观 item；空 → 注入全部
    - 只过滤 character_setting / foreshadowing / world_setting 三类来源，不影响 outline/summary 等
    """

    character_ids: list[uuid.UUID] = Field(default_factory=list)
    foreshadowing_ids: list[uuid.UUID] = Field(default_factory=list)
    world_ids: list[uuid.UUID] = Field(default_factory=list)


class ContextRequest(BaseModel):
    """上下文组装请求 — API 输入 / F3 调用参数.

    Attributes:
        project_id: 项目 ID.
        chapter_id: 目标章节 ID（正在写作的章节）.
        model: 目标模型名（provider/model_name 格式）.
        writing_requirements: 必填，写作要求 / 任务指令.
        max_tokens: 覆盖预算；None = 模型窗口 × max_ratio.
        override: 显式勾选通道（v1.1 #593）；None = 全部注入（默认行为）.
    """

    project_id: uuid.UUID
    chapter_id: uuid.UUID | None = None
    model: str
    writing_requirements: str = Field(..., min_length=1)
    max_tokens: int | None = None
    override: ContextOverride | None = None


class ContextAssemblyResult(BaseModel):
    """上下文组装结果 — F3 据此渲染最终 Prompt.

    Attributes:
        blocks: 按 protected → compressible → dynamic 有序排列.
        budget_tokens: 总预算 Token 数.
        total_tokens: 实际占用 Token 数.
        model: 目标模型.
        dropped: 被裁剪的条目清单位置.
    """

    blocks: list[ContextBlock]
    budget_tokens: int
    total_tokens: int
    model: str
    dropped: list[DroppedItem]
