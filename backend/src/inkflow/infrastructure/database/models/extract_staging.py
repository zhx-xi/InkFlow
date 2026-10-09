"""提取两段式暂存 ORM 模型 — 映射到 extract_staging 表（#1545，§5.9）.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法
（同 extraction_run.py / character.py）。

设计约定（F14 spec §5.9 / §8）:
- DB 主键为 int 自增；暂存行不承载业务实体身份（物化时才生成正式实体），
  故无 uuid 身份列（不进 ENTITY_UUID_TABLES）
- project_id 为 INTEGER FK → projects.id（同 characters / extraction_runs，
  领域 UUID 由 repo 层经 require_int_pk 映射为 int）
- FK 级联: 项目硬删除 → 暂存行级联物理删除
- 索引: batch_id（按批读取 / 删除，§5.9）+ project_id（项目隔离 / 级联清理）
- payload 存 JSON 文本（Text）——confirm 时反序列化回领域实体（Character /
  WorldSetting），故不做 JSON 列类型推断
- 本文件为纯 ORM 映射，不含领域转换函数（转换在
  repositories/extract_staging_repo.py）
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class ExtractStagingORM(Base):
    """提取暂存行 ORM 模型 — 映射到 extract_staging 表（§5.9）.

    Maps to the ``extract_staging`` table. Each row is one pending extraction
    product awaiting user confirmation; confirm materializes them into the
    formal tables and clears the batch (spec §5.9).
    """

    __tablename__ = "extract_staging"

    __table_args__ = (
        Index("ix_extract_staging_batch_id", "batch_id"),
        Index("ix_extract_staging_project_id", "project_id"),
    )
    """batch_id 索引（按批读取 / 删除，§5.9）+ project_id 索引（项目隔离）."""

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    """自增主键（暂存行序号，读取按写入序返回）."""

    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    """所属项目（项目硬删除级联清理；索引见 __table_args__）."""

    batch_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    """批次标识（同一次提取的全部源共享，与 §5.8.5 回滚批次同形态）."""

    type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    """提取类型（ExtractionType.value；首刀仅 character / setting）."""

    entity_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    """实体类型（``character`` / ``world_setting``，决定 confirm 物化路径）."""

    action: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
    )
    """动作（``create`` → repo.add；``update`` → repo.update，§5.9）."""

    target_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    """update 时指向被覆盖行（暂存行 payload 内的实体 UUID 字符串；create 为 NULL）."""

    payload: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    """条目原始 model_dump（JSON 文本），confirm 时反序列化回领域实体."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    """暂存时间（UTC）."""

    def __repr__(self) -> str:
        return (
            f"<ExtractStagingORM id={self.id} batch_id={self.batch_id!r} "
            f"entity_type={self.entity_type!r} action={self.action!r}>"
        )
