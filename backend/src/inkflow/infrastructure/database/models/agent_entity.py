"""AgentORM 模型 — 映射到 agents 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法（同 F1 project.py /
provider_config.py）。⚠️ 文件名用 agent_entity.py（F4 已占用 agent.py 存
AgentExecutionORM）。

设计约定（spec §2.1）:
- DB 主键为 int 自增；name 唯一（Agent 名称唯一）
- tool_ids / skill_ids 存 LenientJSON 列表列（fallback=[]，容错空串/损坏
  JSON，见 #261），转换函数在 repo 层
- builtin 只读保护在 service 层，ORM 仅存储
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


class AgentORM(Base):
    """Agent 表 ORM 模型 — 映射到 agents 表."""

    __tablename__ = "agents"

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
    """Agent 名称（唯一）."""

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """Agent 描述."""

    icon: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="",
    )
    """图标（emoji 字符或图标键；空串 = 默认图标）."""

    system_prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """system prompt（内置 Agent 只读）."""

    tool_ids: Mapped[list] = mapped_column(
        LenientJSON(fallback=[]),
        nullable=False,
        default=list,
    )
    """能力白名单：工具目录 name 列表（JSON 列）."""

    skill_ids: Mapped[list] = mapped_column(
        LenientJSON(fallback=[]),
        nullable=False,
        default=list,
    )
    """能力白名单：Skill.id 字符串化列表（JSON 列）."""

    model_override: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    """模型覆盖（provider/model 格式；None = 跟随默认）."""

    temperature_override: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    """温度覆盖（None = 跟随默认）."""

    builtin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    """是否内置（True = 只读，出厂 seed；False = 用户自定义）."""

    role_key: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    """链角色稳定标识（§5.7.1；None = 非链角色/未分配，服务层自动分配不可变）."""

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
        return f"<AgentORM id={self.id} name={self.name!r}>"
