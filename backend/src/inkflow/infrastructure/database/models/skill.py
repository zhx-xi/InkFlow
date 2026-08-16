"""SkillORM 模型 — 映射到 skills 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法（同 F1 project.py /
provider_config.py）。

设计约定（spec §2.2）:
- DB 主键为 int 自增；name 唯一（skill 名称唯一）
- content 存完整 SKILL.md（frontmatter + markdown 正文，原样存储）
- source 存 "builtin" | "user_upload"（内置只读保护在 service 层）
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层）
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class SkillORM(Base):
    """Skill 表 ORM 模型 — 映射到 skills 表."""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    """自增主键."""

    name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    """skill 名（唯一，frontmatter name 提取）."""

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """描述（frontmatter description 提取）."""

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """完整 SKILL.md 内容（frontmatter + markdown 正文，原样存储）."""

    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="user_upload",
    )
    """来源（"builtin" | "user_upload"）."""

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
        return f"<SkillORM id={self.id} name={self.name!r}>"
