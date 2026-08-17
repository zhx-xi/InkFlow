"""F45 M2 语义总结 ORM 模型 — 映射到 semantic_summaries 表（spec §2.4）.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法（镜像
user_preference.py 形态）。

设计约定（spec §2.4，父侧契约 test_semantic_summary_repo.py）：
- id 存储形态为 uuid4 字符串（与 user_preferences.id 一致，SQLite 兼容）
- scope=user 时 project_id=None（用户级总结全局仅一份，spec §5.3）
- anchor_hash 为锚点集合的确定性指纹（SHA-256 排序锚点键，spec §5.4）
- 无 FK 声明：projects 主键为 int 自增，String(36) uuid 值与 int 主键永远不匹配
  （镜像 user_preferences 先例）——级联删除语义由服务层承担
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class SemanticSummaryORM(Base):
    """一条 LLM 语义总结（项目级/用户级）— 映射到 semantic_summaries 表."""

    __tablename__ = "semantic_summaries"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    """总结 UUID 主键（uuid4 字符串，兼容 SQLite）"""

    scope: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    """归属范围（project/user，spec §2.3 SummaryScope）"""

    project_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    """项目 UUID 字符串（scope=user 时为 None，用户级总结全局单一，spec §5.3）"""

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    """抽象风格指令文本（LLM 产出）"""

    anchor_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    """锚点集合哈希（SHA-256 排序锚点键，幂等复用判据，spec §5.4）"""

    anchor_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    """锚点数（证据量，可解释性）"""

    model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    """生成模型（config.llm_default_model，代码不写第二份默认值）"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )
    """创建时间（UTC）"""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    """最后更新时间（UTC，自动更新）"""

    def __repr__(self) -> str:
        return f"<SemanticSummaryORM id={self.id!r} content={self.content!r}>"
