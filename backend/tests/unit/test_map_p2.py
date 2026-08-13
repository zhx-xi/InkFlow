"""F43 设定库 P2 地图工作台后端扩展契约 — test_map_p2.py（RED 阶段，只写测试不改 src/）.

被测扩展: F36 既有 maps/map_pins 之上叠加 P2 字段（specs/f43-setting-library-crud/spec.md
§2.7/§3.5/§9.5 B1-B7）。独立新文件（test_map_service.py 已 830 行，超 900 护栏——§9.5 裁定）。

镜像: tests/unit/test_map_service.py（service 层全 mock + fixture 构造模式）+
tests/unit/test_map_api.py（TestClient(app) + @patch("inkflow.api.routers.maps.get_map_service")
+ _mock_svc helper）。

【RED 预期（父侧验收口径）】B1-B7 全部 FAILED（AttributeError / TypeError /
AssertionError 混合），零收集 ERROR（错误类缺失用 try/except ImportError stub 置 None，
文件可收集、失败发生在用例体），零既有文件改动。

【GREEN 契约——实现方按此逐字落地】

1. 领域模型 inkflow.domain.models.map（spec §2.7/§3.5）:
   - MapPin 加 type: str = "location"（枚举 location/role/event/other）
     + ref_id: uuid.UUID | None = None ——【必须带默认值】否则 copy_service.copy
     （只传旧字段构造 MapPin）与既有 F36 测试 TypeError（spec §9.5 向后兼容约束）
   - MapPinCreate 加 type: str = "location" + ref_id: uuid.UUID | None = None
     （§3.5.1 逐字: location_id/ref_id/type/x/y/label）
   - MapPinUpdate 加 type: str | None = None + ref_id: uuid.UUID | None = None
     （exclude_unset 语义）
   - WorldMap 加 bg_source: str = "image"（枚举 shape/image/ai）+ extra: dict = {}
     ——【必须带默认值】同上（spec §9.5）
   - WorldMapUpdate 加 bg_source: str | None = None + extra: dict | None = None
     （exclude_unset 语义）
   - 关联语义（A-1）: type=location 用 location_id（ref_id 为 NULL）；type=role/event
     用 ref_id（location_id 为 NULL）；type=other 两者均 NULL。不双列并存。

2. MapService（inkflow.domain.services.map_service）:
   - __init__ 加可选注入 character_repo: CharacterRepositoryProtocol | None = None +
     timeline_repo: TimelineRepositoryProtocol | None = None（默认 None 向后兼容——D-17:
     未注入跳过关联校验仅透传，防破坏既有 F36 测试构造）
   - add_pin(map_id, location_id=None, x=0.0, y=0.0, label="", type="location",
     ref_id=None): ① 地图不存在 → MapNotFoundError（既有）；② type=role →
     character_repo.get(_to_int_id(ref_id)) 为 None → raise MapPinRefNotFoundError；
     ③ type=event → timeline_repo.get 同语义；④ type 非法（非 location/role/event/other）
     → raise MapBgSourceError（422 语义）
   - create_map(..., image_filename="", image_content=b"", bg_source="image"):
     ⑤ bg_source=shape 且无 file → 不写图，image_path 存 ""；⑥ bg_source=image 且无
     file → raise MapBgSourceError（spec §3.5.2）

3. 错误类 inkflow.domain.ports.map_errors 新增（默认消息文案逐字）:
   - MapPinRefNotFoundError(MapServiceError)「pin 关联角色/事件不存在或不在同一项目」（422）
   - MapBgSourceError(MapServiceError)「bg_source 非法 / image 模式缺图片」（422）

4. API 透传（inkflow.api.routers.maps，spec §3.5）:
   - POST /api/v1/maps/{map_id}/pins: MapPinCreate 新字段 type/ref_id → svc.add_pin
     透传（type/ref_id 必须 kwargs 形态调用——mock 位置/关键字比较分离，实现位置传必破）
   - PATCH /api/v1/maps/{map_id}: WorldMapUpdate 新字段 bg_source/extra → svc.update_map
     透传（update.model_fields_set 必须含两键）

5. repo 映射（inkflow.infrastructure.database.repositories.map_repo）:
   - _pin_orm_to_domain: type 直传；ref_id int → UUID（_int_to_uuid）
   - _pin_domain_to_orm: type 直传；ref_id UUID → int（_uuid_to_int），None 保持 None
   - _orm_to_domain: bg_source 直传；extra 直传（LenientJSON dict）
   - _domain_to_orm: bg_source 直传；extra 直传
   - ORM（infrastructure/database/models/map.py）: MapPinORM 加 type
     （VARCHAR(16) DEFAULT 'location'）+ ref_id（INTEGER）；MapORM 加 bg_source
     （VARCHAR(16) DEFAULT 'image'）+ extra（JSON LenientJSON DEFAULT {}）；
     迁移 ensure_map_columns（§2.7.3，本文件不测）

【失败形态地图（RED 阶段实测）】B1 models=AttributeError（extra='ignore' 静默丢字段，
属性访问炸）；B2/B3/B4 service=TypeError（__init__ 缺 character_repo/timeline_repo 参数
或 add_pin 缺 type 参数）；B5 service=TypeError（create_map 缺 bg_source 参数）；
B6 api=AssertionError（assert_awaited_once_with 缺参 / model_fields_set 缺键）；
B7 repo=AttributeError（转换函数不映射新字段 / ORM 无新列）。

依据: specs/f43-setting-library-crud/spec.md §2.7/§3.5/§9.5 + 父侧定稿契约。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

try:
    from inkflow.domain.ports.map_errors import MapBgSourceError, MapPinRefNotFoundError
except ImportError:  # pragma: no cover - F43 P2 RED: 错误类尚未实现
    MapBgSourceError = None
    MapPinRefNotFoundError = None

from inkflow.api.app import app
from inkflow.core.database import Base, ensure_map_columns
from inkflow.domain.models.map import MapPin, MapPinCreate, MapPinUpdate, WorldMap, WorldMapUpdate
from inkflow.domain.models.project import Project
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.map_service import MapService
from inkflow.infrastructure.database.models.map import MapORM, MapPinORM
from inkflow.infrastructure.database.repositories.map_repo import (
    _domain_to_orm,
    _orm_to_domain,
    _pin_domain_to_orm,
    _pin_orm_to_domain,
)

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
REF_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-00000000000a")  # 角色/事件关联 ref（role/event pin）
TS = datetime(2026, 8, 1, 10, 0, 0)
SHAPES = {
    "shapes": [{"id": "s_1", "type": "rect", "x": 10, "y": 20, "w": 30, "h": 40, "label": "城墙"}]
}


def _map(
    name: str = "清河县城图",
    *,
    project_id: uuid.UUID = PID,
    description: str = "",
    image_path: str = "maps/abc123/main.png",
    root_location_id: uuid.UUID | None = None,
) -> WorldMap:
    """构造测试用地图实体（固定时间戳，便于断言；只传旧字段——向后兼容默认值契约）."""
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
    x: float = 50.0,
    y: float = 50.0,
    label: str = "清河县城",
) -> MapPin:
    """构造测试用 pin 实体（固定时间戳，便于断言；只传旧字段——向后兼容默认值契约）."""
    return MapPin(
        id=uuid.uuid4(),
        map_id=map_id or uuid.uuid4(),
        location_id=location_id,
        x=x,
        y=y,
        label=label,
        created_at=TS,
        updated_at=TS,
    )


def _project(*, project_id: uuid.UUID = PID) -> Project:
    """构造测试用项目实体（create_map 项目存在性校验）."""
    return Project(id=project_id, name="测试项目", created_at=TS, updated_at=TS)


def _make_service(
    mock_repo: MagicMock,
    mock_asset_store: MagicMock,
    mock_world_repo: MagicMock,
    mock_project_repo: MagicMock,
    *,
    character_repo: MagicMock | None = None,
    timeline_repo: MagicMock | None = None,
) -> MapService:
    """构造被测 MapService（全 Mock 注入；character_repo/timeline_repo 可选扩展注入）.

    RED 形态: __init__ 未扩展 character_repo/timeline_repo 参数 → TypeError:
    unexpected keyword argument（B2/B3/B4 签名扩展 RED，属合法）。
    """
    return MapService(
        repository=mock_repo,
        asset_store=mock_asset_store,
        world_repo=mock_world_repo,
        project_repo=mock_project_repo,
        character_repo=character_repo,
        timeline_repo=timeline_repo,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock MapRepositoryProtocol — 全部 16 方法显式默认值（裸 AsyncMock 陷阱防护）."""
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
    """Mock MapAssetStoreProtocol — save 返回动态相对路径（按 map_id）."""
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
    """Mock WorldRepositoryProtocol — location 校验（get 默认 None = 地点不存在）."""
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — 项目存在性校验（get 默认 None = 项目不存在）."""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_character_repo() -> MagicMock:
    """Mock CharacterRepositoryProtocol — 角色关联校验（get 默认 None = 角色不存在）."""
    repo = MagicMock(spec=CharacterRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_timeline_repo() -> MagicMock:
    """Mock TimelineRepositoryProtocol — 事件关联校验（get 默认 None = 事件不存在）."""
    repo = MagicMock(spec=TimelineRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def service(
    mock_repo: MagicMock,
    mock_asset_store: MagicMock,
    mock_world_repo: MagicMock,
    mock_project_repo: MagicMock,
) -> MapService:
    """被测 MapService 实例（F36 既有四依赖注入——镜像 test_map_service.py）."""
    return MapService(
        repository=mock_repo,
        asset_store=mock_asset_store,
        world_repo=mock_world_repo,
        project_repo=mock_project_repo,
    )


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock MapService（被 await 方法逐用例显式赋 AsyncMock）."""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestB1Models:
    """B1: models 字段扩展 — type/ref_id/bg_source/extra（spec §2.7.1/§2.7.2 + §3.5.1/§3.5.2）."""

    def test_pin_create_carries_type_and_ref_id(self) -> None:
        """MapPinCreate(type='role', ref_id=...) → dto.type=='role' 且 dto.ref_id 保留.

        RED 形态: MapPinCreate 无 type/ref_id 字段 → Pydantic extra='ignore' 静默丢字段
        （构造不报错）→ dto.type 属性访问 AttributeError（FAILED 非 ERROR）。
        """
        dto = MapPinCreate(type="role", ref_id=REF_ID, x=42.5, y=68.0, label="苏云舟")
        assert dto.type == "role"
        assert dto.ref_id == REF_ID

    def test_pin_create_defaults_location_and_none(self) -> None:
        """MapPinCreate 缺省 → type=='location'、ref_id is None（向后兼容默认值）.

        RED 形态: 字段不存在 → 同 AttributeError（默认值无从谈起）。
        """
        dto = MapPinCreate(x=10.0, y=10.0)
        assert dto.type == "location"
        assert dto.ref_id is None

    def test_pin_update_carries_type_and_ref_id(self) -> None:
        """MapPinUpdate(type='role', ref_id=...) → dto.type=='role' 且 ref_id 保留（exclude_unset）.

        RED 形态: MapPinUpdate 无 type/ref_id 字段 → extra='ignore' 静默丢 → AttributeError。
        """
        dto = MapPinUpdate(type="role", ref_id=REF_ID, x=10.0)
        assert dto.type == "role"
        assert dto.ref_id == REF_ID

    def test_pin_entity_defaults_backward_compat(self) -> None:
        """MapPin 实体加 type/ref_id 必须带默认值（type='location', ref_id=None）——GREEN 必守.

        向后兼容约束（spec §9.5）: copy_service.copy 构造 MapPin 只传旧字段，无默认值 →
        既有 F36 测试 TypeError。本用例锁「旧字段构造 → 默认值可用」。
        RED 形态: MapPin 无 type 字段 → AttributeError。
        """
        pin = _pin(x=1.0, y=2.0, label="p")
        assert pin.type == "location"
        assert pin.ref_id is None

    def test_world_map_update_carries_bg_source_and_extra(self) -> None:
        """WorldMapUpdate(bg_source='shape', extra={...}) → dto.bg_source/extra 保留.

        RED 形态: WorldMapUpdate 无 bg_source/extra 字段 → extra='ignore' 静默丢 →
        dto.bg_source AttributeError。
        """
        dto = WorldMapUpdate(bg_source="shape", extra=SHAPES)
        assert dto.bg_source == "shape"
        assert dto.extra == SHAPES

    def test_world_map_entity_defaults_backward_compat(self) -> None:
        """WorldMap 实体加 bg_source/extra 必须带默认值（bg_source='image', extra={}）——GREEN 必守.

        向后兼容约束（spec §9.5）: 既有 F36 构造只传旧字段。
        RED 形态: WorldMap 无 bg_source 字段 → AttributeError。
        """
        wm = _map(name="清河县城图", image_path="maps/abc/main.png")
        assert wm.bg_source == "image"
        assert wm.extra == {}


