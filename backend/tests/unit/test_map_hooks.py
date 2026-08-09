"""F36 服务钩子接线测试 — WorldService.location_cleanup / ProjectService.map_cleanup 调用契约.

拆分原因: test_map_service.py 原 908 行 > 900 行护栏（F24 教训）——TestF36ServiceHooks
独立成文件。fixtures/helpers 复制自 test_map_service.py（mock_repo/mock_asset_store/
mock_world_repo/mock_project_repo/_map/_pin/_setting/_project），保持同构。

覆盖（spec §5.4 D10=b + 父侧定稿接线契约 2026-08-09）:
- WorldService.delete_setting cascade 分支 → location_cleanup(子树全部 int ids)
- WorldService.delete_setting force 分支 → location_cleanup([sid])；软删不调用
- ProjectService.hard_delete 成功 → map_cleanup(pid_int)；失败不调用
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.map import MapPin
from inkflow.domain.models.project import Project
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.project_service import ProjectService
from inkflow.domain.services.world_service import WorldService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _map(name: str = "清河县城图", **kw) -> MapPin:
    """构造测试用地图实体（固定时间戳，便于断言）."""
    values = dict(
        id=uuid.uuid4(),
        project_id=PID,
        name=name,
        image_path="maps/abc/main.png",
        description="",
        root_location_id=None,
        created_at=TS,
        updated_at=TS,
    )
    values.update(kw)
    return MapPin(**values)


def _setting(name: str, *, project_id: uuid.UUID = PID) -> WorldSetting:
    """构造测试用世界观地点条目."""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        category="",
        content="",
        is_deleted=False,
        parent_id=None,
        created_at=TS,
        updated_at=TS,
    )


def _project(*, project_id: uuid.UUID = PID) -> Project:
    """构造测试用项目实体."""
    return Project(id=project_id, name="测试项目", created_at=TS, updated_at=TS)


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock WorldRepositoryProtocol（接线用例用）."""
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_descendants = AsyncMock(return_value=[])
    repo.hard_delete_many = AsyncMock(return_value=0)
    repo.hard_delete = AsyncMock(return_value=True)
    repo.soft_delete = AsyncMock(return_value=True)
    return repo


class TestF36ServiceHooks:
    """接线契约 — F36 在 F35/F1 既有 service 上加可选回调（GREEN 批实现）。

    既有模块 import 放用例体惰性（RED 阶段顶部 import 待实现 map 模块已使全文件收集失败，
    分离便于分阶段 GREEN）。RED（实现缺失时）: WorldService/ProjectService 构造无新参数 →
    TypeError.
    """

    async def test_world_service_location_cleanup_cascade(self) -> None:
        """WorldService(location_cleanup=cb): cascade 分支（hard_delete_many 之后）→
        await cb(子树全部 int ids)。  # F36
        """

        setting = _setting(name="青州")
        child = _setting(name="清河县城")
        grandchild = _setting(name="清河县城分县")
        mock_repo = MagicMock(spec=WorldRepositoryProtocol)
        mock_repo.get = AsyncMock(return_value=setting)
        mock_repo.list = AsyncMock(return_value=([child], 1))
        mock_repo.list_descendants = AsyncMock(return_value=[setting, child, grandchild])
        mock_repo.hard_delete_many = AsyncMock(return_value=3)
        mock_cb = AsyncMock()
        svc = WorldService(repository=mock_repo, location_cleanup=mock_cb)
        assert await svc.delete_setting(setting.id, cascade=True) is True
        mock_cb.assert_awaited_once_with([setting.id.int, child.id.int, grandchild.id.int])
        mock_repo.hard_delete_many.assert_awaited_once()

    async def test_world_service_location_cleanup_force(self) -> None:
        """force 分支（hard_delete 之后）→ await cb([sid])；软删（无参）→ cb 不调用。  # F36"""

        setting = _setting(name="清河县城")
        mock_repo = MagicMock(spec=WorldRepositoryProtocol)
        mock_repo.get = AsyncMock(return_value=setting)
        mock_repo.list = AsyncMock(return_value=([], 0))
        mock_repo.hard_delete = AsyncMock(return_value=True)
        mock_repo.soft_delete = AsyncMock(return_value=True)
        mock_cb = AsyncMock()
        svc = WorldService(repository=mock_repo, location_cleanup=mock_cb)
        assert await svc.delete_setting(setting.id, force=True) is True
        mock_cb.assert_awaited_once_with([setting.id.int])

        mock_cb.reset_mock()
        assert await svc.delete_setting(setting.id) is True  # 软删分支
        mock_cb.assert_not_awaited()

    async def test_project_service_map_cleanup(self) -> None:
        """ProjectService(map_cleanup=cb): hard_delete 成功（True）→ await cb(pid.int)；
        hard_delete 返回 False → 不调用。  # F36（异常 log warning 不阻断属实现侧，测试只断言调用）
        """

        with mock.patch(
            "inkflow.domain.services.project_service.SQLiteProjectRepository"
        ) as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.hard_delete = AsyncMock(return_value=True)
            mock_cb = AsyncMock()
            svc = ProjectService(db_session=object(), map_cleanup=mock_cb)
            assert await svc.hard_delete(PID) is True
            mock_cb.assert_awaited_once_with(PID.int)
            mock_repo.hard_delete = AsyncMock(return_value=False)
            mock_cb.reset_mock()
            assert await svc.hard_delete(PID) is False
            mock_cb.assert_not_awaited()
