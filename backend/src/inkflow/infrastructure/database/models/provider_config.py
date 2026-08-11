"""ProviderConfig ORM 模型 — 映射到 provider_configs 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法
（同 F1 project.py / F13 foreshadowing.py）。

设计约定（spec §8.2）:
- DB 主键为 int 自增；name 唯一（注册表 provider 名唯一）
- models 存 JSON 列（list[dict]，仿 ProjectORM.config），转换函数在 repo 层
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层）
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base, LenientJSON


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class ProviderConfigORM(Base):
    """Provider 注册表 ORM 模型 — 映射到 provider_configs 表."""

    __tablename__ = "provider_configs"

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
    """provider 名（注册表唯一）."""

    builtin_key: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    """内置行稳定标识（openai/deepseek/zhipu/ollama；用户行 = None，seed 插入时设置）."""

    base_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    """OpenAI 兼容端点（None = 用 SDK/内置默认）."""

    default_model: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    """默认模型字符串（provider/model 格式）."""

    models: Mapped[list] = mapped_column(
        LenientJSON(fallback=[]),
        nullable=False,
        default=list,
    )
    """模型条目 JSON 列表（list[dict]：id/type/roles，仿 ProjectORM.config）."""

    max_retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
    )
    """重试次数，默认 3."""

    timeout: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=120,
    )
    """请求超时秒数，默认 120."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    """记录创建时间（UTC）. """

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    """记录最后更新时间（UTC，自动更新）. """

    def __repr__(self) -> str:
        return f"<ProviderConfigORM id={self.id} name={self.name!r}>"