class TestB2B3RefValidation:
    """B2/B3: add_pin type=role/event 关联校验 — ref 实体不存在 → MapPinRefNotFoundError（422）."""

    async def test_add_pin_role_ref_not_found_raises(
        self,
        mock_repo: MagicMock,
        mock_asset_store: MagicMock,
        mock_world_repo: MagicMock,
        mock_project_repo: MagicMock,
        mock_character_repo: MagicMock,
        mock_timeline_repo: MagicMock,
    ) -> None:
        """B2: add_pin(type='role', ref_id=...) 关联角色不存在 → character_repo.get(ref_int)
        None → MapPinRefNotFoundError（spec §3.5.3，422）.

        RED 形态: MapService.__init__ 未扩展 character_repo/timeline_repo 参数 →
        构造 TypeError: unexpected keyword argument 'character_repo'（签名扩展 RED，
        属合法——pytest.raises(None) 形态不会到达，构造先失败）。
        """
        mock_repo.get = AsyncMock(return_value=_map())
        svc = _make_service(
            mock_repo,
            mock_asset_store,
            mock_world_repo,
            mock_project_repo,
            character_repo=mock_character_repo,
            timeline_repo=mock_timeline_repo,
        )
        ref = uuid.uuid4()
        with pytest.raises(MapPinRefNotFoundError):
            await svc.add_pin(uuid.uuid4(), type="role", ref_id=ref, x=10.0, y=10.0)
        mock_character_repo.get.assert_awaited_once_with(ref.int)

    async def test_add_pin_event_ref_not_found_raises(
        self,
        mock_repo: MagicMock,
        mock_asset_store: MagicMock,
        mock_world_repo: MagicMock,
        mock_project_repo: MagicMock,
        mock_character_repo: MagicMock,
        mock_timeline_repo: MagicMock,
    ) -> None:
        """B3: add_pin(type='event', ref_id=...) 关联事件不存在 → timeline_repo.get(ref_int)
        None → MapPinRefNotFoundError（422）.

        RED 形态: 同 B2——MapService 构造 TypeError（timeline_repo 参数缺失）。
        """
        mock_repo.get = AsyncMock(return_value=_map())
        svc = _make_service(
            mock_repo,
            mock_asset_store,
            mock_world_repo,
            mock_project_repo,
            character_repo=mock_character_repo,
            timeline_repo=mock_timeline_repo,
        )
        ref = uuid.uuid4()
        with pytest.raises(MapPinRefNotFoundError):
            await svc.add_pin(uuid.uuid4(), type="event", ref_id=ref, x=10.0, y=10.0)
        mock_timeline_repo.get.assert_awaited_once_with(ref.int)


