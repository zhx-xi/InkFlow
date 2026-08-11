"""AgentTemplate ORM 模型 — 映射到 agent_templates 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法
（同 F1 project.py / provider_config.py）。

设计约定（spec §9.2）:
- DB 主键为 int 自增；name 唯一（模板名称唯一）
- roles 存 JSON 列（dict：{key: RoleTemplate.model_dump()}，仿 ProjectORM.config），
  转换函数在 repo 层
- is_default 单例：全表至多一条 is_default=True（repo 层保证）
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层）
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base, LenientJSON


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class AgentTemplateORM(Base):
    """模板表 ORM 模型 — 映射到 agent_templates 表."""

    __tablename__ = "agent_templates"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    """自增主键."""

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
    )
    """模板名称（唯一）."""

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """模板描述."""

    main_model: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    """主模型（None = 跟随默认）."""

    default_temperature: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    """全角色兜底温度（None = 跟随默认）."""

    roles: Mapped[dict] = mapped_column(
        LenientJSON(fallback={}),
        nullable=False,
        default=dict,
    )
    """四角色 JSON 列（{key: RoleTemplate.model_dump()}）."""

    default_words: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    """章节默认字数（None = 跟随默认）."""

    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    """是否当前默认模板（单例，全表至多一条 True）."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    """记录创建时间（UTC）."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    """记录最后更新时间（UTC，自动更新）."""

    def __repr__(self) -> str:
        return f"<AgentTemplateORM id={self.id} name={self.name!r}>"
