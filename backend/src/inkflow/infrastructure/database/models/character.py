"""角色/分组/关系 ORM 模型 — 映射到 characters, character_groups, character_relations 表.

使用 SQLAlchemy 2.0 Mapped + mapped_column 新式映射语法（同 F1 project.py）。

设计约定（同 F1 §12 / F9 spec §2）:
- DB 主键为 int 自增；领域层 id 为 UUID，映射规则: domain_id = uuid.UUID(int=orm.id)
  （int↔UUID 转换函数在 repositories/character_repo.py，参照 project_repo.py 惯例）
- 软删除标记 is_deleted + partial unique index（sqlite_where）保证
  「活动记录唯一、软删除后可重建同名」的语义（spec §2.4）
- FK 级联: 项目删除 → 角色/分组/关系级联删除；分组删除 → 成员 group_id 置 NULL；
  角色硬删除 → 关系物理删除
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base, LenientJSON


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class CharacterORM(Base):
    """角色 ORM 模型 — 映射到 characters 表.

    Maps to the ``characters`` table. Each row corresponds to one
    character profile within a project.
    """

    __tablename__ = "characters"

    __table_args__ = (
        Index(
            "uq_characters_active_name",
            "project_id",
            "name",
            unique=True,
            sqlite_where=text("is_deleted = 0"),
        ),
    )
    """项目内活动角色名唯一（软删除后允许重建同名，spec §2.4）."""

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

    name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    """角色名 (1–50 字符，去空白)."""

    personality: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """性格描述 (≤ 5000 字符)."""

    background: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """背景故事 (≤ 20000 字符)."""

    goals: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    """目标/动机 (≤ 5000 字符)."""

    group_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("character_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """所属分组（分组删除时置 NULL，已索引）."""

    extra: Mapped[dict] = mapped_column(
        LenientJSON(fallback={}),
        nullable=False,
        default=dict,
    )
    """扩展字典（外貌/口头禅等 Phase 2+ 字段预留）."""

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    """软删除标记（已索引，用于过滤查询）."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )
    """记录创建时间（UTC）. """

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    """记录最后更新时间（UTC，自动更新）. """

    def __repr__(self) -> str:
        return f"<CharacterORM id={self.id} name={self.name!r}>"


class CharacterGroupORM(Base):
    """角色分组 ORM 模型 — 映射到 character_groups 表.

    Maps to the ``character_groups`` table. Groups organize characters
    into factions/orgs (e.g. 「主角团」「反派」).
    """

    __tablename__ = "character_groups"

    __table_args__ = (
        Index(
            "uq_character_groups_active_name",
            "project_id",
            "name",
            unique=True,
            sqlite_where=text("is_deleted = 0"),
        ),
    )
    """项目内活动分组名唯一（软删除后允许重建同名，spec §2.4）."""

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

    name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    """分组名 (1–50 字符，去空白)."""

    description: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
    )
    """分组说明 (≤ 500 字符)."""

    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    """列表排序权重（小者在前，≥ 0）."""

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    """软删除标记."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )
    """记录创建时间（UTC）. """

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    """记录最后更新时间（UTC，自动更新）. """

    def __repr__(self) -> str:
        return f"<CharacterGroupORM id={self.id} name={self.name!r}>"


class CharacterRelationORM(Base):
    """角色关系 ORM 模型 — 映射到 character_relations 表（有向边）.

    Maps to the ``character_relations`` table. Each row is a directed
    edge in the character relationship graph (from → to).
    """

    __tablename__ = "character_relations"

    __table_args__ = (
        Index(
            "uq_character_relations_active_key",
            "project_id",
            "from_character_id",
            "to_character_id",
            "relation_type",
            unique=True,
            sqlite_where=text("is_deleted = 0"),
        ),
    )
    """活动关系中 (project, from, to, relation_type) 唯一（spec §2.4）."""

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
    """所属项目（冗余存储，便于按项目查询与隔离；项目删除级联删除，已索引）."""

    from_character_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """关系起点（角色硬删除级联删除，已索引）."""

    to_character_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """关系终点（角色硬删除级联删除，已索引）."""

    relation_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    """关系类型 (1–20 字符，去空白，自由文本)."""

    description: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
    )
    """关系说明 (≤ 500 字符)."""

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    """软删除标记."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
    )
    """记录创建时间（UTC）. """

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
    """记录最后更新时间（UTC，自动更新）. """

    def __repr__(self) -> str:
        return (
            f"<CharacterRelationORM id={self.id} "
            f"{self.from_character_id}->{self.to_character_id} {self.relation_type!r}>"
        )