class TestB4InvalidPinType:
    """B4: add_pin type 非法枚举 → MapBgSourceError（422 语义，spec §3.5.3）."""

    async def test_add_pin_invalid_type_raises(
        self,
        mock_repo: MagicMock,
        mock_asset_store: MagicMock,
        mock_world_repo: MagicMock,
        mock_project_repo: MagicMock,
        mock_character_repo: MagicMock,
        mock_timeline_repo: MagicMock,
    ) -> None:
        """add_pin(type='invalid') 非 location/role/event/other → MapBgSourceError.

        RED 形态: 当前 add_pin 无 type 参数（且 __init__ 无扩展注入参数）→ 构造或调用
        TypeError: unexpected keyword argument（签名扩展 RED，先于任何校验）。
        """
        mock_repo.get = AsyncMock(return_value=_map())
        svc = _make_service(
            mock_repo,
            mock_asset_store,
            mock_world_repo,
            mock_project_repo,
            character_repo=mock_character_repo,
            timeline_repo=mock_timeline_repo,
        )
        with pytest.raises(MapBgSourceError):
            await svc.add_pin(uuid.uuid4(), type="invalid", x=10.0, y=10.0)


class TestB5CreateMapBgSource:
    """B5: create_map bg_source 分支 — shape 无图 / image 缺图（spec §3.5.2）."""

    async def test_create_map_shape_no_file_empty_image_path(
        self,
        service: MapService,
        mock_repo: MagicMock,
        mock_project_repo: MagicMock,
    ) -> None:
        """create_map(bg_source='shape') 无 file → 成功且返回 map.image_path==''（简图无图）.

        RED 形态: create_map 无 bg_source 参数 → TypeError: unexpected keyword
        argument 'bg_source'（签名扩展 RED）。
        """
        mock_project_repo.get = AsyncMock(return_value=_project())
        mock_repo.add = AsyncMock(side_effect=lambda m: m)
        result = await service.create_map(PID, "简图", "", None, "", b"", bg_source="shape")
        assert result.image_path == ""

    async def test_create_map_image_no_file_raises(
        self,
        service: MapService,
        mock_repo: MagicMock,
        mock_project_repo: MagicMock,
    ) -> None:
        """create_map(bg_source='image') 无 file → MapBgSourceError（image 模式必填图片）.

        RED 形态: MapBgSourceError 缺失（stub 置 None）→ pytest.raises(None) →
        ValueError「You must specify at least one parameter to match on.」（raises(None)
        形态，任务书 B2 行同款背书——错误类 stub 后 raises(None) 属预期）。
        """
        mock_project_repo.get = AsyncMock(return_value=_project())
        with pytest.raises(MapBgSourceError):
            await service.create_map(PID, "底图", "", None, "", b"", bg_source="image")


