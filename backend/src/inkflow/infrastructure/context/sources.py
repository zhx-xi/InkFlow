"""上下文数据源实现 — 收集各数据源产出的 ContextItem.

Phase 1:
    - ProjectConfigOutlineSource: 从 project.config.extra["outline"] 读取大纲
    - CharacterSettingSource / WorldSettingSource / ForeshadowingSource: 空实现，
      机制与注入格式先行就位，待 F8/F9/F14 落地后替换

依据: specs/f6-context-service/spec.md §3.2 / §4.3, ADR-010.
"""

from __future__ import annotations

import uuid

from inkflow.domain.models.context import ContextItem, ContextSourceType
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol


class ProjectConfigOutlineSource:
    """大纲数据源 — 读取 project.config.extra["outline"].

    Args:
        project_repo: 项目仓储（get 接受 int 主键，域内 UUID 以 project_id.int 转换）.
    """

    def __init__(self, project_repo: ProjectRepositoryProtocol) -> None:
        self._project_repo = project_repo

    async def collect(self, project_id: uuid.UUID, chapter_id: uuid.UUID) -> list[ContextItem]:
        """收集大纲条目；项目不存在或大纲缺失/为空 → 空列表（跳过，不报错）."""
        project = await self._project_repo.get(project_id.int)
        if project is None:
            return []
        outline = project.config.extra.get("outline")
        if not outline:
            return []
        return [
            ContextItem(
                source=ContextSourceType.OUTLINE,
                title="大纲",
                content=outline,
            )
        ]


class CharacterSettingSource:
    """角色设定数据源 — Phase 1 空实现."""

    async def collect(self, project_id: uuid.UUID, chapter_id: uuid.UUID) -> list[ContextItem]:
        # TODO: Phase 2: F8 角色设定数据源
        return []


class WorldSettingSource:
    """世界设定数据源 — Phase 1 空实现."""

    async def collect(self, project_id: uuid.UUID, chapter_id: uuid.UUID) -> list[ContextItem]:
        # TODO: Phase 2: F9 世界设定数据源
        return []


class ForeshadowingSource:
    """伏笔管理数据源 — Phase 1 空实现."""

    async def collect(self, project_id: uuid.UUID, chapter_id: uuid.UUID) -> list[ContextItem]:
        # TODO: Phase 2: F14 伏笔管理数据源
        return []
