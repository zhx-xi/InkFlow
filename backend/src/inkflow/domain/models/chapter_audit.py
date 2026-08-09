"""F34 章节审计领域模型 — 检查项/严重级别枚举 + 报告/记录/DTO.

AuditCheckType / AuditSeverity 是检查项与严重级别枚举；ChapterAuditFinding
是单条审计发现；ChapterAuditReport 是瞬态审计报告（一次审计的完整结果）；
AuditLog 是轻量审计记录实体（Q1=C：摘要级落库，无 findings 明细）；
AuditTriggerRequest / AuditConfirmRequest 是触发/确认 DTO（GUI 与 CLI 共用）。

依据: specs/f34-chapter-audit/spec.md §2。
领域层保持纯净：仅依赖 Pydantic v2 与标准库，不感知 ORM / 框架。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class AuditCheckType(StrEnum):
    """章节审计检查项（spec §2.1）— 4 项.

    Attributes:
        WORD_COUNT: 字数检查（F2 确定性）.
        CHARACTER_DRIFT: 人设漂移（LLM 分析，vs F9 角色档案）.
        SETTING_DRIFT: 设定漂移（LLM 分析，vs F10 世界观条目）.
        STATIC_CONSISTENCY: 静态一致性（委托 F15，可选包含）.
    """

    WORD_COUNT = "word_count"  # 字数检查（F2 确定性）
    CHARACTER_DRIFT = "character_drift"  # 人设漂移（LLM，vs F9 角色档案）
    SETTING_DRIFT = "setting_drift"  # 设定漂移（LLM，vs F10 世界观条目）
    STATIC_CONSISTENCY = "static_consistency"  # 静态一致性（委托 F15）


class AuditSeverity(StrEnum):
    """审计发现严重级别（spec §2.2）— info/warning/error 三级.

    Attributes:
        INFO: 提示（如字数低于目标）.
        WARNING: 警告（行为疑似与人设/设定冲突）.
        ERROR: 错误（明确与档案/设定矛盾）.
    """

    INFO = "info"  # 提示（如：章节字数低于目标 20%）
    WARNING = "warning"  # 警告（如：角色行为可能与人设冲突）
    ERROR = "error"  # 错误（如：明确与设定矛盾）


class ChapterAuditFinding(BaseModel):
    """单条章节审计发现（spec §2.2）.

    Attributes:
        check_type: 所属检查项.
        severity: 严重级别.
        message: 人类可读描述（中文）.
        suggestion: 修改建议（LLM 给，可为空）.
        ref_entity_id: 关联档案条目（角色/设定），无则 None.
        ref_entity_name: 关联条目名（展示用）.
        context: 章节中相关片段（≤200 字，定位用）.
    """

    model_config = {"from_attributes": True}

    check_type: AuditCheckType
    severity: AuditSeverity
    message: str
    suggestion: str = ""  # 修改建议（LLM 给，可为空）
    ref_entity_id: uuid.UUID | None = None  # 关联档案条目（角色/设定），无则 None
    ref_entity_name: str = ""  # 关联条目名（展示用）
    context: str = ""  # 章节中相关片段（≤200 字，定位用）


class ChapterAuditReport(BaseModel):
    """瞬态章节审计报告（spec §2.2）— 一次审计的完整结果，不落库.

    Attributes:
        chapter_id: 所属章节 UUID.
        chapter_title: 章节标题快照（展示用）.
        status: 确认状态（pending/accepted/rejected，默认 pending）.
        findings: 审计发现列表.
        summary: LLM 一句话总结（可选）.
        degraded: LLM 检查是否降级（记录进 audit_logs）.
        created_at: 审计生成时间（UTC）.
        confirmed_at: 确认时间（pending 为 None）.
    """

    model_config = {"from_attributes": True}

    chapter_id: uuid.UUID
    chapter_title: str
    status: Literal["pending", "accepted", "rejected"] = "pending"
    findings: list[ChapterAuditFinding]  # 必填（spec §2.2；测试 docstring 亦声明必填）
    summary: str = ""  # LLM 一句话总结（可选）
    degraded: bool = False  # LLM 检查是否降级
    created_at: datetime  # 审计生成时间（UTC）
    confirmed_at: datetime | None = None  # 确认时间（pending 为 None）


class AuditLog(BaseModel):
    """单次审计的轻量记录（spec §2.3，Q1=C）— 可追溯，无 findings 明细.

    Attributes:
        id: 审计记录 UUID（ORM 主键 int 背书）.
        project_id: 所属项目 UUID.
        chapter_id: 所属章节 UUID.
        chapter_title: 章节标题快照（章节改名后仍可读）.
        status: 确认状态（pending/accepted/rejected）.
        severity_summary: 严重级别摘要（如 "1 error, 2 warnings, 0 info"）.
        summary: LLM 一句话总结（可空）.
        degraded: LLM 降级标记（可追溯审计质量）.
        note: 拒绝原因/备注（用户确认时填写，可空）.
        created_at: 审计时间（UTC）.
        confirmed_at: 确认时间（pending 为 None）.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    chapter_id: uuid.UUID
    chapter_title: str  # 快照（章节改名后仍可读）
    status: Literal["pending", "accepted", "rejected"]
    severity_summary: str  # 摘要：如 "1 error, 2 warnings, 0 info"（计数落库）
    summary: str = ""  # LLM 一句话总结（可空）
    degraded: bool = False  # LLM 降级标记（可追溯审计质量）
    note: str = ""  # 拒绝原因/备注（用户确认时填写，可空）
    created_at: datetime  # 审计时间（UTC）
    confirmed_at: datetime | None = None  # 确认时间（pending 为 None）


class AuditTriggerRequest(BaseModel):
    """手动触发审计请求 DTO（spec §2.4）— 自动触发无需 body.

    Attributes:
        include_static: 是否包含 F15 静态一致性委托（默认 True）.
    """

    model_config = {"from_attributes": True}

    include_static: bool = True  # 是否包含 F15 静态一致性委托


class AuditConfirmRequest(BaseModel):
    """用户确认请求 DTO（spec §2.4）— GUI 与 CLI 共用同一契约（Q2=B）.

    Attributes:
        action: 确认动作（accept=接受 / reject=拒绝）.
        note: 拒绝原因/备注（可选，写入 audit_logs.note）.
    """

    model_config = {"from_attributes": True}

    action: Literal["accept", "reject"]
    note: str = ""  # 拒绝原因/备注（可选，写入 audit_logs.note）
