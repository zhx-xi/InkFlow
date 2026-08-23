"""F45 M1 用户级偏好 ORM 模型 — 映射到 user_preferences 表（spec §2.4）.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法（同 F28 preference.py）.

设计约定（spec §2.4，父侧契约 test_user_preference_repo.py）：
- id 存储形态为 uuid4 字符串（与 ProjectPreferenceORM.id 一致，SQLite 兼容）
- 全局表（无 project_id 列），category 维度与项目级一致（四类复用）
- source_projects / source_events 为 JSON 快照列（项目 id / 事件 id 字符串列表，
  惰性重算 Q1=B 与跨项目追溯用）
- 无 FK 声明：projects 主键为 int 自增，String(36) uuid 值与 int 主键永远不匹配
  （镜像 F28 preference.py 先例）——级联删除语义由服务层承担
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base, LenientJSON


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class UserPreferenceORM(Base):
    """一条已学习的用户级偏好（全局跨项目）— 映射到 user_preferences 表."""

    __tablename__ = "user_preferences"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    """偏好 UUID 主键（uuid4 字符串，兼容 SQLite）"""

    category: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    """偏好分类（addressing/style_word/structure/other，复用 F28 四类）"""

    pattern: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    """模式描述（被替换的旧文本片段，如「她」→「林晚」的「她」）"""

    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    """偏好值（用户反复修改后保留的新文本，如「林晚」）"""

    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    """置信度（0-1，随 count 增长单调递增，公式见 F28 spec §5.2）"""

    count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    """支持事件数（跨项目累计，≥2 且项目数 ≥2 才落库，count desc 排序依据）"""

    project_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    """支撑项目数（≥2 才落库——保守规则防单项目特有设定混算）"""

    source_projects: Mapped[list] = mapped_column(
        LenientJSON(fallback=[]),
        nullable=False,
        default=list,
    )
    """支撑项目 id 字符串列表 JSON 快照（惰性重算 Q1=B 用）"""

    source_events: Mapped[list] = mapped_column(
        LenientJSON(fallback=[]),
        nullable=False,
        default=list,
    )
    """支撑事件 id 列表 JSON 快照（memory_events.id，可追源）"""

    active_watermark_at_last_access: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    """上次访问时的项目活跃水位（float，默认 0.0）"""

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
        return f"<UserPreferenceORM id={self.id!r} pattern={self.pattern!r}>"
