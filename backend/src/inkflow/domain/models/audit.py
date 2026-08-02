"""一致性审计领域模型 — 审计报告与发现（F15 横切审计型模块）.

AuditDimension / AuditSeverity 是维度与严重级别枚举；AuditFinding 是单条
审计发现（id 为稳定键，供快照断言与去重）；DimensionSummary / AuditSummary /
AuditReport 构成审计报告三层结构（维度计数 / 汇总 / 明细 + 时间线深挖）。
F15 不新建业务实体表——报告是当前数据快照的只读计算结果，全部为纯 Pydantic
输出模型，model_dump(mode="json") 直接进 API/CLI 信封（spec §2.5）。

引用 F12 ConsistencyReport（domain/models/timeline.py 已定义）作为时间线
维度的嵌套原始报告——引用不重定义（spec §2.4）。

依据: specs/f15-audit-service/spec.md §2。
领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from inkflow.domain.models.timeline import ConsistencyReport  # F12 已定义，引用不重定义（§2.4）


class AuditDimension(StrEnum):
    """审计维度（spec §2.1）.

    Attributes:
        CHARACTER: 角色（关系/分组引用完整性）.
        TIMELINE: 时间线（委托 F12 双线一致性）.
        WORLD: 世界（档案健康度 + 缺口）.
        FORESHADOWING: 伏笔（event_id 锚点 + 状态机）.
        CROSS: 跨维度联动（事件→章节、提取缺口）.
    """

    CHARACTER = "character"  # 角色（关系/分组引用完整性）
    TIMELINE = "timeline"  # 时间线（委托 F12 双线一致性）
    WORLD = "world"  # 世界（档案健康度 + 缺口）
    FORESHADOWING = "foreshadowing"  # 伏笔（event_id 锚点 + 状态机）
    CROSS = "cross"  # 跨维度联动（事件→章节、提取缺口）


class AuditSeverity(StrEnum):
    """严重级别（spec §2.1/§6.2）.

    Attributes:
        ERROR: 引用断裂 / 状态矛盾 —— 数据不一致，需修正.
        WARNING: 软删引用 / 可恢复异常 —— 数据一致但值得注意.
        INFO: 缺口 / 健康度提示 —— 不涉及一致性.
    """

    ERROR = "error"  # 引用断裂 / 状态矛盾 —— 数据不一致，需修正
    WARNING = "warning"  # 软删引用 / 可恢复异常 —— 数据一致但值得注意
    INFO = "info"  # 缺口 / 健康度提示 —— 不涉及一致性


class AuditFinding(BaseModel):
    """单条审计发现（spec §2.2）— id 为稳定键，供快照断言与去重.

    Attributes:
        id: 稳定键 f"{rule_id}:{entity_key}"（entity_key = 实体 UUID 字符串；
            时间线冲突对 = "{prev_id}:{next_id}"，run 缺口 = source_key）.
        rule_id: 规则标识（如 character.relation_ref；完整清单见 spec §5.2）.
        dimension: 所属维度（由 rule_id 决定，冗余存储便于过滤）.
        severity: 严重级别（规则固定级别）.
        message: 人类可读描述（含修正建议）.
        entity_type: 违规主体类型（character/relation/group/world_setting/
            event/foreshadowing/chapter/run）.
        entity_id: 违规主体 id（run 缺口无 UUID → None，id 字段承载）.
        entity_name: 违规主体名称（标题/姓名/条目名；无名称场景用 id 短串）.
        ref_type: 引用目标类型（悬空/软删场景：character/group/event/chapter）.
        ref_id: 引用目标 id（如悬空的 to_character_id）.
        data: 附加上下文（时间线冲突对快照、run 状态等）.
    """

    id: str
    rule_id: str
    dimension: AuditDimension
    severity: AuditSeverity
    message: str
    entity_type: str
    entity_id: uuid.UUID | None = None  # run 缺口无 UUID → None，id 字段承载
    entity_name: str = ""  # 无名称场景用 id 短串
    ref_type: str | None = None  # 悬空/软删场景的引用目标类型
    ref_id: uuid.UUID | None = None  # 引用目标 id（如悬空的 to_character_id）
    data: dict[str, Any] = Field(default_factory=dict)  # 附加上下文（冲突对快照、run 状态等）


class DimensionSummary(BaseModel):
    """单维度发现计数（spec §2.3）.

    Attributes:
        error: error 级发现数.
        warning: warning 级发现数.
        info: info 级发现数.
    """

    error: int = 0
    warning: int = 0
    info: int = 0


class AuditSummary(BaseModel):
    """审计汇总（spec §2.3）— consistent 仅由 error 级 findings 决定.

    Attributes:
        consistent: error 级 findings 为空.
        total: findings 总数.
        by_dimension: 5 维度计数.
        counts: 档案规模观测（角色/关系/分组/条目/事件/伏笔/章节/runs 计数）.
    """

    consistent: bool  # error 级 findings 为空
    total: int  # findings 总数
    by_dimension: dict[AuditDimension, DimensionSummary] = Field(default_factory=dict)  # 5 维度计数
    counts: dict[str, int] = Field(default_factory=dict)  # 档案规模观测


class AuditReport(BaseModel):
    """审计报告（spec §2.3）— 只读计算的瞬态结果，不落库.

    Attributes:
        project_id: 所属项目 UUID.
        generated_at: 生成时间 (UTC).
        summary: 审计汇总.
        findings: 审计发现列表（按 (dimension 序, severity 序, entity_name)
            稳定排序，spec §6.3）.
        timeline_check: F12 原始报告嵌套（时间线维度深挖；无事件/委托失败
            为 None 的语义见 spec §5.3）.
    """

    project_id: uuid.UUID
    generated_at: datetime  # UTC
    summary: AuditSummary
    findings: list[AuditFinding] = Field(default_factory=list)
    timeline_check: ConsistencyReport | None = None  # F12 原始报告嵌套（引用不重定义，§2.4）
