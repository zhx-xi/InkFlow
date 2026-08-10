"""F28 偏好 / 记忆事件 ORM 模型 — 映射到 project_preferences / memory_events 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法（同 F27 agent_run.py）.

设计约定（spec §2.3，父侧契约 test_preference_repo.py / test_memory_event_repo.py）：
- id 存储形态为 uuid4 字符串（与 AgentRunORM.id 一致，SQLite 兼容）
- project_id / chapter_id 为 uuid4 字符串列（String(36) + index，镜像
  AgentExecutionORM 先例——F4 实测：agent_executions.project_id 即 String(36)
  无 FK），存 str(uuid)；领域 UUID → 字符串转换在 repo 层
- 无 FK 声明：projects/chapters 主键为 int 自增，String(36) uuid 值与 int
  主键永远不匹配，FK 声明会误导（PRAGMA foreign_keys=ON 时拦截插入）——
  级联删除语义由服务层承担（与 agent_executions 同构）
- source_events 为 JSON 快照列（事件 id 字符串列表，Q2 独立表可追源）
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class ProjectPreferenceORM(Base):
    """一条已学习的项目偏好 — 映射到 project_preferences 表."""

    __tablename__ = "project_preferences"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    """偏好 UUID 主键（uuid4 字符串，兼容 SQLite）"""

    project_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )
    """所属项目 UUID 字符串（已索引；无 FK——镜像 agent_runs/drafts 先例）"""

    category: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    """偏好分类（addressing/style_word/structure/other，Q1 拍板非向量）"""

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
    """置信度（0-1，随 count 增长单调递增，公式见 spec §5.2）"""

    count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    """支持事件数（≥N 才落库，count desc 排序依据）"""

    source_events: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    """支持事件 id 列表 JSON 快照（memory_events.id，可追源）"""

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
        return f"<ProjectPreferenceORM id={self.id!r} pattern={self.pattern!r}>"


class MemoryEventORM(Base):
    """一次用户修改/确认/重新生成行为的 diff 事件快照 — 映射到 memory_events 表."""

    __tablename__ = "memory_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    """事件 UUID 主键（uuid4 字符串，兼容 SQLite）"""

    project_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )
    """所属项目 UUID 字符串（已索引；无 FK——镜像 agent_runs/drafts 先例）"""

    draft_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    """关联草稿 id（可空，无 FK——镜像 drafts 先例）"""

    chapter_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    """目标章节 UUID 字符串（可空，无 FK——镜像 drafts 先例）"""

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    """来源 agent run id（可空，无 FK）"""

    event_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    """事件类型（draft_edited/draft_rejected/draft_confirmed）"""

    before_content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    """修改前内容（edited 必填，rejected/confirmed 可空）"""

    after_content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    """修改后内容（edited 必填，rejected 可空）"""

    diff_chars: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    """修改量 = len(after) - len(before) 字符数差（可负，只读统计用）"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )
    """事件时间（UTC）"""

    def __repr__(self) -> str:
        return f"<MemoryEventORM id={self.id!r} event_type={self.event_type!r}>"
