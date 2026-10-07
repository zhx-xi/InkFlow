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
    self_only:         仅复制 root_setting_id 本体（不含子级）；需与 root_setting_id 同用.
    category（#1482）: 仅复制 src.category == category 的源条目；None = 不过滤.
    auto_create_categories（#1482）: 目标项目缺失源条目分类时自动创建（默认 False）；
                       True = 自动创建（opt-in，kind 继承源分类）.
    """

    source_project_id: uuid.UUID
    root_setting_id: uuid.UUID | None = None
    self_only: bool = False  # P1 新增：True = 仅复制 root_setting_id 本体（不含子级）
    category: str | None = None  # #1482：仅复制该分类下的条目；None = 不过滤
    auto_create_categories: bool = False  # #1482：目标缺失源分类时自动创建（opt-in）


class WorldCopyResult(BaseModel):
    """复制结果报告 — 镜像 F10 WorldExtractionResult 风格（created/skipped/warnings）.

    created:      复制到目标项目的世界观条目（新 id）.
    skipped:      目标项目同名冲突被跳过的源条目名.
    maps_created: 复制的地图（新 id + 新 image_path）.
    pins_created: 复制的 pin 数.
    warnings:     复制过程中的警告（冲突/文件复制失败/全局图 pin 转纯注释）.
    categories_created（#1482）: 因缺失而在目标项目自动创建的分类名（opt-in 时可能非空）.
    """

    created: list[WorldSetting]
    skipped: list[str]
    maps_created: list[WorldMap]
    pins_created: int
    warnings: list[str]
    categories_created: list[str]
