"""知识图谱关系 ORM 模型 —— 映射到 knowledge_relations 表（无 is_deleted，真删语义）.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法（同 F1 project.py）。

设计约定（同 F9 character_relations 先例 / F48 spec §2.5）：
- DB 主键为 int 自增；领域层 id 为 UUID，映射规则 domain_id = uuid.UUID(int=orm.id)
  （int↔UUID 转换函数在 repositories/knowledge_relation_repo.py）
- 全唯一索引 (project_id, source_type, source_id, target_type, target_id,
  relation_type) 保证「项目内同键关系唯一」
- 跨实体无 DB FK（source_id/target_id 无 ForeignKey）——服务层显式校验
- FK 级联: 项目删除 → 关系级联删除（生产连接 FK 语义见 spec §5.3 D10=b）
- 真删语义: 关系删除 = 物理删除，无 is_deleted、无 restore
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class KnowledgeRelationORM(Base):
    """知识图谱关系 ORM 模型 —— 映射到 knowledge_relations 表.

    Maps to the ``knowledge_relations`` table. Each row is a directed
    edge between two entities of any type (from → to).
    """

    __tablename__ = "knowledge_relations"

    __table_args__ = (
        Index(
            "uq_knowledge_relations_key",
            "project_id",
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation_type",
            unique=True,
        ),
    )
    """项目内六元组关系键全唯一（spec §2.1 规则 4）."""

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    """自增主键（领域层映射为 UUID）."""

    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """所属项目（项目删除级联删除，已索引）."""

    source_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    """关系起点实体类型（EntityType 枚举值）."""

    source_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )
    """关系起点实体主键（int；跨实体无 DB FK，服务层显式校验）."""

    target_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    """关系终点实体类型（EntityType 枚举值）."""

    target_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )
    """关系终点实体主键（int；跨实体无 DB FK，服务层显式校验）."""

    relation_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    """关系类型（1-20 字符，去空白，自由文本）."""

    description: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
    )
    """关系说明（≤ 500 字符，可空串）."""

    source: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="manual",
    )
    """关系来源（manual/ai；v1.0 仅 manual，#479 预留给定时提取）."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )
    """记录创建时间（UTC）."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    """记录最后更新时间（UTC，自动更新）."""

    def __repr__(self) -> str:
        return (
            f"<KnowledgeRelationORM id={self.id} "
            f"{self.source_type}:{self.source_id}--{self.relation_type}-->"
            f"{self.target_type}:{self.target_id}>"
        )
