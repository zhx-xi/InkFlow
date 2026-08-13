"""F43 P5 地图清理钩子契约 — clear_ref_pins + clear_location_pins 扩展（#284 最后一批）。

设计背景（spec §2.10/§5.18/§9.9）：
- 生产 SQLite foreign_keys=OFF → 删除角色/事件后 map_pins.ref_id(type=role/event) 残留；
  删除地点后 maps.root_location_id 残留（clear_location_pins 现只清 pin.location_id）。
- 本批 MapService 新增 clear_ref_pins（镜像 clear_location_pins 模式）+ clear_location_pins 扩展。

RED 预期：
- C5: clear_ref_pins 方法不存在 → 用例体调用 AttributeError FAIL
- C6: clear_location_pins 扩展未实现（repo.clear_location_pins 现只处理 pins）→ 断言 FAIL

镜像: tests/unit/test_map_service.py（service 层全 mock；fixture 显式默认值）。
测试文件拆分（900 行护栏）：test_map_service.py 已 830 行，P5 契约新拆本文件。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.map import MapPin
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.map_service import MapService

PID = uuid.UUID(int=7)


def _pin(*, pin_id: uuid.UUID | None = None, ref_id: uuid.UUID | None = None) -> MapPin:
    """构造测试用 MapPin（clear_ref_pins 只关心 ref_id 形态）。"""
    return MapPin(
        id=pin_id or uuid.uuid4(),
        location_id=None,
        type="role",
        ref_id=ref_id,
        x=10.0,
        y=20.0,
        label="测试 pin",
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock MapRepositoryProtocol — 显式默认值（裸 AsyncMock 陷阱防护）。"""
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
    """Mock MapAssetStoreProtocol."""
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
    """Mock WorldRepositoryProtocol."""
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def service(
    mock_repo: MagicMock,
    mock_asset_store: MagicMock,
    mock_world_repo: MagicMock,
) -> MapService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return MapService(
        repository=mock_repo,
        asset_store=mock_asset_store,
        world_repo=mock_world_repo,
    )


class TestClearRefPins:
    """C5: MapService.clear_ref_pins('role'|'event', ids) —— RED 预期 AttributeError FAIL."""

    async def test_clear_ref_pins_role_delegates_to_repo(self, service, mock_repo) -> None:
        """clear_ref_pins('role', ids) → repo 收到调用（透传 ref_type + int ids）。"""
        ids = [uuid.UUID(int=1), uuid.UUID(int=2)]
        await service.clear_ref_pins("role", ids)
        mock_repo.clear_ref_pins.assert_awaited_once_with("role", [1, 2])

    async def test_clear_ref_pins_event_delegates_to_repo(self, service, mock_repo) -> None:
        """clear_ref_pins('event', ids) → repo 收到调用。"""
        ids = [uuid.UUID(int=5)]
        await service.clear_ref_pins("event", ids)
        mock_repo.clear_ref_pins.assert_awaited_once_with("event", [5])


class TestClearLocationPinsExtended:
    """C6: clear_location_pins 扩展 maps.root_location_id —— RED 预期 FAIL."""

    async def test_clear_location_pins_also_clears_map_root_location(
        self, service, mock_repo
    ) -> None:
        """clear_location_pins 除 pin.location_id 外，maps.root_location_id 也置空。"""
        loc_ids = [uuid.UUID(int=11), uuid.UUID(int=12)]
        await service.clear_location_pins(loc_ids)
        mock_repo.clear_location_pins.assert_awaited()
        # 扩展：maps.root_location_id 清理（repo 新方法 clear_map_root_locations）
        mock_repo.clear_map_root_locations.assert_awaited_once_with([11, 12])
