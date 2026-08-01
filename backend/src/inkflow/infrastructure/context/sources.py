"""上下文数据源实现 — 收集各数据源产出的 ContextItem.

Phase 1:
    - ProjectConfigOutlineSource: 从 project.config.extra["outline"] 读取大纲
    - CharacterSettingSource / WorldSettingSource: 空实现，
      机制与注入格式先行，待 F9/F10 落地后替换

Phase 2:
    - ForeshadowingSource: 已由 F13（伏笔管理）实现 — 注入未回收伏笔提醒
      （ADR-019 编号口径：F13=伏笔管理，F14=统一提取）

依据: specs/f6-context-service/spec.md §3.2 / §4.3,
      specs/f13-foreshadowing-service/spec.md §5.3, ADR-010, ADR-019.
"""

from __future__ import annotations

import uuid

from inkflow.domain.models.context import ContextItem, ContextSourceType
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
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
    """伏笔数据源 — 收集未回收（open）伏笔提醒（F13 真实实现）.

    Args:
        foreshadowing_repo: 伏笔仓储（list_open 查询 open 状态活动伏笔）.
    """

    def __init__(self, foreshadowing_repo: ForeshadowingRepositoryProtocol) -> None:
        self._repo = foreshadowing_repo

    async def collect(self, project_id: uuid.UUID, chapter_id: uuid.UUID) -> list[ContextItem]:
        """收集全部未回收伏笔的提醒条目.

        - 项目不存在/无 open 伏笔 → 空列表（跳过，不报错，同 F6 数据源惯例）
        - 项目存在但所有伏笔已回收/已软删除 → 空列表（正常路径）
        - chapter_id 参数 MVP 不使用（全量注入 open 伏笔，按章节过滤归 Phase 2+）
        """
        items = await self._repo.list_open(project_id.int)  # (priority DESC, updated_at DESC)
        return [
            ContextItem(
                source=ContextSourceType.FORESHADOWING,
                title=f"伏笔：{f.title}",
                content=_render_reminder(f),  # 确定性模板，无 LLM
                priority=f.priority,  # 透传伏笔优先级（F6 dynamic 层排序键）
                metadata={
                    "foreshadowing_id": str(f.id),
                    "status": f.status.value,
                    "location": f.location,
                    "event_id": str(f.event_id) if f.event_id else None,
                },
            )
            for f in items
        ]


def _render_reminder(f: Foreshadowing) -> str:
    """提醒文本确定性模板 — 纯函数，无 LLM（spec §5.3）.

    首段固定「未回收伏笔：{title}。」；description 非空时追加描述段；
    location 非空时追加埋设位置段。全部来自伏笔档案字段。

    Args:
        f: 伏笔领域实体.

    Returns:
        提醒文本（分段以换行连接）.
    """
    parts = [f"未回收伏笔：{f.title}。"]
    if f.description:
        parts.append(f.description)
    if f.location:
        parts.append(f"（埋设位置：{f.location}）")
    return "\n".join(parts)
