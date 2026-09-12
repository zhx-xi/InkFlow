"""Coverage backfill batch 2: MapService 未覆盖分支（Mock 注入，镜像 test_map_service）。

经公开方法驱动：
- create_map 非法 bg_source -> MapBgSourceError（148-149）
- update_map 父图循环校验遇重复子项 -> MapParentCycleError（74-75 去重 continue）
- update_map repo.update 返回 None -> 无事件返回 None（322->324）
- delete_map cascade 且自身实体缺失 -> 事件 project_id=None + warning（426-438）
- update_pin 显式 ref_id -> 合并并发布（611-612 / 615-622）
- add_pin type=role/event 关联校验通过 -> 正常创建（550->556 / 554->556）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.map import MapPin, MapPinUpdate, WorldMap, WorldMapUpdate
from inkflow.domain.ports.map_errors import MapBgSourceError, MapParentCycleError
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.services.map_service import MapService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _map(
    name: str = "清河县城图",
    *,
    map_id: uuid.UUID | None = None,
    parent_map_id: uuid.UUID | None = None,
) -> WorldMap:
    return WorldMap(
        id=map_id or uuid.uuid4(),
        project_id=PID,
        name=name,
        image_path="maps/abc/main.png",
        parent_map_id=parent_map_id,
        created_at=TS,
        updated_at=TS,
    )


def _pin() -> MapPin:
    return MapPin(
        id=uuid.uuid4(),
        map_id=uuid.uuid4(),
        x=50.0,
        y=50.0,
        label="清河县城",
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
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
def service(mock_repo: MagicMock) -> MapService:
    return MapService(
        repository=mock_repo,
        asset_store=MagicMock(),
        world_repo=MagicMock(),
    )


@pytest.mark.asyncio
async def test_create_map_rejects_unknown_bg_source(service, mock_repo) -> None:
    """bg_source 非枚举 -> MapBgSourceError，且不触达仓储（148-149）。"""
    with pytest.raises(MapBgSourceError):
        await service.create_map(PID, "新图", bg_source="hologram")

    mock_repo.get.assert_not_called()


@pytest.mark.asyncio
async def test_update_map_cycle_check_handles_duplicate_child_entries(
    service, mock_repo
) -> None:
    """父图校验：重复子项被去重，目标父图命中子树 -> MapParentCycleError（74-75）。"""
    existing = _map(map_id=uuid.UUID(int=1))
    parent_id = uuid.UUID(int=2)
    parent = _map("父图", map_id=parent_id)
    duplicate = _map("父图", map_id=parent_id, parent_map_id=existing.id)

    async def _get(map_id: int):
        return existing if map_id == 1 else parent

    mock_repo.get = AsyncMock(side_effect=_get)
    mock_repo.list = AsyncMock(return_value=([duplicate, duplicate], 2))

    with pytest.raises(MapParentCycleError):
        await service.update_map(existing.id, WorldMapUpdate(parent_map_id=parent_id))

    mock_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_map_null_update_returns_none_without_event(
    service, mock_repo, recorded_events
) -> None:
    """repo.update 返回 None -> 直接返回 None 且不发布事件（322->324）。"""
    existing = _map()
    mock_repo.get = AsyncMock(return_value=existing)
    mock_repo.update = AsyncMock(return_value=None)

    result = await service.update_map(existing.id, WorldMapUpdate(description="改"))

    assert result is None
    assert recorded_events == []


@pytest.mark.asyncio
async def test_delete_map_cascade_without_self_map_publishes_none_project(
    service, mock_repo, recorded_events
) -> None:
    """cascade 删除时自身实体缺失 -> warning + 事件 project_id=None（426-438）。"""
    mock_repo.get = AsyncMock(return_value=None)
    mock_repo.children = AsyncMock(return_value=[])
    orphan_id = uuid.UUID(int=9)

    assert await service.delete_map(orphan_id, cascade=True) is True

    mock_repo.delete_many.assert_awaited_once_with([9])
    assert len(recorded_events) == 1
    event = recorded_events[0]
    assert (event.domain, event.op) == ("map", "delete")
    assert event.project_id is None


@pytest.mark.asyncio
async def test_update_pin_with_ref_id_merges_and_publishes(
    service, mock_repo, recorded_events
) -> None:
    """update_pin 显式传 ref_id -> 合并进实体并发 map_pin/update（611-612 / 615-622）。"""
    existing = _pin()
    ref_id = uuid.UUID(int=7)
    mock_repo.get_pin = AsyncMock(return_value=existing)

    updated = await service.update_pin(existing.id, MapPinUpdate(ref_id=ref_id))

    assert updated is not None
    assert updated.ref_id == ref_id
    assert len(recorded_events) == 1
    assert (recorded_events[0].domain, recorded_events[0].op) == ("map_pin", "update")


@pytest.mark.asyncio
async def test_add_pin_accepts_role_and_event_refs(mock_repo) -> None:
    """add_pin type=role/event 且关联实体同项目 -> 校验通过创建（550->556 / 554->556）。"""
    wm = _map()
    mock_repo.get = AsyncMock(return_value=wm)
    character_repo = MagicMock()
    character_repo.get = AsyncMock(return_value=SimpleNamespace(project_id=wm.project_id))
    timeline_repo = MagicMock()
    timeline_repo.get = AsyncMock(return_value=SimpleNamespace(project_id=wm.project_id))
    svc = MapService(
        repository=mock_repo,
        asset_store=MagicMock(),
        world_repo=MagicMock(),
        character_repo=character_repo,
        timeline_repo=timeline_repo,
    )

    role_pin = await svc.add_pin(wm.id, type="role", ref_id=uuid.UUID(int=3))
    event_pin = await svc.add_pin(wm.id, type="event", ref_id=uuid.UUID(int=4))

    assert role_pin.type == "role"
    assert event_pin.type == "event"
