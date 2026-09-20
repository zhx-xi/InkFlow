"""#1321 世界观分类条件必填 — service 层 + 提取管线豁免 RED/GREEN 契约.

批 2 的真实验证点：条件校验落在 `WorldService.create_setting`（唯一真相源），
使 agent 工具 / CLI / MCP 直调路径全部一致生效。

GREEN 契约:
- 非根条目（parent_id 非空）+ category="" → WorldCategoryMissingError（422）
- 根条目（parent_id 空）+ category="" → 正常建根（#722 守护）
- 提取管线（_world_extractor 直调 repo.add）绕过本方法 → 天然豁免（D5b）

RED 预期：实现前 test_non_root_missing_category_raises FAIL（直接走 add）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.world_errors import WorldCategoryMissingError
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.world_service import WorldService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
ROOT_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000000f0")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _setting(name: str, *, parent_id=None) -> WorldSetting:
    return WorldSetting(
        id=ROOT_ID if parent_id is None else uuid.uuid4(),
        project_id=PID,
        name=name,
        category="",
        content="",
        parent_id=parent_id,
        created_at=TS,
        updated_at=TS,
    )


def _svc(*, has_root: bool) -> tuple[WorldService, MagicMock]:
    """构造 Mock Repository：has_root 控制项目是否已有根."""
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=_setting("青州"))
    repo.add = AsyncMock(side_effect=lambda s: s)
    repo.list = AsyncMock(return_value=([_setting("世界观")], 1) if has_root else ([], 0))
    repo.get_by_name = AsyncMock(return_value=None)
    repo.get_by_parent_and_name = AsyncMock(return_value=None)
    repo.get_category_by_name = AsyncMock(return_value=None)
    return WorldService(repository=repo), repo


class TestCreateConditionalRequiredService:
    """service 层创建侧条件必填."""

    @pytest.mark.asyncio
    async def test_non_root_missing_category_raises(self) -> None:
        """非根条目（有父）+ category="" → WorldCategoryMissingError（#1321 核心断言）."""
        parent = _setting("青州")
        svc, repo = _svc(has_root=True)
        repo.get = AsyncMock(return_value=parent)

        with pytest.raises(WorldCategoryMissingError):
            await svc.create_setting(PID, "清河县城", category="", parent_id=parent.id)
        repo.add.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_root_with_category_ok(self) -> None:
        """非根条目 + 非空且存在的分类 → 正常创建."""
        parent = _setting("青州")
        svc, repo = _svc(has_root=True)
        repo.get = AsyncMock(return_value=parent)
        repo.get_category_by_name = AsyncMock(return_value=MagicMock())

        created = await svc.create_setting(PID, "清河县城", category="地理", parent_id=parent.id)
        assert created.category == "地理"

    @pytest.mark.asyncio
    async def test_root_without_category_ok(self) -> None:
        """*722 守护*：根条目（无父）+ category="" → 正常建根，不得抛."""
        svc, repo = _svc(has_root=False)

        created = await svc.create_setting(PID, "世界观", category="")
        assert created.parent_id is None
        repo.add.assert_awaited_once()
