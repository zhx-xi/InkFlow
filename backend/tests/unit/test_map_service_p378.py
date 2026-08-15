"""F36 地图服务层 #378 单元测试 — parent_map_id 改挂（PATCH 拖拽调层级）。

拆分原因: test_map_service.py 追加 #378 用例后 948 行超 900 行护栏（check_file_length），
#378 用例独立文件（先例: test_extractions_rag_errors.py）。

设计契约（specs/f36-world-map/spec.md v1.4 §5.4 update_map ④'）:
- update_map parent_map_id 出现且非 None → 父图存在/同项目（MapParentMapNotFoundError）
  + 循环校验（目标 = 自身或自身子孙 → MapParentCycleError）；出现且 null → 变根图
- 合并: parent_map_id=null 保留（变根图），与 root_location_id null 同款 exclude_unset 语义
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.map import WorldMap, WorldMapUpdate
from inkflow.domain.ports.map_errors import MapParentMapNotFoundError, MapServiceError
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.map_service import MapService

try:  # pragma: no cover - #378 RED: MapParentCycleError 尚未实现
    from inkflow.domain.ports.map_errors import MapParentCycleError
except ImportError:
    MapParentCycleError = type("MapParentCycleError", (MapServiceError,), {})

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _map(
    name: str = "清河县城图",
    *,
    project_id: uuid.UUID = PID,
    description: str = "",
    image_path: str = "maps/abc123/main.png",
    root_location_id: uuid.UUID | None = None,
    parent_map_id: uuid.UUID | None = None,  # v1.4 #378：图挂父图
) -> WorldMap:
    """构造测试用地图实体（固定时间戳，便于断言）。"""
    return WorldMap(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        image_path=image_path,
        description=description,
        root_location_id=root_location_id,
        parent_map_id=parent_map_id,
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock MapRepositoryProtocol — 方法显式默认值（裸 AsyncMock 陷阱防护）。"""
    repo = MagicMock(spec=MapRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.children = AsyncMock(return_value=[])
    repo.add = AsyncMock(side_effect=lambda m: m)
    repo.update = AsyncMock(side_effect=lambda m: m)
    repo.delete = AsyncMock(return_value=True)
    repo.delete_many = AsyncMock(return_value=0)
    repo.list_pins = AsyncMock(return_value=[])
    repo.add_pin = AsyncMock(side_effect=lambda p: p)
    repo.update_pin = AsyncMock(side_effect=lambda p: p)
    repo.delete_pin = AsyncMock(return_value=True)
    repo.list_maps_by_project = AsyncMock(return_value=[])
    repo.delete_by_project = AsyncMock(return_value=0)
    repo.clear_location_pins = AsyncMock(return_value=0)
    repo.list_by_root_locations = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_asset_store() -> MagicMock:
    """Mock MapAssetStoreProtocol — save 返回动态相对路径（按 map_id）。"""
    store = MagicMock()
    store.save = AsyncMock(
        side_effect=lambda *, map_id, filename, content: f"maps/{map_id}/main.png"
    )
    store.delete = AsyncMock(return_value=None)
    store.copy = AsyncMock(return_value="maps/copied/main.png")
    store.resolve = MagicMock(return_value=__import__("pathlib").Path("C:/data/maps/abc/main.png"))
    return store


@pytest.fixture
def mock_world_repo() -> MagicMock:
    """Mock WorldRepositoryProtocol — location 校验（get 默认 None = 地点不存在）。"""
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — 项目存在性校验（get 默认 None = 项目不存在）。"""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def service(
    mock_repo: MagicMock,
    mock_asset_store: MagicMock,
    mock_world_repo: MagicMock,
    mock_project_repo: MagicMock,
) -> MapService:
    """被测 MapService 实例（全 Mock 依赖注入）。"""
    return MapService(
        repository=mock_repo,
        asset_store=mock_asset_store,
        world_repo=mock_world_repo,
        project_repo=mock_project_repo,
    )


class TestUpdateMapParentMap:
    """update_map parent_map_id 改挂（v1.4 #378，spec §5.4 ④'）。"""

    async def test_update_parent_map_rehang_success(self, service, mock_repo) -> None:
        """v1.4 #378: 改挂成功——existing 挂 A → 改挂 B（repo.get 首=existing 次=父图 B）."""
        parent_a = uuid.uuid4()
        existing = _map(name="中州分图", parent_map_id=parent_a)
        parent_b = _map(name="南疆总图")
        mock_repo.get = AsyncMock(side_effect=[existing, parent_b])
        mock_repo.get_by_name = AsyncMock(return_value=None)
        mock_repo.list = AsyncMock(return_value=([existing, parent_b], 2))  # 循环校验全量
        result = await service.update_map(existing.id, WorldMapUpdate(parent_map_id=parent_b.id))
        merged = mock_repo.update.await_args.args[0]
        assert merged.parent_map_id == parent_b.id
        assert result is merged

    async def test_update_parent_map_to_root(self, service, mock_repo) -> None:
        """v1.4 #378: parent_map_id=null → 变根图（merged.parent_map_id=None；不查父图）."""
        existing = _map(name="中州分图", parent_map_id=uuid.uuid4())
        mock_repo.get = AsyncMock(return_value=existing)  # 只调一次（null 不查父图）
        mock_repo.get_by_name = AsyncMock(return_value=None)
        result = await service.update_map(existing.id, WorldMapUpdate(parent_map_id=None))
        merged = mock_repo.update.await_args.args[0]
        assert merged.parent_map_id is None
        assert result is merged

    async def test_update_parent_map_not_found_raises(self, service, mock_repo) -> None:
        """v1.4 #378: 父图不存在/跨项目 → MapParentMapNotFoundError；update 不调用."""
        existing = _map(name="中州分图", parent_map_id=uuid.uuid4())
        mock_repo.get = AsyncMock(side_effect=[existing, None])  # 二次 = 父图不存在
        mock_repo.get_by_name = AsyncMock(return_value=None)
        with pytest.raises(MapParentMapNotFoundError):
            await service.update_map(existing.id, WorldMapUpdate(parent_map_id=uuid.uuid4()))
        mock_repo.update.assert_not_awaited()

    async def test_update_parent_map_cycle_self_raises(self, service, mock_repo) -> None:
        """v1.4 #378: 目标 = 自身 → MapParentCycleError（循环拒绝，防成环）."""
        existing = _map(name="中州分图", parent_map_id=uuid.uuid4())
        mock_repo.get = AsyncMock(side_effect=[existing, existing])  # 父图存在但 = 自身
        mock_repo.get_by_name = AsyncMock(return_value=None)
        mock_repo.list = AsyncMock(return_value=([existing], 1))
        with pytest.raises(MapParentCycleError):
            await service.update_map(existing.id, WorldMapUpdate(parent_map_id=existing.id))
        mock_repo.update.assert_not_awaited()

    async def test_update_parent_map_cycle_descendant_raises(self, service, mock_repo) -> None:
        """v1.4 #378: 目标 = 自身子孙 → MapParentCycleError（BFS 收集子孙命中）."""
        existing = _map(name="中州分图", parent_map_id=uuid.uuid4())
        child = _map(name="中州细图", parent_map_id=existing.id)
        grandchild = _map(name="细图孙", parent_map_id=child.id)
        mock_repo.get = AsyncMock(side_effect=[existing, grandchild])  # 父图 = existing 的孙
        mock_repo.get_by_name = AsyncMock(return_value=None)
        mock_repo.list = AsyncMock(return_value=([existing, child, grandchild], 3))  # 全量 BFS
        with pytest.raises(MapParentCycleError):
            await service.update_map(existing.id, WorldMapUpdate(parent_map_id=grandchild.id))
        mock_repo.update.assert_not_awaited()
