"""MapService 数据面变更事件测试（#1088 批 A3；spec §15.3.2/§15.3.3）。

自 test_map_service.py 拆出（守 900 行护栏，同 #281 测试文件规模治理先例）：
map（项目域：create 取形参 / update·delete 取已加载实体）与 map_pin
（create 从已加载 map 推 project_id；pin 自身无 project_id → update/delete
薄透传发 None + warning，spec §15.3.2 已知例外）。

依赖全 Mock 注入（镜像 test_map_service.py 的 fixture 形态）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.map import MapPin, MapPinUpdate, WorldMap, WorldMapUpdate
from inkflow.domain.models.project import Project
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.map_errors import MapNotFoundError
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_errors import ProjectNotFoundError
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.map_service import MapService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
IMG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _map(
    name: str = "清河县城图",
    *,
    project_id: uuid.UUID = PID,
    description: str = "",
    image_path: str = "maps/abc123/main.png",
    root_location_id: uuid.UUID | None = None,
) -> WorldMap:
    """构造测试用地图实体（固定时间戳，便于断言）。"""
    return WorldMap(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        image_path=image_path,
        description=description,
        root_location_id=root_location_id,
        created_at=TS,
        updated_at=TS,
    )


def _pin(
    *,
    map_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
) -> MapPin:
    """构造测试用 pin 实体（固定时间戳，便于断言）。"""
    return MapPin(
        id=uuid.uuid4(),
        map_id=map_id or uuid.uuid4(),
        location_id=location_id,
        x=50.0,
        y=50.0,
        label="清河县城",
        created_at=TS,
        updated_at=TS,
    )


def _setting(name: str, *, project_id: uuid.UUID = PID) -> WorldSetting:
    """构造测试用世界观地点条目（location 校验 mock 返回）。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        category="",
        content="",
        is_deleted=False,
        created_at=TS,
        updated_at=TS,
    )


def _project(*, project_id: uuid.UUID = PID) -> Project:
    """构造测试用项目实体（create_map 项目存在性校验）。"""
    return Project(id=project_id, name="测试项目", created_at=TS, updated_at=TS)


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock MapRepositoryProtocol — 全部方法显式默认值（裸 AsyncMock 陷阱防护）。"""
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
    repo.get_pin = AsyncMock(return_value=None)
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
    store.resolve = MagicMock(return_value=Path("C:/data/maps/abc/main.png"))
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


class TestDataChangeEvents:
    """#1088 批 A3：写路径成功 → 发布一条变更事件（spec §15.3.2/§15.3.3）。"""

    async def test_create_map_publishes_create_with_form_project_id(
        self, service, mock_repo, mock_project_repo, recorded_events
    ) -> None:
        """A 类：create_map 成功 → map/create，project_id 取形参。"""
        mock_project_repo.get = AsyncMock(return_value=_project())

        created = await service.create_map(PID, "清河县城图", "", None, "main.png", IMG)

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("map", "create")
        assert event.resource_id == str(created.id)
        assert event.project_id == str(PID)

    async def test_create_map_failure_publishes_nothing(self, service, recorded_events) -> None:
        """反例：项目不存在（写失败）→ 不发布（§15.3.3 不变量 1）。"""
        with pytest.raises(ProjectNotFoundError):
            await service.create_map(PID, "清河县城图", "", None, "main.png", IMG)

        assert recorded_events == []

    async def test_update_map_publishes_update_with_loaded_entity_project_id(
        self, service, mock_repo, recorded_events
    ) -> None:
        """B 类：update_map 成功 → map/update，project_id 从已加载实体解析（非 None）。"""
        existing = _map(name="旧名")
        mock_repo.get = AsyncMock(return_value=existing)

        updated = await service.update_map(existing.id, WorldMapUpdate(name="新名"))

        assert updated is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("map", "update")
        assert event.resource_id == str(existing.id)
        assert event.project_id == str(PID)

    async def test_update_map_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：地图不存在（返回 None）→ 不发布。"""
        result = await service.update_map(uuid.uuid4(), WorldMapUpdate(name="新名"))

        assert result is None
        assert recorded_events == []

    async def test_delete_map_publishes_delete(self, service, mock_repo, recorded_events) -> None:
        """B 类：无子真删成功 → map/delete（实体已加载 → project_id 非 None）。"""
        existing = _map()
        mock_repo.children = AsyncMock(return_value=[])
        mock_repo.get = AsyncMock(return_value=existing)

        assert await service.delete_map(existing.id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("map", "delete")
        assert event.resource_id == str(existing.id)
        assert event.project_id == str(PID)

    async def test_delete_map_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：无子场景地图不存在（返回 False）→ 不发布。"""
        mock_repo.children = AsyncMock(return_value=[])
        mock_repo.get = AsyncMock(return_value=None)

        assert await service.delete_map(uuid.uuid4()) is False
        assert recorded_events == []

    async def test_add_pin_publishes_create_with_project_from_map(
        self, service, mock_repo, recorded_events
    ) -> None:
        """map_pin/create：project_id 从方法内已加载的 map 推出（非 None）。"""
        wm = _map()
        mock_repo.get = AsyncMock(return_value=wm)

        pin = await service.add_pin(wm.id)

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("map_pin", "create")
        assert event.resource_id == str(pin.id)
        assert event.project_id == str(wm.project_id)

    async def test_add_pin_missing_map_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：地图不存在（写失败）→ 不发布。"""
        mock_repo.get = AsyncMock(return_value=None)

        with pytest.raises(MapNotFoundError):
            await service.add_pin(uuid.uuid4())

        assert recorded_events == []

    async def test_update_pin_publishes_none_project_id_with_warning(
        self, service, mock_repo, recorded_events, caplog
    ) -> None:
        """update_pin：MapPin 无 project_id 且未加载 map → None + warning（§15.3.2）。"""
        existing = _pin()
        mock_repo.get_pin = AsyncMock(return_value=existing)

        with caplog.at_level(logging.WARNING, logger="inkflow.domain.services.map_service"):
            updated = await service.update_pin(existing.id, MapPinUpdate(label="新标签"))

        assert updated is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("map_pin", "update")
        assert event.resource_id == str(existing.id)
        assert event.project_id is None
        assert any("project_id" in record.getMessage() for record in caplog.records)

    async def test_update_pin_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：pin 不存在（返回 None）→ 不发布。"""
        mock_repo.get_pin = AsyncMock(return_value=None)

        result = await service.update_pin(uuid.uuid4(), MapPinUpdate(label="新标签"))

        assert result is None
        assert recorded_events == []

    async def test_delete_pin_publishes_none_project_id_with_warning(
        self, service, mock_repo, recorded_events, caplog
    ) -> None:
        """delete_pin 为薄透传（未加载实体）→ None + warning（§15.3.2 已知例外）。"""
        pin_id = uuid.uuid4()

        with caplog.at_level(logging.WARNING, logger="inkflow.domain.services.map_service"):
            assert await service.delete_pin(pin_id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("map_pin", "delete")
        assert event.resource_id == str(pin_id)
        assert event.project_id is None
        assert any("project_id" in record.getMessage() for record in caplog.records)

    async def test_delete_pin_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：pin 不存在（返回 False）→ 不发布。"""
        mock_repo.delete_pin = AsyncMock(return_value=False)

        assert await service.delete_pin(uuid.uuid4()) is False
        assert recorded_events == []
