"""F36 覆盖率缺口闭合补测 — 新增用例直接通过（GREEN 阶段，coverage.xml 驱动）.

覆盖（2026-08-09 QA，CI coverage-backend 等价命令实测 miss 行归因）:
- MapService 防御/边界分支: _to_int_id int 分支 / create 双异常 / get_image_file None /
  replace_image update None / reparent 自身 None / reparent 子图 root None /
  _delete_image 失败 warning / add_pin 无 location / list_pins 过滤 /
  update_pin location 通过 / update_pin location null 转纯注释
- SQLiteMapRepository: get_pin（G4b 新增未测）/ list_maps_by_project
- API: DELETE pin 404（delete_pin False → router 自构 404）

依据: specs/f36-world-map/spec.md §13 M8（覆盖率门禁）+ F32 覆盖率缺口闭合模式。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.map import MapPin, MapPinUpdate, WorldMap
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.services.map_service import MapService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（复制自 test_map_repo.py）."""
    from inkflow.infrastructure.database.models.map import (  # noqa: F401  # 惰性注册 ORM 供 create_all（fixture 内显式 import）
        MapORM,
        MapPinORM,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project(db_session):
    """一个基础项目（地图 FK 依赖，复制自 test_map_repo.py）."""
    from inkflow.infrastructure.database.models.project import ProjectORM

    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _map(name: str = "清河县城图", **kw) -> WorldMap:
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
    return WorldMap(**values)


def _pin(**kw) -> MapPin:
    """构造测试用 pin 实体."""
    values = dict(
        id=uuid.uuid4(),
        map_id=uuid.uuid4(),
        location_id=None,
        x=50.0,
        y=50.0,
        label="标记",
        created_at=TS,
        updated_at=TS,
    )
    values.update(kw)
    return MapPin(**values)


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock MapRepositoryProtocol — 全部方法显式默认值（裸 AsyncMock 陷阱防护）."""
    repo = MagicMock(spec=MapRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.get_pin = AsyncMock(return_value=None)
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
    store.resolve = MagicMock(return_value=Path("C:/data/maps/abc/main.png"))
    return store


@pytest.fixture
def mock_world_repo() -> MagicMock:
    """Mock WorldRepositoryProtocol."""
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol."""
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def service(mock_repo, mock_asset_store, mock_world_repo, mock_project_repo) -> MapService:
    """被测 MapService（全 Mock 依赖注入）."""
    return MapService(
        repository=mock_repo,
        asset_store=mock_asset_store,
        world_repo=mock_world_repo,
        project_repo=mock_project_repo,
    )


class TestServiceCoverageGaps:
    """MapService 防御/边界分支补测."""

    async def test_list_maps_int_project_id(self, service, mock_repo) -> None:
        """_to_int_id int 分支：int project_id 直接透传（L54）."""
        await service.list_maps(12345)
        mock_repo.list.assert_awaited_once_with(
            project_id=12345,
            root_location_id=None,
            top_level_only=False,
            offset=0,
            limit=50,
        )

    async def test_create_map_cleanup_failure_warns(
        self, service, mock_repo, mock_asset_store, mock_project_repo
    ) -> None:
        """create 落库失败且清理文件也失败 → 原异常仍传播（L150-151 双异常防御）."""
        mock_project_repo.get = AsyncMock(return_value=MagicMock(id=PID))
        mock_repo.add = AsyncMock(side_effect=RuntimeError("db down"))
        mock_asset_store.delete = AsyncMock(side_effect=OSError("file locked"))
        with pytest.raises(RuntimeError):
            await service.create_map(PID, "清河县城图", "", None, "main.png", b"\x89PNG")
        mock_asset_store.delete.assert_awaited_once()

    async def test_get_image_file_missing_map(self, service, mock_repo) -> None:
        """get_image_file 地图不存在 → None（L192-195）."""
        mock_repo.get = AsyncMock(return_value=None)
        assert await service.get_image_file(uuid.uuid4()) is None

    async def test_get_image_file_returns_path(self, service, mock_repo, mock_asset_store) -> None:
        """get_image_file 命中 → asset_store.resolve 结果（L195）."""
        m = _map()
        mock_repo.get = AsyncMock(return_value=m)
        mock_asset_store.resolve = MagicMock(return_value=Path("C:/data/maps/abc/main.png"))
        assert await service.get_image_file(m.id) == Path("C:/data/maps/abc/main.png")
        mock_asset_store.resolve.assert_called_once_with(m.image_path)

    async def test_replace_image_update_failure_keeps_old(
        self, service, mock_repo, mock_asset_store
    ) -> None:
        """replace_image repo.update 返回 None → 不删旧文件（L284-286 分支）."""
        m = _map()
        mock_repo.get = AsyncMock(return_value=m)
        mock_repo.update = AsyncMock(return_value=None)
        assert await service.replace_image(m.id, "new.png", b"\x89PNG") is None
        mock_asset_store.delete.assert_not_awaited()

    async def test_delete_reparent_self_missing_returns_false(self, service, mock_repo) -> None:
        """delete_map reparent 路径自身不存在 → False（L373）."""
        child = _map(name="子图", root_location_id=uuid.uuid4())
        target = _map(name="目标图")
        # children side_effect 只对根 sid 返回 [child]，其余返回 []（防 BFS 无限递归）
        mock_repo.children = AsyncMock(side_effect=lambda mid: [] if mid != 11111 else [child])
        mock_repo.get = AsyncMock(side_effect=lambda mid: target if mid == target.id.int else None)
        assert await service.delete_map(uuid.UUID(int=11111), reparent_to=target.id) is False

    async def test_delete_reparent_child_root_none_skips(
        self, service, mock_repo, mock_world_repo
    ) -> None:
        """reparent 子图 root_location_id None → continue（L393 防御分支）."""
        child = _map(name="孤儿子图", root_location_id=None)
        target = _map(name="目标图")
        sid = uuid.UUID(int=22222)
        mock_repo.children = AsyncMock(side_effect=lambda mid: [] if mid != sid.int else [child])
        mock_repo.get = AsyncMock(
            side_effect=lambda mid: target if mid in {sid.int, target.id.int} else None
        )
        mock_repo.list_pins = AsyncMock(return_value=[])
        assert await service.delete_map(sid, reparent_to=target.id) is True
        mock_world_repo.get.assert_not_awaited()

    async def test_delete_image_failure_warns(self, service, mock_repo, mock_asset_store) -> None:
        """_delete_image 文件删除失败 → warning 不阻断（L423-424）."""
        m = _map()
        mock_repo.get = AsyncMock(return_value=m)
        mock_asset_store.delete = AsyncMock(side_effect=OSError("locked"))
        assert await service.delete_map(m.id) is True
        mock_repo.delete.assert_awaited_once_with(m.id.int)

    async def test_add_pin_without_location_skips_world_check(
        self, service, mock_repo, mock_world_repo
    ) -> None:
        """add_pin 无 location_id → world_repo.get 不调用（L456-460 分支）."""
        m = _map()
        mock_repo.get = AsyncMock(return_value=m)
        pin = await service.add_pin(m.id, None, 10.0, 20.0, "纯注释")
        assert pin.location_id is None
        mock_world_repo.get.assert_not_awaited()

    async def test_list_pins_filter_by_location(self, service, mock_repo) -> None:
        """list_pins 带 location_id → 内存过滤（L479-480）."""
        loc_a = uuid.uuid4()
        loc_b = uuid.uuid4()
        mock_repo.list_pins = AsyncMock(
            return_value=[
                _pin(location_id=loc_a, label="A"),
                _pin(location_id=loc_b, label="B"),
                _pin(location_id=None, label="C"),
            ]
        )
        result = await service.list_pins(uuid.uuid4(), location_id=loc_a)
        assert [p.label for p in result] == ["A"]
        mock_repo.list_pins.assert_awaited_once()

    async def test_update_pin_location_exists_passes(
        self, service, mock_repo, mock_world_repo
    ) -> None:
        """update_pin location 校验通过（loc 非 None 不抛，L502-504 分支）."""
        existing = _pin(map_id=uuid.uuid4())
        mock_repo.get_pin = AsyncMock(return_value=existing)
        mock_world_repo.get = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
        updated = await service.update_pin(existing.id, MapPinUpdate(location_id=uuid.uuid4()))
        assert updated is not None

    async def test_update_pin_location_null_converts_comment(self, service, mock_repo) -> None:
        """update_pin location_id 出现且 null → updates 含 None（L508 转纯注释 pin）."""
        existing = _pin(map_id=uuid.uuid4(), location_id=uuid.uuid4())
        mock_repo.get_pin = AsyncMock(return_value=existing)
        result = await service.update_pin(existing.id, MapPinUpdate(location_id=None))
        assert result is not None
        pin_arg = mock_repo.update_pin.await_args.args[0]
        assert pin_arg.location_id is None


class TestRepoCoverageGaps:
    """SQLiteMapRepository 补测（真实 in-memory SQLite，镜像 test_map_repo.py fixture）."""

    async def test_get_pin_hit_and_miss(self, db_session, project) -> None:
        """get_pin 命中往返 + 不存在 → None（G4b 新增方法补测，L253-256）."""
        from inkflow.infrastructure.database.repositories.map_repo import SQLiteMapRepository

        repo = SQLiteMapRepository(db_session)
        from inkflow.domain.models.map import WorldMap

        wm = WorldMap(
            id=uuid.uuid4(),
            project_id=uuid.UUID(int=project.id),
            name="地图",
            image_path="maps/x/main.png",
            created_at=TS,
            updated_at=TS,
        )
        saved = await repo.add(wm)
        p = await repo.add_pin(_pin(map_id=saved.id, x=1.0, y=2.0, label="p1"))
        hit = await repo.get_pin(p.id.int)
        assert hit is not None and hit.id == p.id and hit.label == "p1"
        assert await repo.get_pin(99999) is None

    async def test_list_maps_by_project(self, db_session, project) -> None:
        """list_maps_by_project 全量收集（L344-346）."""
        from inkflow.domain.models.map import WorldMap
        from inkflow.infrastructure.database.repositories.map_repo import SQLiteMapRepository

        repo = SQLiteMapRepository(db_session)
        wm = WorldMap(
            id=uuid.uuid4(),
            project_id=uuid.UUID(int=project.id),
            name="地图A",
            image_path="maps/x/main.png",
            created_at=TS,
            updated_at=TS,
        )
        wm2 = WorldMap(
            id=uuid.uuid4(),
            project_id=uuid.UUID(int=project.id),
            name="地图B",
            image_path="maps/y/main.png",
            created_at=TS,
            updated_at=TS,
        )
        await repo.add(wm)
        await repo.add(wm2)
        maps = await repo.list_maps_by_project(project.id)
        assert {m.name for m in maps} == {"地图A", "地图B"}


class TestApiCoverageGaps:
    """API 补测（TestClient + mock get_map_service，镜像 test_map_api.py）."""

    def test_delete_pin_missing_returns_404(self) -> None:
        """DELETE /map-pins/{id} delete_pin False → 404「pin 不存在」（L307）."""
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from inkflow.api.app import app

        client = TestClient(app)
        with patch("inkflow.api.routers.maps.get_map_service") as mock_get_svc:
            svc = MagicMock()
            mock_get_svc.return_value = svc
            svc.delete_pin = AsyncMock(return_value=False)
            resp = client.delete(f"/api/v1/map-pins/{uuid.uuid4()}")
            assert resp.status_code == 404
            assert resp.json()["detail"] == "pin 不存在"