class TestB6ApiPassthrough:
    """B6: API 透传 — POST pins 透传 type/ref_id；PATCH map 透传 bg_source/extra（spec §3.5）."""

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_add_pin_passthrough_type_ref_id(self, mock_get_svc: MagicMock) -> None:
        """POST /maps/{id}/pins body 含 type/ref_id → svc.add_pin 收到 type/ref_id.

        GREEN 契约: type/ref_id 必须 kwargs 形态透传（mock 位置/关键字比较分离——实现
        位置传第 6/7 参必破）。
        RED 形态: MapPinCreate 无 type/ref_id 字段（extra='ignore' 静默丢弃）→ router
        仍按旧 5 参调用 add_pin → assert_awaited_once_with 期望 7 参失配 →
        AssertionError（expected call not found）。
        """
        svc = _mock_svc(mock_get_svc)
        map_id = uuid.uuid4()
        ref = uuid.uuid4()
        svc.add_pin = AsyncMock(return_value=_pin(map_id=map_id, x=42.5, y=68.0, label="苏云舟"))

        response = client.post(
            f"/api/v1/maps/{map_id}/pins",
            json={"type": "role", "ref_id": str(ref), "x": 42.5, "y": 68.0, "label": "苏云舟"},
        )
        assert response.status_code == 201
        svc.add_pin.assert_awaited_once_with(
            map_id, None, 42.5, 68.0, "苏云舟", type="role", ref_id=ref
        )

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_update_map_passthrough_bg_source_extra(self, mock_get_svc: MagicMock) -> None:
        """PATCH /maps/{id} body 含 bg_source/extra → svc.update_map 收到
        （update.model_fields_set 必须含两键 + 值保留）.

        RED 形态: WorldMapUpdate 无 bg_source/extra 字段 → extra='ignore' 静默丢弃 →
        "bg_source" not in update.model_fields_set → AssertionError（断言失败而非
        AttributeError——用 fields_set 锁「字段被声明且透传」，GREEN 必须声明字段）。
        """
        svc = _mock_svc(mock_get_svc)
        m = _map(project_id=PID)
        svc.update_map = AsyncMock(return_value=m)

        response = client.patch(
            f"/api/v1/maps/{m.id}",
            json={"bg_source": "shape", "extra": SHAPES},
        )
        assert response.status_code == 200
        args, kwargs = svc.update_map.await_args
        update = args[1] if len(args) > 1 else kwargs["update"]
        assert "bg_source" in update.model_fields_set
        assert "extra" in update.model_fields_set
        assert update.bg_source == "shape"
        assert update.extra == SHAPES


