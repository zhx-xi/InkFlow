"""#708 coverage 补测 — world_service.get_root_setting 未覆盖分支。

单独文件存放：test_world_service.py 已达 900 行上限（check_file_length 门禁），
新增用例按既有 gaps 文件先例（test_agent_service_coverage.py 等）落新文件。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.world_service import WorldService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _setting(name: str) -> WorldSetting:
    """构造测试用世界观条目实体（固定时间戳）。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        category="",
        content="",
        parent_id=None,
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def service() -> WorldService:
    """被测服务实例（全 mock 依赖注入，extractor/project_repo 占位）。"""
    return WorldService(
        repository=MagicMock(spec=WorldRepositoryProtocol),
        extractor=AsyncMock(),
        project_repo=AsyncMock(),
    )


async def test_get_root_setting_returns_first_root(service) -> None:
    """有根条目 → 返回 roots[0]（L224-225 主路径）。"""
    repo = service._repo
    root = _setting(name="大越国")
    repo.list = AsyncMock(return_value=([root], 1))

    result = await service.get_root_setting(PID)

    assert result is root
    repo.list.assert_awaited_once_with(PID.int, top_level_only=True, limit=1)


async def test_get_root_setting_none_when_no_root(service) -> None:
    """无根条目 → None（L225 反分支）。"""
    repo = service._repo
    repo.list = AsyncMock(return_value=([], 0))

    result = await service.get_root_setting(PID)

    assert result is None
