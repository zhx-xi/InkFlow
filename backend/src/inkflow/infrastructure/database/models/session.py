"""会话 ORM 模型 —— 映射到 sessions / session_logs 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新版映射语法（同 F12 timeline.py）。

设计约定（spec §2/§8）：
- DB 主键为 int 自增；领域层 id 为 UUID，
  映射规则: domain_id = uuid.UUID(int=orm.id)（int→UUID 转换函数在
  repositories/session_repo.py，参照 timeline_repo.py 惯例）
- SessionORM: 四态状态机 + 上下文/结果 JSON 快照 + 软删除标记；
  索引: session_type / status / project_id / is_deleted
- SessionLogORM: 会话履历日志（追加语义，不可篡改）；
  索引: session_id + (session_id, seq) 唯一约束（seq 会话内唯一）
- FK 级联: 项目硬删除 → project_id 置 NULL（履历保留）；
  会话硬删除 → 日志级联物理删除（DB FK CASCADE）
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层，
  陷阱 7：ORM 层只放纯映射类）
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class SessionORM(Base):
    """会话 ORM 模型 —— 映射到 sessions 表."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    """自增主键（领域层映射为 UUID）."""

    session_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    """会话类型: writing / task（已索引）."""

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        index=True,
    )
    """会话状态: active / paused / completed / failed（已索引）."""

    project_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """所属项目（可空 = 全局会话；项目硬删除 → 置 NULL 保留履历）."""

    title: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    """会话标题 (1-100 字符，去空白；允许重复，实例语义)."""

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """会话描述/备注 (≤5000 字符)."""

    context: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    """上下文快照（JSON）: 写作会话 = 续写上下文；任务会话 = 任务参数."""

    result: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    """结果快照（JSON）: completed 时填写."""

    error: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """失败原因（failed 时填写，≤2000 字符）."""

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    """会话开始时间（UTC，默认 = 创建时间）."""

    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    """最近一次暂停时间（UTC，可空）."""

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    """完成/失败时间（UTC，可空）."""

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    """软删除标记（已索引；归档会话不进列表查询）."""

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
        return f"<SessionORM id={self.id} title={self.title!r}>"


class SessionLogORM(Base):
    """会话日志 ORM 模型 —— 映射到 session_logs 表."""

    __tablename__ = "session_logs"

    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_session_logs_session_seq"),)
    """(session_id, seq) 唯一约束: 会话内 seq 唯一（追加语义，spec §8）."""

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    """自增主键（领域层映射为 UUID）."""

    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """所属会话（会话硬删除 → 日志级联物理删除；已索引）."""

    seq: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    """会话内递增序号（从 1 起，服务层分配 = 会话内 max(seq)+1）."""

    level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="info",
    )
    """日志级别: info / warning / error."""

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    """日志消息 (1-2000 字符，去空白)."""

    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    """结构化负载（JSON）: 进度百分比 / token 消耗 / 章节 id 等."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    """日志时间（UTC）."""

    def __repr__(self) -> str:
        return f"<SessionLogORM id={self.id} session_id={self.session_id} seq={self.seq}>"