class TestB7RepoRoundtrip:
    """B7: repo ORM↔领域往返映射扩展（spec §2.7.1/§2.7.2）.

    GREEN 契约（映射逐字）:
    - _pin_orm_to_domain: type 直传；ref_id int → UUID（_int_to_uuid）
    - _pin_domain_to_orm: type 直传；ref_id UUID → int（_uuid_to_int），None 保持 None
    - _orm_to_domain: bg_source 直传；extra 直传（LenientJSON dict）
    - _domain_to_orm: bg_source 直传；extra 直传
    """

    def test_pin_orm_to_domain_carries_type_ref_id(self) -> None:
        """_pin_orm_to_domain: ORM type/ref_id → 领域（ref_id int→UUID）.

        RED 形态: MapPin 无 type 字段 → pin.type AttributeError（ORM 新列先构造后赋值——
        RED 期 MapPinORM 无此列，赋值或读取任一环节 AttributeError，均为预期）。
        """
        orm = MapPinORM(
            id=1,
            map_id=1,
            location_id=None,
            x=1.0,
            y=2.0,
            label="p",
            created_at=TS,
            updated_at=TS,
        )
        orm.type = "role"
        orm.ref_id = REF_ID.int
        pin = _pin_orm_to_domain(orm)
        assert pin.type == "role"
        assert pin.ref_id == REF_ID

    def test_pin_domain_to_orm_carries_type_ref_id(self) -> None:
        """_pin_domain_to_orm: 领域 type/ref_id → ORM（ref_id UUID→int）.

        RED 形态: MapPinORM 无 type 列 → orm.type AttributeError（领域构造时 type/ref_id
        被 extra='ignore' 静默丢弃，转换结果不含新字段）。
        """
        pin = MapPin(
            id=uuid.uuid4(),
            map_id=uuid.uuid4(),
            location_id=None,
            x=1.0,
            y=2.0,
            label="p",
            created_at=TS,
            updated_at=TS,
            type="role",
            ref_id=REF_ID,
        )
        orm = _pin_domain_to_orm(pin)
        assert orm.type == "role"
        assert orm.ref_id == REF_ID.int

    def test_map_orm_to_domain_carries_bg_source_extra(self) -> None:
        """_orm_to_domain: ORM bg_source/extra → 领域（extra JSON dict 直传）.

        RED 形态: WorldMap 无 bg_source 字段 → wm.bg_source AttributeError。
        """
        orm = MapORM(
            id=1,
            project_id=1,
            name="简图",
            image_path="",
            description="",
            created_at=TS,
            updated_at=TS,
        )
        orm.bg_source = "shape"
        orm.extra = SHAPES
        wm = _orm_to_domain(orm)
        assert wm.bg_source == "shape"
        assert wm.extra == SHAPES

    def test_map_domain_to_orm_carries_bg_source_extra(self) -> None:
        """_domain_to_orm: 领域 bg_source/extra → ORM.

        RED 形态: MapORM 无 bg_source 列 → orm.bg_source AttributeError（领域构造时
        bg_source/extra 被 extra='ignore' 静默丢弃）。
        """
        wm = WorldMap(
            id=uuid.uuid4(),
            project_id=PID,
            name="简图",
            image_path="",
            description="",
            root_location_id=None,
            created_at=TS,
            updated_at=TS,
            bg_source="shape",
            extra=SHAPES,
        )
        orm = _domain_to_orm(wm)
        assert orm.bg_source == "shape"
        assert orm.extra == SHAPES


