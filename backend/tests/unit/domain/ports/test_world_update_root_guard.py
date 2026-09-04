"""#847 更新设置根守卫 RED 契约测试.

锁定契约（当前实现 update_setting 无根校验 → 应 FAIL）:
1. 把非根条目置顶（parent_id→null）且项目已有根 → 拒绝（WorldRootConflictError，防第二根）
2. 把唯一根改挂他父 → 拒绝（WorldRootMissingError，防无根）
3. 正常改挂（保持唯一根）→ 成功（防过度拒绝）

依据: issue #847 + specs/f10-world-settings/spec.md §7（更新守卫行）+
specs/f35-world-tree/spec.md §2.1 规则 6（根世界单例）.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.world import WorldSetting, WorldUpdate
from inkflow.domain.ports.world_errors import (
    WorldRootConflictError,
    WorldRootMissingError,
)
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.world_service import WorldService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
OTHER_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _setting(
    name: str,
    *,
    project_id: uuid.UUID = PID,
    parent_id: uuid.UUID | None = None,
) -> WorldSetting:
    """构造测试用世界观条目实体（固定时间戳，parent_id 可置顶/置子）. """
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        category="",
        content="",
        parent_id=parent_id,
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock WorldRepositoryProtocol — 默认无根、无父、无冲突（显式 AsyncMock 防假绿）. """
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))  # 默认无根
    repo.get_by_parent_and_name = AsyncMock(return_value=None)
    repo.collect_ancestor_ids = AsyncMock(return_value=[])
    repo.update = AsyncMock(side_effect=lambda s: s)
    return repo


@pytest.fixture
def service(mock_repo: MagicMock) -> WorldService:
    """被测服务实例（全 Mock 依赖注入）. """
    return WorldService(repository=mock_repo)


class TestUpdateRootGuard:
    """#847 更新设置根守卫（update_setting 无根校验的旁路封堵）. """

    async def test_update_non_root_to_top_when_root_exists_raises_conflict(
        self, service: WorldService, mock_repo: MagicMock
    ) -> None:
        """把非根条目置顶（parent_id→null）且项目已有根 → 拒绝（防第二根）.

        当前实现 FAIL：update_setting 无根守卫，直接置顶成为第二个根条目.
        """
        root = _setting("大陆")
        child = _setting("宗门", parent_id=root.id)
        mock_repo.get = AsyncMock(return_value=child)
        mock_repo.list = AsyncMock(return_value=([root], 1))  # 项目已有根
        with pytest.raises(WorldRootConflictError):
            await service.update_setting(child.id, WorldUpdate(parent_id=None))
        mock_repo.update.assert_not_awaited()

    async def test_update_only_root_to_child_raises_root_missing(
        self, service: WorldService, mock_repo: MagicMock
    ) -> None:
        """把唯一根改挂他父 → 拒绝（防无根）.

        当前实现 FAIL：update_setting 无根守卫，根改挂后项目无根.
        """
        root = _setting("大陆")
        target = _setting("概念区")
        by_int = {root.id.int: root, target.id.int: target}
        mock_repo.get = AsyncMock(side_effect=lambda sid: by_int.get(sid))
        mock_repo.list = AsyncMock(return_value=([root], 1))  # 唯一根
        with pytest.raises(WorldRootMissingError):
            await service.update_setting(root.id, WorldUpdate(parent_id=target.id))
        mock_repo.update.assert_not_awaited()

    async def test_update_non_root_reparent_keeps_single_root_succeeds(
        self, service: WorldService, mock_repo: MagicMock
    ) -> None:
        """正常改挂（保持唯一根）→ 成功（防过度拒绝）.

        当前实现 PASS：无根守卫，改挂后根仍唯一.
        """
        root = _setting("大陆")
        child_a = _setting("宗门A", parent_id=root.id)
        child_b = _setting("宗门B", parent_id=root.id)
        by_int = {root.id.int: root, child_a.id.int: child_a, child_b.id.int: child_b}
        mock_repo.get = AsyncMock(side_effect=lambda sid: by_int.get(sid))
        mock_repo.collect_ancestor_ids = AsyncMock(return_value=[root.id.int])
        mock_repo.get_by_parent_and_name = AsyncMock(return_value=None)
        updated = await service.update_setting(child_a.id, WorldUpdate(parent_id=child_b.id))
        assert updated.parent_id == child_b.id
        assert child_a.parent_id == root.id  # 原树结构未变
