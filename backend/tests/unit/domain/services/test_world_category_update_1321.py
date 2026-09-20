"""#1321 世界观分类条件必填 + 更新侧存在性校验 — service 层 RED 契约.

批 1 的**真实验证点**在 service（router 测试全 mock service，无法证伪校验本体）。
本文件用 Mock Repository 直测 `WorldService.update_setting` 的分类存在性校验：

GREEN 契约:
- `"category" in update.model_fields_set` 且值非空 → 调 `repo.get_category_by_name`；
  返回 None → `WorldCategoryMissingError`（422）
- 值非空且分类存在 → 正常更新（不抛）
- 值 == ""（清空）→ **不查存在性**、不抛（冻结语义）
- 未传 category（不在 fields_set）→ 不查存在性、不抛

RED 预期：实现前全部负向用例 FAIL（校验缺失 → 直接走 update）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.world import WorldSetting, WorldUpdate
from inkflow.domain.ports.world_errors import WorldCategoryMissingError
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.world_service import WorldService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
SID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000051")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _setting(name: str = "子地点", *, category: str = "旧分类", parent_id=None) -> WorldSetting:
    """构造测试用条目实体（默认非根、带旧分类）."""
    return WorldSetting(
        id=SID,
        project_id=PID,
        name=name,
        category=category,
        content="",
        parent_id=parent_id or uuid.uuid4(),
        created_at=TS,
        updated_at=TS,
    )


def _svc(existing: WorldSetting) -> tuple[WorldService, MagicMock]:
    """构造 Mock Repository 注入的 WorldService（复用 test_world_service 同款注入）."""
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=existing)
    repo.update = AsyncMock(side_effect=lambda s: s)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.get_by_parent_and_name = AsyncMock(return_value=None)
    repo.get_category_by_name = AsyncMock(return_value=None)
    return WorldService(repository=repo), repo


class TestUpdateCategoryExistenceService:
    """service 层更新侧分类存在性校验."""

    @pytest.mark.asyncio
    async def test_unknown_category_raises(self) -> None:
        """PATCH category="不存在"（分类表中无）→ WorldCategoryMissingError."""
        svc, repo = _svc(_setting())
        repo.get_category_by_name = AsyncMock(return_value=None)

        with pytest.raises(WorldCategoryMissingError):
            await svc.update_setting(SID, WorldUpdate(category="不存在"))

    @pytest.mark.asyncio
    async def test_existing_category_ok(self) -> None:
        """PATCH category="已有分类"（分类表命中）→ 正常更新，不抛."""
        svc, repo = _svc(_setting())
        repo.get_category_by_name = AsyncMock(return_value=MagicMock())

        updated = await svc.update_setting(SID, WorldUpdate(category="已有分类"))
        assert updated is not None
        assert updated.category == "已有分类"

    @pytest.mark.asyncio
    async def test_clear_category_skips_existence(self) -> None:
        """PATCH category=""（清空）→ 不查存在性、不抛（冻结语义守护）."""
        svc, repo = _svc(_setting())
        repo.get_category_by_name = AsyncMock(side_effect=AssertionError("不应查存在性"))

        updated = await svc.update_setting(SID, WorldUpdate(category=""))
        assert updated is not None
        assert updated.category == ""

    @pytest.mark.asyncio
    async def test_absent_category_skips_existence(self) -> None:
        """未传 category（不在 model_fields_set）→ 不查存在性、不抛."""
        svc, repo = _svc(_setting())
        repo.get_category_by_name = AsyncMock(side_effect=AssertionError("不应查存在性"))

        updated = await svc.update_setting(SID, WorldUpdate(content="改了正文"))
        assert updated is not None
        assert updated.category == "旧分类"