# ─────────────────────────────────────────────────────────────────────────────
# B8: ensure_map_columns 迁移契约（spec §2.7.3 — 覆盖率缺口闭合补测，GREEN 形态）
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def engine():
    """独立 in-memory SQLite — 每个测试一个全新数据库（镜像 test_provider_config_migration.py）."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield eng
    await eng.dispose()


async def _create_legacy_maps(conn) -> None:
    """模拟旧库: 手工建 maps 表（无 bg_source/extra 列，其余列同 MapORM）+ 1 行旧数据."""
    await conn.execute(
        text(
            """
            CREATE TABLE maps (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name VARCHAR(50) NOT NULL,
                image_path VARCHAR(255) NOT NULL,
                description VARCHAR(500) NOT NULL,
                root_location_id INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            INSERT INTO maps
                (project_id, name, image_path, description, root_location_id,
                 created_at, updated_at)
            VALUES
                (1, '清河县城图', 'maps/abc123/main.png', '', NULL,
                 '2026-01-01 00:00:00', '2026-01-01 00:00:00')
            """
        )
    )


async def _create_legacy_map_pins(conn) -> None:
    """模拟旧库: 手工建 map_pins 表（无 type/ref_id 列，其余列同 MapPinORM）+ 1 行旧数据."""
    await conn.execute(
        text(
            """
            CREATE TABLE map_pins (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                map_id INTEGER NOT NULL,
                location_id INTEGER,
                x FLOAT NOT NULL,
                y FLOAT NOT NULL,
                label VARCHAR(50) NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            INSERT INTO map_pins
                (map_id, location_id, x, y, label, created_at, updated_at)
            VALUES
                (1, NULL, 42.5, 68.0, '清河县城', '2026-01-01 00:00:00',
                 '2026-01-01 00:00:00')
            """
        )
    )


@pytest.mark.integration
class TestMapMigration:
    """B8: ensure_map_columns 轻量列迁移契约 — 旧库加列 / 数据保留 / 幂等 / 表不存在 no-op."""

    async def test_legacy_maps_gets_bg_source_and_extra(self, engine):
        """旧 maps 表（无 bg_source/extra 列）迁移后: 两列存在 + 旧数据保留."""
        async with engine.begin() as conn:
            await _create_legacy_maps(conn)
            await conn.run_sync(ensure_map_columns)

            cols = (await conn.execute(text("PRAGMA table_info(maps)"))).fetchall()
            col_names = [row[1] for row in cols]
            assert "bg_source" in col_names, f"迁移后应含 bg_source 列，实际列: {col_names}"
            assert "extra" in col_names, f"迁移后应含 extra 列，实际列: {col_names}"

            names = (await conn.execute(text("SELECT name FROM maps"))).scalars().all()
            assert names == ["清河县城图"]  # 迁移不丢数据

    async def test_legacy_map_pins_gets_type_and_ref_id(self, engine):
        """旧 map_pins 表（无 type/ref_id 列）迁移后: 两列存在 + 旧数据保留."""
        async with engine.begin() as conn:
            await _create_legacy_map_pins(conn)
            await conn.run_sync(ensure_map_columns)

            cols = (await conn.execute(text("PRAGMA table_info(map_pins)"))).fetchall()
            col_names = [row[1] for row in cols]
            assert "type" in col_names, f"迁移后应含 type 列，实际列: {col_names}"
            assert "ref_id" in col_names, f"迁移后应含 ref_id 列，实际列: {col_names}"

            labels = (await conn.execute(text("SELECT label FROM map_pins"))).scalars().all()
            assert labels == ["清河县城"]  # 迁移不丢数据

    async def test_idempotent_when_columns_exist(self, engine):
        """新库（create_all 已含新列）→ 迁移 no-op 不报错（幂等）."""
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(ensure_map_columns)  # no-op

            map_cols = (await conn.execute(text("PRAGMA table_info(maps)"))).fetchall()
            map_names = [row[1] for row in map_cols]
            assert "bg_source" in map_names
            assert "extra" in map_names

            pin_cols = (await conn.execute(text("PRAGMA table_info(map_pins)"))).fetchall()
            pin_names = [row[1] for row in pin_cols]
            assert "type" in pin_names
            assert "ref_id" in pin_names

    async def test_noop_when_tables_missing(self, engine):
        """表不存在 → 迁移 no-op 不抛错，无副作用（未建表、未 ALTER）."""
        async with engine.begin() as conn:
            result = await conn.run_sync(ensure_map_columns)
            assert result is None  # 签名契约 -> None，不抛异常

            map_cols = (await conn.execute(text("PRAGMA table_info(maps)"))).fetchall()
            pin_cols = (await conn.execute(text("PRAGMA table_info(map_pins)"))).fetchall()
            assert map_cols == []  # 未建表、未 ALTER（无副作用）
            assert pin_cols == []
