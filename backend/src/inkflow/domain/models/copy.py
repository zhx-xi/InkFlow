"""F37 跨书复制 DTO — 请求/报告模型（spec §2）."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from inkflow.domain.models.map import WorldMap
from inkflow.domain.models.world import WorldSetting


class WorldCopyRequest(BaseModel):
    """跨书复制请求 DTO.

    source_project_id: 源项目（世界观设定从哪来）.
    root_setting_id:   复制起点（指定子树）；None = 复制源项目全部活动世界观条目.
    """

    source_project_id: uuid.UUID
    root_setting_id: uuid.UUID | None = None


class WorldCopyResult(BaseModel):
    """复制结果报告 — 镜像 F10 WorldExtractionResult 风格（created/skipped/warnings）.

    created:      复制到目标项目的世界观条目（新 id）.
    skipped:      目标项目同名冲突被跳过的源条目名.
    maps_created: 复制的地图（新 id + 新 image_path）.
    pins_created: 复制的 pin 数.
    warnings:     复制过程中的警告（冲突/文件复制失败/全局图 pin 转纯注释）.
    """

    created: list[WorldSetting]
    skipped: list[str]
    maps_created: list[WorldMap]
    pins_created: int
    warnings: list[str]
