"""F45 M1 用户级偏好领域模型 — 全局跨项目偏好的结构化产物（UserPreference）.

UserPreference 是用户级偏好学习的统计沉淀（spec §2.2，M1 新增）:
- 全局跨项目（无 project_id 字段），聚合键 (category, value)，count>=2 且
  project_count>=2 才可落库（保守规则防混算，spec §5.1）;
- source_projects 记录支撑项目 id（惰性重算用，Q1=B: 项目删除后查询时
  发现幽灵来源 → 重算/删除）;
- source_events 反查 memory_events 事件详情（可追溯）;
- 删除即停止注入（读路径实时查库无缓存，spec §5.3）.

依据: specs/f45-memory-evolution/spec.md §2.2/§5.1/§7。
领域层保持纯净：仅依赖 Pydantic v2 与标准库，不感知 ORM / 框架。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from inkflow.domain.models.preference import PreferenceCategory


class UserPreference(BaseModel):
    """一条已学习的用户级偏好（全局跨项目，M1 新增，spec §2.2）.

    Attributes:
        id: 偏好 UUID 字符串（uuid4）.
        category: 分类维度（与项目级偏好同维度）.
        pattern: 模式描述（被替换的旧文本片段，如「她」→「林晚」的「她」）.
        value: 偏好值（用户反复修改后保留的新文本，如「林晚」）.
        confidence: 置信度（0-1，随 count 增长单调递增，公式见 F28 spec §5.2）.
        count: 支撑事件数（跨项目累计，>=2 才落库）.
        project_count: 支撑项目数（>=2 才落库，防单项目特有设定混算）.
        source_projects: 支撑项目 id 字符串列表（去重，惰性重算用）.
        source_events: 支撑事件 id 列表（memory_events.id，可追溯）.
        created_at: 创建时间（UTC）.
        updated_at: 最后更新时间（UTC）.
    """

    model_config = {"from_attributes": True}

    id: str
    category: PreferenceCategory
    pattern: str
    value: str
    confidence: float
    count: int
    project_count: int
    source_projects: list[str] = []
    source_events: list[str] = []
    created_at: datetime
    updated_at: datetime
