"""#848 跨书复制服务守卫 RED 契约测试.

锁定契约（当前实现 copy 直调 repo.add 绕过 create_setting 守卫 → 应 FAIL）:
1. 复制带 category 条目到无该分类目标 → 跳过 + warning（不落未建分类）
2. 复制顶层节点到已有根目标 → 跳过（不制造第二根）
3. 复制到无根 + 无冲突目标 → 成功（首个复制根）

依据: issue #848 + specs/f10-world-settings/spec.md §7（复制守卫行）+
specs/f37-world-copy/spec.md（复制语义）.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.copy_service import WorldCopyService

SOURCE_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TARGET_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
SOURCE_INT = SOURCE_PID.int
TARGET_INT = TARGET_PID.int
TS = datetime(2026, 8, 1, 10, 0, 0)


def _setting(
    name: str,
    *,
    project_id: uuid.UUID = SOURCE_PID,
    parent_id: uuid.UUID | None = None,
    category: str = "",
) -> object:
    """构造测试用世界观条目（惰性 import 领域模型；返回注解省略防 F821）. """
    from inkflow.domain.models.world import WorldSetting

    return WorldSetting(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        category=category,
        content="",
        extra={},
        parent_id=parent_id,
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock WorldRepositoryProtocol — 方法显式默认值（显式 AsyncMock 防假绿）. """
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda s: s)
    repo.list_all_active = AsyncMock(return_value=[])
    repo.list_descendants = AsyncMock(return_value=[])
    repo.get_by_parent_and_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))  # 默认目标无根
    repo.get_category_by_name = AsyncMock(return_value=None)  # 默认无该分类
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — 源/目标项目均存在. """
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(
        side_effect=lambda pid: SimpleNamespace(id=pid) if pid in (SOURCE_INT, TARGET_INT) else None
    )
    return repo


@pytest.fixture
def service(mock_repo: MagicMock, mock_project_repo: MagicMock) -> WorldCopyService:
    """被测 WorldCopyService 实例（无 map/asset → 跳过地图复制聚焦条目守卫）. """
    return WorldCopyService(
        repository=mock_repo,
        project_repo=mock_project_repo,
        map_repo=None,
        asset_store=None,
    )


class TestCopyGuard:
    """#848 复制守卫（copy 直调 repo.add 的旁路封堵）. """

    async def test_copy_category_entry_to_target_without_category_skipped(
        self, service: WorldCopyService, mock_repo: MagicMock
    ) -> None:
        """复制带 category 条目到无该分类目标 → 跳过 + warning（不落未建分类）.

        当前实现 FAIL：copy 直调 repo.add，带未建分类条目直接落库.
        """
        root = _setting("大陆")
        child = _setting("宗门", parent_id=root.id, category="设定")
        mock_repo.list_all_active = AsyncMock(return_value=[root, child])
        mock_repo.list = AsyncMock(return_value=([], 0))  # 目标无根
        mock_repo.get_category_by_name = AsyncMock(return_value=None)  # 「设定」分类未建
        result = await service.copy(SOURCE_PID, TARGET_PID)
        names = [s.name for s in result.created]
        assert "宗门" not in names  # 未落未建分类条目
        assert "宗门" in result.skipped
        assert any("设定" in w for w in result.warnings)
        # add 只被根调用，未再次为「宗门」调用（add 次数 = created 数）
        assert mock_repo.add.await_count == 1

    async def test_copy_top_level_to_target_with_root_skipped(
        self, service: WorldCopyService, mock_repo: MagicMock
    ) -> None:
        """复制顶层节点到已有根目标 → 跳过（不制造第二根）.

        当前实现 FAIL：copy 直调 repo.add，顶层节点落库成为第二个根.
        """
        src_root = _setting("天元大陆")
        existing_root = _setting("已有根", project_id=TARGET_PID)
        mock_repo.list_all_active = AsyncMock(return_value=[src_root])
        mock_repo.list = AsyncMock(return_value=([existing_root], 1))  # 目标已有根
        result = await service.copy(SOURCE_PID, TARGET_PID)
        assert result.created == []
        assert "天元大陆" in result.skipped
        assert any("根" in w for w in result.warnings)
        mock_repo.add.assert_not_awaited()

    async def test_copy_to_no_root_no_conflict_succeeds_as_first_root(
        self, service: WorldCopyService, mock_repo: MagicMock
    ) -> None:
        """复制到无根 + 无冲突目标 → 成功（首个复制根）.

        当前实现 PASS：无守卫，顶层节点落库成为目标根.
        """
        src_root = _setting("天元大陆")
        mock_repo.list_all_active = AsyncMock(return_value=[src_root])
        mock_repo.list = AsyncMock(return_value=([], 0))  # 目标无根
        result = await service.copy(SOURCE_PID, TARGET_PID)
        assert len(result.created) == 1
        assert result.created[0].name == "天元大陆"
        assert result.created[0].project_id == TARGET_PID
        assert result.created[0].parent_id is None  # 首个复制根置顶
        mock_repo.add.assert_awaited_once()
