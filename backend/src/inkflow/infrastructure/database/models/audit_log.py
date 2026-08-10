"""F34 审计日志 ORM 模型 — 映射到 audit_logs 表.

设计约定（spec §2.3/§8.1）：
- DB 主键为 int 自增；领域层 id 为 UUID，
  映射规则: domain_id = uuid.UUID(int=orm.id)（转换在
  repositories/audit_log_repo.py）
- 轻量记录（Q1=C）：仅摘要级字段，无 findings 明细/JSON 快照
- FK 级联: 项目/章节硬删除 → 审计记录随删（附属记录，非独立资产，E14）
- schema 由 Base.metadata.create_all 管理，零迁移
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层，
  陷阱 7：ORM 层只放纯映射类）
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class AuditLogORM(Base):
    """审计日志 ORM 模型 —— 映射到 audit_logs 表."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    """自增主键（领域层映射为 UUID）."""

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
    )
    """所属项目（项目硬删除 → 审计记录级联删除，E14）."""

    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=True,
    )
    """所属章节（可空——F27 save_draft 未绑定章节时审计可空；章节硬删除 →
    审计记录级联删除，E14）."""

    chapter_title: Mapped[str] = mapped_column(
        String(200),
    )
    """章节标题快照（章节改名后仍可读，spec §2.3）."""

    status: Mapped[str] = mapped_column(
        String(10),
    )
    """确认状态: pending / accepted / rejected."""

    severity_summary: Mapped[str] = mapped_column(
        String(50),
    )
    """严重级别摘要（如 "1 error, 2 warnings, 0 info"，计数落库）."""

    summary: Mapped[str] = mapped_column(
        Text,
        default="",
    )
    """LLM 一句话总结（可空）."""

    degraded: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    """LLM 降级标记（可追溯审计质量）."""

    note: Mapped[str] = mapped_column(
        Text,
        default="",
    )
    """拒绝原因/备注（用户确认时填写，可空）."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utcnow,
    )
    """审计时间（UTC，默认 = 记录创建时间）."""

    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    """确认时间（pending 为 None）."""

    def __repr__(self) -> str:
        return f"<AuditLogORM id={self.id} chapter_id={self.chapter_id} status={self.status!r}>"
