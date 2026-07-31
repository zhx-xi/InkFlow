"""上下文数据源测试 — ProjectConfigOutlineSource + Phase 1 空实现.

测试范围 (spec §3.2 / §4.3):
    - 大纲数据源: project.config.extra["outline"] 存在 / 缺失
    - 角色 / 世界 / 伏笔数据源: Phase 1 返回空列表（F8/F9/F14 落地后替换）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from inkflow.domain.models.context import ContextItem, ContextSourceType
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.infrastructure.context.sources import (
    CharacterSettingSource,
    ForeshadowingSource,
    ProjectConfigOutlineSource,
    WorldSettingSource,
)


def _make_project(outline: str | None = None) -> Project:
    """构造测试用 Project — extra 仅在 outline 非 None 时含 outline 键."""
    extra: dict = {}
    if outline is not None:
        extra["outline"] = outline
    return Project(
        id=uuid.UUID(int=1),
        name="测试项目",
        config=ProjectConfig(extra=extra),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestProjectConfigOutlineSource:
    """大纲数据源 — 从 project.config.extra["outline"] 读取."""

    async def test_returns_outline_when_extra_has_outline(self) -> None:
        """extra 含 outline 时返回对应 ContextItem."""
        project = _make_project(outline="第一卷：开局")
        repo = AsyncMock()
        repo.get.return_value = project
        source = ProjectConfigOutlineSource(repo)

        items = await source.collect(uuid.UUID(int=1), uuid.UUID(int=2))

        assert len(items) == 1
        item = items[0]
        assert isinstance(item, ContextItem)
        assert item.source == ContextSourceType.OUTLINE
        assert item.title == "大纲"
        assert item.content == "第一卷：开局"
        # UUID → int 主键转换，按真实仓储契约调用
        repo.get.assert_awaited_once_with(1)

    async def test_returns_empty_when_extra_has_no_outline(self) -> None:
        """extra 无 outline 键时返回空列表（缺失 → 跳过，不报错）."""
        project = _make_project()
        repo = AsyncMock()
        repo.get.return_value = project
        source = ProjectConfigOutlineSource(repo)

        items = await source.collect(uuid.UUID(int=1), uuid.UUID(int=2))

        assert items == []


class TestPhase1EmptySources:
    """Phase 1 空实现 — 返回空列表，机制与注入格式先行."""

    async def test_character_setting_returns_empty(self) -> None:
        """角色设定数据源返回空列表（F8 Phase 2 落地）."""
        source = CharacterSettingSource()

        items = await source.collect(uuid.UUID(int=1), uuid.UUID(int=2))

        assert items == []

    async def test_world_setting_returns_empty(self) -> None:
        """世界设定数据源返回空列表（F9 Phase 2 落地）."""
        source = WorldSettingSource()

        items = await source.collect(uuid.UUID(int=1), uuid.UUID(int=2))

        assert items == []

    async def test_foreshadowing_returns_empty(self) -> None:
        """伏笔管理数据源返回空列表（F14 Phase 2 落地）."""
        source = ForeshadowingSource()

        items = await source.collect(uuid.UUID(int=1), uuid.UUID(int=2))

        assert items == []
