"""F28 项目偏好领域模型 — 偏好学习闭环的结构化产物（ProjectPreference）.

ProjectPreference 是用户修改行为的统计沉淀（spec §2.1，ADR-G 结构化偏好表）:
- 由 memory_service 在同类修改达到阈值（N≥2）时落库（学习）;
- category/pattern/value 三要素构成可解释的偏好描述（如 addressing +
  「她」→「林晚」的称呼替换）;
- count/confidence 记录支撑强度（confidence = 1 - 1/(count+1)，单调递增）;
- source_events 反查 memory_events 事件详情（可追溯）;
- 删除即停止注入（读路径实时查库无缓存，spec §5.3）.

依据: specs/f28-agent-memory/spec.md §2.1/§5.2/§5.3。
领域层保持纯净：仅依赖 Pydantic v2 与标准库，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class PreferenceCategory(StrEnum):
    """偏好分类维度（Q1 拍板：4 类起步，2026-08-11）.

    Attributes:
        ADDRESSING: 称呼习惯（主角/配角称谓、人称替换，如「她」→「林晚」）.
        STYLE_WORD: 风格用词（形容词/副词/固定表达替换，如「说」→「低声道」）.
        STRUCTURE: 结构偏好（段落/标题/列表组织模式）.
        OTHER: 其他（兜底）.
    """

    ADDRESSING = "addressing"
    STYLE_WORD = "style_word"
    STRUCTURE = "structure"
    OTHER = "other"


class ProjectPreference(BaseModel):
    """一条已学习的项目偏好（结构化偏好表，非向量——ADR-G）.

    Attributes:
        id: 偏好 UUID 字符串（uuid4）.
        project_id: 所属项目 UUID.
        category: 分类维度.
        pattern: 模式描述（被替换的旧文本片段，如「她」→「林晚」的「她」）.
        value: 偏好值（用户反复修改后保留的新文本，如「林晚」）.
        confidence: 置信度（0-1，随 count 增长单调递增，公式见 spec §5.2）.
        count: 支撑事件数（≥2 才落库）.
        source_events: 支撑事件 id 列表（memory_events.id，可追溯）.
        active_watermark_at_last_access: 上次注入/访问时的项目活跃水位（用于 Δt_active 计算）.
        superseded_by: 被取代的旧偏好 value（新 value 落库前 LLM 判定显式覆盖；"" = 未被取代）.
        created_at: 创建时间（UTC）.
        updated_at: 最后更新时间（UTC）.
    """

    model_config = {"from_attributes": True}

    id: str
    project_id: uuid.UUID
    category: PreferenceCategory
    pattern: str
    value: str
    confidence: float
    count: int
    source_events: list[str] = []
    active_watermark_at_last_access: float = 0.0
    """上次注入/访问时的项目活跃水位（用于 Δt_active 计算）；旧数据缺省 0"""
    superseded_by: str = ""
    """被取代的旧偏好 value（F49 ② LLM 判定显式覆盖标记）；"" = 未被取代"""
    created_at: datetime
    updated_at: datetime
