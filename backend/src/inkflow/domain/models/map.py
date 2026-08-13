"""F36 地图领域模型 — 对应 maps/map_pins 表（无 is_deleted——真删语义）.

依据: specs/f36-world-map/spec.md §2.3。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class WorldMap(BaseModel):
    """地图领域实体 — 对应 maps 表（无 is_deleted——真删语义）."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    image_path: str  # 相对 config.data_dir 的路径（如 maps/<uuid>/main.png）
    description: str = ""
    root_location_id: uuid.UUID | None = None
    bg_source: str = "image"  # F43 P2：枚举 shape/image/ai（默认 image，旧数据兼容）
    extra: dict = Field(default_factory=dict)  # F43 P2：扩展字典（{"shapes": [...]}）
    created_at: datetime
    updated_at: datetime


class WorldMapCreate(BaseModel):
    """创建地图请求 DTO — 图片文件走 multipart，不在 body."""

    project_id: uuid.UUID
    name: str
    description: str = ""
    root_location_id: uuid.UUID | None = None


class WorldMapUpdate(BaseModel):
    """更新地图元数据请求 DTO（不换图；换图走 PUT /maps/{id}/image）.

    root_location_id: None 表示不修改；出现且为 null = 改为全局图（与 F35 parent_id 同款
    exclude_unset 语义）.
    """

    name: str | None = None
    description: str | None = None
    root_location_id: uuid.UUID | None = None
    bg_source: str | None = None  # F43 P2：shape/image/ai（exclude_unset 语义）
    extra: dict | None = None  # F43 P2：shapes 整体替换（exclude_unset 语义）


class MapPin(BaseModel):
    """地图 pin 领域实体 — 对应 map_pins 表（无 is_deleted——真删语义）."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    map_id: uuid.UUID
    location_id: uuid.UUID | None = None
    type: str = "location"  # F43 P2：枚举 location/role/event/other（默认 location）
    ref_id: uuid.UUID | None = None  # F43 P2：type=role/event 关联实体主键
    x: float
    y: float
    label: str
    created_at: datetime
    updated_at: datetime


class MapPinCreate(BaseModel):
    """创建 pin 请求 DTO."""

    location_id: uuid.UUID | None = None
    ref_id: uuid.UUID | None = None  # F43 P2：type=role/event 用
    type: str = "location"  # F43 P2：location/role/event/other
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    label: str = ""


class MapPinUpdate(BaseModel):
    """更新 pin 请求 DTO — 全可选，exclude_unset 语义.

    location_id: None = 不修改；出现且为 null = 转为纯注释 pin.
    """

    location_id: uuid.UUID | None = None
    ref_id: uuid.UUID | None = None  # F43 P2：exclude_unset 语义
    type: str | None = None  # F43 P2：exclude_unset 语义
    x: float | None = None
    y: float | None = None
    label: str | None = None
