"""#1481 `WorldService.ensure_root_setting` — 幂等「根必存在」原语（Mock Repository）.

自 `test_world_service.py` 拆出（900 行护栏，specs/f35-world-tree §5.7）。

覆盖:
- 无根项目 → 建默认根（name/parent_id/category/content 形态 + 「根不触发分类校验」）
- 已有根 → 原样返回既有根，不建第二根（幂等）
- 项目不存在 → ProjectNotFoundError 透传（create_setting 前置校验）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.project import Project
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_errors import ProjectNotFoundError
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.world_service import WorldService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _setting(name: str) -> WorldSetting:
    """构造测试用世界观条目实体（固定时间戳）."""
    return WorldSetting(id=uuid.uuid4(), project_id=PID, name=name, created_at=TS, updated_at=TS)


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock WorldRepositoryProtocol — 默认「无根、无同名」（新建路径）."""
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.get_by_parent_and_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.add = AsyncMock(side_effect=lambda s: s)
    return repo


@pytest.fixture
def service(mock_repo: MagicMock) -> WorldService:
    """被测服务实例（全 Mock 依赖注入；project_repo.get 默认项目存在）."""
    project_repo = MagicMock(spec=ProjectRepositoryProtocol)
    project_repo.get = AsyncMock(
        return_value=Project(id=PID, name="p", created_at=TS, updated_at=TS)
    )
    return WorldService(repository=mock_repo, project_repo=project_repo)


class TestEnsureRootSetting:
    """`ensure_root_setting` 契约（#1481；建项目自动建根的注入目标）."""

    async def test_creates_default_root_when_missing(self, service, mock_repo) -> None:
        """无根项目 → 建默认根（name=世界观总纲 / parent_id=None / category=''）.

        「根条目本身不得触发分类校验」：根以**空分类**创建 ⇒ #1321（非根必填分类）与
        #834（带 category 须先建分类）两条前置均不适用——本用例即该实现坑的守护。
        """
        from inkflow.domain.models.world import DEFAULT_WORLD_ROOT_NAME

        mock_repo.list = AsyncMock(return_value=([], 0))

        created = await service.ensure_root_setting(PID)

        assert DEFAULT_WORLD_ROOT_NAME == "世界观总纲"
        assert created.name == "世界观总纲"
        assert created.parent_id is None
        assert created.category == ""
        assert created.content == ""
        assert created.project_id == PID
        mock_repo.add.assert_awaited_once()

    async def test_returns_existing_root_without_creating_second(self, service, mock_repo) -> None:
        """已有根项目 → 原样返回既有根，不建第二根（幂等，不撞 WorldRootConflictError）."""
        existing = _setting(name="既有根")
        mock_repo.list = AsyncMock(return_value=([existing], 1))

        result = await service.ensure_root_setting(PID)

        assert result is existing
        mock_repo.add.assert_not_awaited()

    async def test_project_missing_raises_not_found(self, mock_repo) -> None:
        """项目不存在 → ProjectNotFoundError 透传（create_setting #1138 前置校验）."""
        project_repo = MagicMock(spec=ProjectRepositoryProtocol)
        project_repo.get = AsyncMock(return_value=None)
        svc = WorldService(repository=mock_repo, project_repo=project_repo)

        with pytest.raises(ProjectNotFoundError):
            await svc.ensure_root_setting(PID)

        mock_repo.add.assert_not_awaited()
