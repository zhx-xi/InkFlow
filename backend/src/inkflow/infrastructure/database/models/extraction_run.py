"""统一提取增量追踪记录 ORM 模型 — 映射到 extraction_runs 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法
（同 F1 project.py / F9 character.py / F13 foreshadowing.py）。

设计约定（F14 spec §2.3 / §8）:
- DB 主键为 int 自增；领域层 id 直接暴露 int（run 仅供状态查询，
  同 timeline_events 先例，无 UUID 映射）
- 唯一约束 UNIQUE (project_id, type, source_key)（__table_args__ +
  UniqueConstraint，name="uq_extraction_runs_source"）——同一 (项目, 类型, 源)
  只保留**最新一次** run 状态（upsert，spec §2.3）；历史变更审计归 F15
- 索引: project_id（项目隔离 / 级联清理）/ type（runs 查询按类型过滤，§3.3）
- FK 级联: 项目硬删除 → run 级联物理删除（spec §2.3）；章节删除后
  run 行保留（孤儿行，不影响任何逻辑，spec §2.3 业务规则）
- status 默认 "success"（失败 run 也落库，供 extract status 观察缺口）
- 本文件为纯 ORM 映射，不包含任何领域转换函数（转换在 repo 层
  repositories/extraction_run_repo.py）
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class ExtractionRunORM(Base):
    """统一提取增量追踪记录 ORM 模型 — 映射到 extraction_runs 表.

    Maps to the ``extraction_runs`` table. Each row records the **latest**
    extraction state for one (project_id, type, source_key); upsert keeps
    only one row per source (spec §2.3).
    """

    __tablename__ = "extraction_runs"

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "type",
            "source_key",
            name="uq_extraction_runs_source",
        ),
        Index("ix_extraction_runs_project_id", "project_id"),
        Index("ix_extraction_runs_type", "type"),
    )
    """(项目, 类型, 源) 唯一 — 同键只保留最新一次 run 状态（upsert 冲突键）+
    项目隔离 / 类型过滤查询索引（spec §2.3/§8）."""

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    """自增主键（领域层直接暴露 int，同 timeline_events 先例）."""

    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    """所属项目（项目硬删除级联清理；索引见 __table_args__）."""

    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    """提取类型（ExtractionType.value，索引见 __table_args__）."""

    source_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    """源标识: 章节模式 = str(chapter_id)；手动模式 = "manual"；outline /
    timeline 关闭时固定 "full"（spec §2.3）."""

    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    """源内容 sha256（UTF-8）— 增量提取判定指纹（spec §5.2）."""

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="success",
    )
    """本次运行状态 (success / skipped / error；失败 run 也落库)."""

    created_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    """该源本次新增数."""

    updated_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    """该源本次更新数."""

    warnings_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    """warnings JSON 序列化（loguru 之外的持久化可观测性）."""

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    """status=error 时的错误消息（截断 ≤ 500 字符）."""

    model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    """该源实际使用的 LLM 模型."""

    indexed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    """该源是否已索引（index=true 且类型支持时置 True）."""

    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    """本次运行时间（UTC）."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    """记录创建时间（UTC，首次 upsert 落库）."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    """记录最后更新时间（UTC，自动更新）."""

    def __repr__(self) -> str:
        return f"<ExtractionRunORM id={self.id} type={self.type!r} source_key={self.source_key!r}>"
