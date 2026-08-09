"""F36 地图 ORM 模型 — 映射到 maps/map_pins 表（无 is_deleted，真删语义）.

依据: specs/f36-world-map/spec.md §2.4。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


class MapORM(Base):
    """地图 ORM — 映射到 maps 表（无 is_deleted，真删语义）."""

    __tablename__ = "maps"

    __table_args__ = (
        Index("uq_maps_name", "project_id", "name", unique=True),
        Index(
            "uq_maps_root_location",
            "project_id",
            "root_location_id",
            unique=True,
            sqlite_where=text("root_location_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    image_path: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    root_location_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("world_settings.id"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class MapPinORM(Base):
    """地图 pin ORM — 映射到 map_pins 表（无 is_deleted，真删语义）."""

    __tablename__ = "map_pins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    map_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("maps.id"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("world_settings.id"),
        nullable=True,
        index=True,
    )
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
