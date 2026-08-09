"""F36 世界观地图服务层单元测试 — MapService（RED 阶段，只写测试不改 src/）.

被测类: inkflow.domain.services.map_service.MapService（尚未实现——本文件为 RED 契约）。
镜像: tests/unit/test_world_service.py（F35）——service 层全 mock（AsyncMock）；fixture 全部
方法显式设默认值（裸 AsyncMock 陷阱: 未配置方法返回 child mock，真值判断静默错）。

RED 预期: 收集期 ModuleNotFoundError（map_service / map_errors / map 模型未实现）= 正确 RED；
接线用例（import 既有 world_service/project_service）放用例体惰性导入——实现缺失时顶部
import 待实现模块同样收集失败，二者分离便于分阶段 GREEN。

设计假设（父侧定稿契约——GREEN 实现按此落地，逐字记录）:

【构造】MapService(*, repository: MapRepositoryProtocol, asset_store: MapAssetStoreProtocol,
  world_repo: WorldRepositoryProtocol, project_repo: ProjectRepositoryProtocol | None = None)，
  全部 mock 注入。

【方法契约（13 个）】
create_map(project_id, name, description, root_location_id, image_filename, image_content)
  -> WorldMap 校验链（load-bearing，负例必须命中目标分支）:
  ① project_repo.get(pid_int) None → raise ProjectNotFoundError（world_errors 复用，404）
  ② root_location_id 提供 → world_repo.get(root_int) 为 None 或 project_id != 入参
     → raise MapRootLocationNotFoundError
  ③ repo.get_by_name(pid_int, name) 非 None → raise MapNameConflictError；
     root_location_id 非 None 且 repo.list(pid_int, root_location_id=root_int) 非空
     → raise MapRootLocationConflictError
  ④ asset_store.save(map_id=新uuid, filename=image_filename, content=image_content)
     抛 MapAssetError → 透传不落库
  ⑤ repo.add 抛异常 → asset_store.delete(已写相对路径) 补调用（防孤儿文件）后 re-raise
  ⑥ 成功返回 repo.add 结果
list_maps(project_id, root_location_id=None, top_level_only=False, offset=0, limit=50)
  -> tuple[list[WorldMap], int] —— 透传 repo.list（root_location_id 转 int）
get_map(map_id) -> WorldMap | None —— 透传 repo.get
update_map(map_id, update: WorldMapUpdate) -> WorldMap | None:
  ① repo.get None → 返回 None
  ② name 在 model_fields_set 且非 None → repo.get_by_name 冲突（排除自身）→ MapNameConflictError
  ③ root_location_id 在 model_fields_set: 新值非 None → world_repo.get 校验（同②）
     → MapRootLocationNotFoundError；再 repo.list(pid, root_location_id=new_int) 非空
     （排除自身）→ MapRootLocationConflictError
  ④ repo.update(merged) 返回
replace_image(map_id, image_filename, image_content) -> WorldMap:
  ① repo.get None → 返回 None（router 转 404）
  ② asset_store.save(map_id, filename, content) → 新相对路径
  ③ repo.update(image_path=新路径) 成功
  ④ 成功后 asset_store.delete(旧 image_path)；save 或 update 失败 → 不删旧文件
     （原子性，spec §5.1 D5）
  ⑤ 返回更新后对象
delete_map(map_id, cascade=False, reparent_to=None) -> bool（D6 参数矩阵，load-bearing）:
  ① children = repo.children(map_id_int)；有子且无 cascade/reparent_to
     → raise MapChildrenActionRequiredError
  ② cascade=True: 递归子树集合（children DFS，含自身）→ repo.delete_many(全部 int ids)
     → 每个子树地图 asset_store.delete(image_path)（先 DB 后文件；文件删除失败 log warning
     不阻断——测试只断言 DB 调用 + delete 被调）→ 返回 True
  ③ reparent_to 非 None:
     a. repo.get(target_int) None → raise MapReparentTargetError；target.project_id != 自身
        project_id → raise MapReparentTargetError
     b. target 在自身子树集合（递归 children 含 target.id）→ raise MapReparentTargetError
     c. 对每个直接子地图 M_child（= children(map_id)）: B = M_child.root_location_id；
        若 repo.list_pins(target_int) 已有 location_id==B 的 pin → 复用不新建；否则
        world_repo.get(B_int).name 取地点名 → repo.add_pin(MapPin(location_id=B, x=50.0,
        y=50.0, label=B.name))（D3 自动补 pin，默认居中+地点名）
     d. repo.delete(map_id_int)（显式级联 pins）+ asset_store.delete(自身 image_path) → True
  ④ 无子: repo.delete + asset_store.delete → True
  ⑤ repo.get None（无子场景时 map 不存在）→ 返回 False（router 转 404）
children(map_id) -> list[WorldMap] —— 透传 repo.children
add_pin(map_id, location_id, x, y, label) -> MapPin:
  ① repo.get(map_id_int) None → raise MapNotFoundError
  ② location_id 提供 → world_repo.get(loc_int) None 或跨项目 → raise MapPinLocationNotFoundError
  ③ repo.add_pin 返回
list_pins(map_id) -> list[MapPin] —— 透传 repo.list_pins（map 不存在返回空列表，无 404 校验）
update_pin(pin_id, update: MapPinUpdate) -> MapPin | None:
  ① repo.get_pin(pin_id) → None → 返回 None（2026-08-09 父侧裁定：repo.update_pin
     单参全对象契约——service 先 get_pin 取现有，合并后传完整 MapPin）
  ② location_id 在 model_fields_set 且非 None → world_repo.get 校验 → MapPinLocationNotFoundError
  ③ model_copy 合并 → repo.update_pin(完整 MapPin) 返回
delete_pin(pin_id) -> bool —— 透传 repo.delete_pin
cleanup_project(project_id) -> int（项目硬删钩子 D10=b）:
  ① repo.list_maps_by_project(pid_int) 收集全部地图
  ② repo.delete_by_project(pid_int) 单事务删 pins+maps
  ③ 每个地图 asset_store.delete(image_path)（失败 warning 不阻断）
  ④ 返回 len(maps)
clear_location_pins(location_ids: list[uuid.UUID]) -> int（地点硬删钩子 D10=b）:
  循环 repo.clear_location_pins(loc_int) 累加返回更新行数

【错误类（inkflow.domain.ports.map_errors，新建模块）——默认消息文案逐字】
MapServiceError(Exception) 基类（422 业务错误基类）
MapNameConflictError(MapServiceError) 同名地图已存在（项目内）
MapRootLocationConflictError(MapServiceError) 该地点已挂有一张地图
MapRootLocationNotFoundError(MapServiceError) 父地点不存在或不在同一项目
MapPinLocationNotFoundError(MapServiceError) pin 关联地点不存在或不在同一项目
MapChildrenActionRequiredError(MapServiceError)
  该地图存在子地图，必须指定 cascade=true（级联删除）或 reparent_to=<map_id>（子地图改挂新父）
MapReparentTargetError(MapServiceError)
  reparent 目标地图不存在/不在同一项目/是自身子孙地图
MapNotFoundError(Exception) 地图不存在（404）
MapPinNotFoundError(Exception) pin 不存在（404）
MapAssetError(Exception)（500 文件层，消息自由）
ProjectNotFoundError 复用 inkflow.domain.ports.world_errors（断言 map_errors 模块
【不导出】ProjectNotFoundError——F16 遮蔽防护，见 TestMapErrorsModule）

【接线契约（F36 在 F35/F1 既有 service 上加可选回调，GREEN 批实现）】
- WorldService 构造加 location_cleanup: Callable[[list[int]], Awaitable[None]] | None = None；
  delete_setting 的 cascade 分支（repo.hard_delete_many 之后）与 force 分支（repo.hard_delete
  之后）调用 await location_cleanup(ids)（cascade 传子树全部 int ids；force 传 [sid]）
- ProjectService 构造加 map_cleanup: Callable[[int], Awaitable[int]] | None = None；
  hard_delete 成功后调用 await map_cleanup(pid_int)（异常 log warning 不阻断）

【领域模型（inkflow.domain.models.map，spec §2.3）】
WorldMap/WorldMapCreate/WorldMapUpdate/MapPin/MapPinCreate/MapPinUpdate；WorldMapUpdate 与
MapPinUpdate 全可选 exclude_unset 语义（root_location_id None=不修改；出现且 null=改全局图）。
【MapAssetStoreProtocol（inkflow.infrastructure.assets.map_asset_store 导出）】
save(*, map_id, filename, content) -> str；delete(relative_path) -> None；
copy(relative_path, *, map_id) -> str；resolve(relative_path) -> Path。测试全 mock。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.map import MapPin, MapPinUpdate, WorldMap, WorldMapUpdate
from inkflow.domain.models.project import Project
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.map_errors import (
    MapAssetError,
    MapChildrenActionRequiredError,
    MapNameConflictError,
    MapNotFoundError,
    MapPinLocationNotFoundError,
    MapPinNotFoundError,
    MapReparentTargetError,
    MapRootLocationConflictError,
    MapRootLocationNotFoundError,
    MapServiceError,
)
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_errors import ProjectNotFoundError
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.map_service import MapService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
OTHER_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")  # 跨项目校验用
TS = datetime(2026, 8, 1, 10, 0, 0)
IMG = b"\x89PNG\r\n\x1a\n" + b"0" * 64  # 图片字节内容（mock 不校验魔数）


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
    x: float = 50.0,
    y: float = 50.0,
    label: str = "清河县城",
) -> MapPin:
    """构造测试用 pin 实体（固定时间戳，便于断言）。"""
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


def _setting(
    name: str,
    *,
    project_id: uuid.UUID = PID,
    parent_id: uuid.UUID | None = None,
) -> WorldSetting:
    """构造测试用世界观地点条目（location 校验 mock 返回）。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        category="",
        content="",
        is_deleted=False,
        parent_id=parent_id,
        created_at=TS,
        updated_at=TS,
    )


def _project(*, project_id: uuid.UUID = PID) -> Project:
    """构造测试用项目实体（create_map 项目存在性校验）。"""
    return Project(id=project_id, name="测试项目", created_at=TS, updated_at=TS)


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock MapRepositoryProtocol — 全部 16 方法显式默认值（裸 AsyncMock 陷阱防护）。"""
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


class TestCreateMap:
    """create_map — 校验链 ①②③ + 文件/落库编排 ④⑤⑥（spec §5.4）。"""

    async def test_create_project_missing_raises(
        self, service, mock_repo, mock_asset_store
    ) -> None:
        """① project_repo.get → None → ProjectNotFoundError（world_errors 复用, 404）."""
        with pytest.raises(ProjectNotFoundError):
            await service.create_map(PID, "清河县城图", "", None, "main.png", IMG)
        mock_repo.add.assert_not_awaited()
        mock_asset_store.save.assert_not_awaited()

    async def test_create_root_location_invalid_raises(
        self, service, mock_repo, mock_project_repo, mock_world_repo, mock_asset_store
    ) -> None:
        """② world_repo.get(root) None 或跨项目 → MapRootLocationNotFoundError."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        root = uuid.uuid4()
        with pytest.raises(MapRootLocationNotFoundError):  # 地点不存在
            await service.create_map(PID, "清河县城图", "", root, "main.png", IMG)
        mock_world_repo.get = AsyncMock(return_value=_setting("他国", project_id=OTHER_PID))
        with pytest.raises(MapRootLocationNotFoundError):  # 跨项目
            await service.create_map(PID, "清河县城图", "", root, "main.png", IMG)
        mock_repo.add.assert_not_awaited()
        mock_asset_store.save.assert_not_awaited()

    async def test_create_name_conflict_raises(self, service, mock_repo, mock_project_repo) -> None:
        """③ get_by_name(pid, name) 非 None → MapNameConflictError（422）."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        mock_repo.get_by_name = AsyncMock(return_value=_map(name="清河县城图"))
        with pytest.raises(MapNameConflictError):
            await service.create_map(PID, "清河县城图", "", None, "main.png", IMG)
        mock_repo.add.assert_not_awaited()

    async def test_create_root_location_conflict_raises(
        self, service, mock_repo, mock_project_repo, mock_world_repo
    ) -> None:
        """③ repo.list(pid, root_location_id=root) 非空 → MapRootLocationConflictError."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        root = uuid.uuid4()
        mock_world_repo.get = AsyncMock(return_value=_setting("清河县城"))
        mock_repo.list = AsyncMock(return_value=([_map(name="既有地图", root_location_id=root)], 1))
        with pytest.raises(MapRootLocationConflictError):
            await service.create_map(PID, "清河县城图", "", root, "main.png", IMG)
        mock_repo.add.assert_not_awaited()
        assert mock_repo.list.await_args.kwargs["root_location_id"] == root.int

    async def test_create_success_save_then_add(
        self, service, mock_repo, mock_asset_store, mock_project_repo, mock_world_repo
    ) -> None:
        """⑥ 成功: save(map_id=新 uuid, filename, content) → repo.add(同 id 地图) → 返回 add 结果
        （save 的 map_id 与 add 的 map.id 一致）."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        root = uuid.uuid4()
        mock_world_repo.get = AsyncMock(return_value=_setting("清河县城"))
        result = await service.create_map(PID, "清河县城图", "县城坊市布局", root, "main.png", IMG)
        assert result.name == "清河县城图"
        mock_project_repo.get.assert_awaited_once_with(PID.int)
        mock_world_repo.get.assert_awaited_once_with(root.int)
        mock_repo.get_by_name.assert_awaited_once_with(PID.int, "清河县城图")
        added = mock_repo.add.await_args.args[0]
        assert isinstance(added, WorldMap)
        assert added.project_id == PID
        assert added.root_location_id == root
        # fixture save 的 side_effect 生成 f"maps/{map_id}/main.png"——断言真实路径字符串
        # （父侧裁定 2026-08-09：AsyncMock(side_effect=...) 的 return_value 是子 mock，无断言价值）
        assert added.image_path == f"maps/{added.id}/main.png"
        mock_asset_store.save.assert_awaited_once_with(
            map_id=added.id, filename="main.png", content=IMG
        )
        assert result is added

    async def test_create_add_failure_deletes_file(
        self, service, mock_repo, mock_asset_store, mock_project_repo
    ) -> None:
        """⑤ repo.add 抛异常 → asset_store.delete(已写相对路径) 补调用（防孤儿）→ re-raise."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        mock_repo.add = AsyncMock(side_effect=RuntimeError("db down"))
        with pytest.raises(RuntimeError):
            await service.create_map(PID, "清河县城图", "", None, "main.png", IMG)
        # 防孤儿补删：delete 收到 save 返回的真实相对路径（父侧裁定：side_effect mock
        # 无 return_value 语义——断言参数形态为 maps/ 前缀相对路径）
        deleted = mock_asset_store.delete.await_args.args[0]
        assert isinstance(deleted, str) and deleted.startswith("maps/")
        mock_asset_store.delete.assert_awaited_once()

    async def test_create_asset_save_failure_passthrough(
        self, service, mock_repo, mock_asset_store, mock_project_repo
    ) -> None:
        """④ save 抛 MapAssetError → 透传（500 文件层）且 repo.add 不调用."""
        mock_project_repo.get = AsyncMock(return_value=_project())
        mock_asset_store.save = AsyncMock(side_effect=MapAssetError("图片类型不支持"))
        with pytest.raises(MapAssetError):
            await service.create_map(PID, "清河县城图", "", None, "main.png", IMG)
        mock_repo.add.assert_not_awaited()
        mock_asset_store.delete.assert_not_awaited()


class TestUpdateMap:
    """update_map — ① 不存在→None；② 改名冲突（排除自身）；③ root_location 改挂校验。"""

    async def test_update_missing_returns_none(self, service, mock_repo) -> None:
        """① repo.get → None → 返回 None（router 转 404）."""
        assert await service.update_map(uuid.uuid4(), WorldMapUpdate(name="改名")) is None
        mock_repo.update.assert_not_awaited()

    async def test_update_name_conflict_other_raises(self, service, mock_repo) -> None:
        """② 改名撞他图（排除自身后仍冲突）→ MapNameConflictError；update 不调用."""
        existing = _map(name="清河县城图")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_name = AsyncMock(return_value=_map(name="清河县城图·改"))
        with pytest.raises(MapNameConflictError):
            await service.update_map(existing.id, WorldMapUpdate(name="清河县城图·改"))
        mock_repo.update.assert_not_awaited()
        mock_repo.get_by_name.assert_awaited_once_with(PID.int, "清河县城图·改")

    async def test_update_name_conflict_self_passes(self, service, mock_repo) -> None:
        """② 排除自身: get_by_name 命中自身 → 不冲突 → repo.update（merged 含新名）."""
        existing = _map(name="清河县城图")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_name = AsyncMock(return_value=existing)
        result = await service.update_map(existing.id, WorldMapUpdate(name="清河县城图·改"))
        merged = mock_repo.update.await_args.args[0]
        assert merged.name == "清河县城图·改"
        assert result is merged

    async def test_update_root_location_not_found_raises(
        self, service, mock_repo, mock_world_repo
    ) -> None:
        """③ root_location_id 出现且非 None → world_repo.get(new) None →
        MapRootLocationNotFoundError."""
        existing = _map(name="清河县城图")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_name = AsyncMock(return_value=None)
        with pytest.raises(MapRootLocationNotFoundError):
            await service.update_map(existing.id, WorldMapUpdate(root_location_id=uuid.uuid4()))
        mock_repo.update.assert_not_awaited()

    async def test_update_root_location_conflict_raises(
        self, service, mock_repo, mock_world_repo
    ) -> None:
        """③ repo.list(pid, root_location_id=new) 非空（他图）→ MapRootLocationConflictError."""
        existing = _map(name="清河县城图")
        new_root = uuid.uuid4()
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_name = AsyncMock(return_value=None)
        mock_world_repo.get = AsyncMock(return_value=_setting("清河县城"))
        mock_repo.list = AsyncMock(return_value=([_map(name="他图", root_location_id=new_root)], 1))
        with pytest.raises(MapRootLocationConflictError):
            await service.update_map(existing.id, WorldMapUpdate(root_location_id=new_root))
        mock_repo.update.assert_not_awaited()

    async def test_update_root_location_rehang_success_excludes_self(
        self, service, mock_repo, mock_world_repo
    ) -> None:
        """③ 排除自身: repo.list 仅命中自身 → 不冲突 → 改挂成功（merged.root_location_id=new）."""
        existing = _map(name="清河县城图", description="县城坊市布局")
        new_root = uuid.uuid4()
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_name = AsyncMock(return_value=None)
        mock_world_repo.get = AsyncMock(return_value=_setting("清河县城"))
        mock_repo.list = AsyncMock(return_value=([existing], 1))
        result = await service.update_map(existing.id, WorldMapUpdate(root_location_id=new_root))
        merged = mock_repo.update.await_args.args[0]
        assert merged.root_location_id == new_root
        assert merged.name == "清河县城图"  # 未出现字段保持原值
        assert merged.description == "县城坊市布局"
        assert result is merged


class TestReplaceImage:
    """replace_image — 换图原子性（先写新成功后删旧，spec §5.1 D5）。"""

    async def test_replace_image_missing_returns_none(
        self, service, mock_repo, mock_asset_store
    ) -> None:
        """① repo.get → None → 返回 None（router 转 404）；save/update/delete 均不调用."""
        assert await service.replace_image(uuid.uuid4(), "new.png", IMG) is None
        mock_asset_store.save.assert_not_awaited()
        mock_repo.update.assert_not_awaited()
        mock_asset_store.delete.assert_not_awaited()

    async def test_replace_image_success_new_then_old(
        self, service, mock_repo, mock_asset_store
    ) -> None:
        """②③④ 成功: save → 新相对路径 → update(image_path=新路径) → 成功后 delete(旧路径)."""
        m = _map(name="清河县城图", image_path="maps/old/main.png")
        mock_repo.get = AsyncMock(return_value=m)
        mock_asset_store.save = AsyncMock(return_value="maps/new/main.png")
        result = await service.replace_image(m.id, "new.png", IMG)
        merged = mock_repo.update.await_args.args[0]
        assert merged.image_path == "maps/new/main.png"
        assert result is merged
        mock_asset_store.save.assert_awaited_once_with(map_id=m.id, filename="new.png", content=IMG)
        mock_asset_store.delete.assert_awaited_once_with("maps/old/main.png")

    async def test_replace_image_save_failure_keeps_old(
        self, service, mock_repo, mock_asset_store
    ) -> None:
        """④ 原子性: save 抛 MapAssetError → 透传；旧文件不删、DB 不更新（update 失败同语义）."""
        m = _map(name="清河县城图", image_path="maps/old/main.png")
        mock_repo.get = AsyncMock(return_value=m)
        mock_asset_store.save = AsyncMock(side_effect=MapAssetError("写文件失败"))
        with pytest.raises(MapAssetError):
            await service.replace_image(m.id, "new.png", IMG)
        mock_repo.update.assert_not_awaited()
        mock_asset_store.delete.assert_not_awaited()


class TestDeleteMap:
    """delete_map — D6 参数矩阵（spec §5.3）: 无子真删 / 有子强制选择 / cascade / reparent。"""

    async def test_delete_with_children_requires_action(
        self, service, mock_repo, mock_asset_store
    ) -> None:
        """① 有子地图且无 cascade/reparent_to → MapChildrenActionRequiredError."""
        m = _map(name="青州全图")
        child = _map(name="清河县城图", image_path="maps/child/main.png")
        mock_repo.get = AsyncMock(return_value=m)
        mock_repo.children = AsyncMock(return_value=[child])
        with pytest.raises(MapChildrenActionRequiredError):
            await service.delete_map(m.id)
        mock_repo.delete.assert_not_awaited()
        mock_asset_store.delete.assert_not_awaited()

    async def test_delete_no_children_deletes_map_and_file(
        self, service, mock_repo, mock_asset_store
    ) -> None:
        """④ 无子: repo.delete(map_id)（显式级联 pins）+ delete(image_path) → True."""
        m = _map(name="清河县城图")
        mock_repo.get = AsyncMock(return_value=m)
        mock_repo.children = AsyncMock(return_value=[])
        result = await service.delete_map(m.id)
        assert result is True
        mock_repo.delete.assert_awaited_once_with(m.id.int)
        mock_asset_store.delete.assert_awaited_once_with(m.image_path)

    async def test_delete_missing_returns_false(self, service, mock_repo, mock_asset_store) -> None:
        """⑤ repo.get → None（无子场景）→ 返回 False（router 转 404）."""
        map_id = uuid.uuid4()
        mock_repo.children = AsyncMock(return_value=[])
        result = await service.delete_map(map_id)
        assert result is False
        mock_repo.get.assert_any_await(map_id.int)
        mock_repo.delete.assert_not_awaited()
        mock_asset_store.delete.assert_not_awaited()

    async def test_delete_cascade_deletes_subtree_and_files(
        self, service, mock_repo, mock_asset_store
    ) -> None:
        """② cascade: 子树集合（children DFS 含自身）→ delete_many(全部 int ids) →
        每张子图文件 delete."""
        m = _map(name="青州全图")
        child = _map(name="清河县城图", image_path="maps/child/main.png")
        mock_repo.get = AsyncMock(return_value=m)
        mock_repo.children = AsyncMock(side_effect=lambda mid: [child] if mid == m.id.int else [])
        mock_repo.delete_many = AsyncMock(return_value=2)
        result = await service.delete_map(m.id, cascade=True)
        assert result is True
        mock_repo.delete_many.assert_awaited_once()
        assert set(mock_repo.delete_many.await_args.args[0]) == {m.id.int, child.id.int}
        mock_asset_store.delete.assert_any_await(m.image_path)
        mock_asset_store.delete.assert_any_await(child.image_path)
        assert mock_asset_store.delete.await_count == 2

    async def test_delete_cascade_three_level_subtree(
        self, service, mock_repo, mock_asset_store
    ) -> None:
        """② 子子孙三层: DFS 递归收集整棵子树（3 张图）→ delete_many(3 ids) + 3 文件 delete."""
        root = _map(name="大越国全图")
        child = _map(name="青州全图", image_path="maps/c1/main.png")
        grandchild = _map(name="清河县城图", image_path="maps/c2/main.png")
        by_id = {root.id.int: [child], child.id.int: [grandchild], grandchild.id.int: []}
        mock_repo.get = AsyncMock(return_value=root)
        mock_repo.children = AsyncMock(side_effect=lambda mid: by_id.get(mid, []))
        mock_repo.delete_many = AsyncMock(return_value=3)
        result = await service.delete_map(root.id, cascade=True)
        assert result is True
        assert set(mock_repo.delete_many.await_args.args[0]) == {
            root.id.int,
            child.id.int,
            grandchild.id.int,
        }
        assert mock_asset_store.delete.await_count == 3
        mock_asset_store.delete.assert_any_await(root.image_path)
        mock_asset_store.delete.assert_any_await(child.image_path)
        mock_asset_store.delete.assert_any_await(grandchild.image_path)

    async def test_delete_reparent_missing_target_raises(
        self, service, mock_repo, mock_asset_store
    ) -> None:
        """③a repo.get(target) → None → MapReparentTargetError；delete 不调用."""
        m = _map(name="青州全图")
        child = _map(name="清河县城图")
        mock_repo.get = AsyncMock(side_effect=lambda mid: m if mid == m.id.int else None)
        mock_repo.children = AsyncMock(side_effect=lambda mid: [child] if mid == m.id.int else [])
        with pytest.raises(MapReparentTargetError):
            await service.delete_map(m.id, reparent_to=uuid.uuid4())
        mock_repo.delete.assert_not_awaited()
        mock_asset_store.delete.assert_not_awaited()

    async def test_delete_reparent_cross_project_target_raises(
        self, service, mock_repo, mock_asset_store
    ) -> None:
        """③a target.project_id != 自身 project_id → MapReparentTargetError（数据隔离）."""
        m = _map(name="青州全图")
        child = _map(name="清河县城图")
        other_target = _map(name="他书全图", project_id=OTHER_PID)
        mock_repo.get = AsyncMock(side_effect=lambda mid: m if mid == m.id.int else other_target)
        mock_repo.children = AsyncMock(side_effect=lambda mid: [child] if mid == m.id.int else [])
        with pytest.raises(MapReparentTargetError):
            await service.delete_map(m.id, reparent_to=other_target.id)
        mock_repo.delete.assert_not_awaited()
        mock_asset_store.delete.assert_not_awaited()

    async def test_delete_reparent_target_in_own_subtree_raises(
        self, service, mock_repo, mock_asset_store
    ) -> None:
        """③b target 在自身子树集合（递归 children 含 target.id）→ MapReparentTargetError."""
        m = _map(name="青州全图")
        child = _map(name="清河县城图")
        target = _map(name="清河县城坊市图")  # 自身深层子孙
        by_id = {m.id.int: [child], child.id.int: [target], target.id.int: []}
        mock_repo.get = AsyncMock(side_effect=lambda mid: m if mid == m.id.int else target)
        mock_repo.children = AsyncMock(side_effect=lambda mid: by_id.get(mid, []))
        with pytest.raises(MapReparentTargetError):
            await service.delete_map(m.id, reparent_to=target.id)
        mock_repo.delete.assert_not_awaited()
        mock_asset_store.delete.assert_not_awaited()

    async def test_delete_reparent_success_pins_reuse_and_create(
        self, service, mock_repo, mock_asset_store, mock_world_repo
    ) -> None:
        """③c/d 成功: 目标已有同地点 pin → 复用；否则 world_repo.get(B).name 取名 →
        add_pin(B, 50, 50, B.name)；子图不 UPDATE root_location（树平移靠 pin 转移）；
        delete(map_id) + delete(自身 image_path) → True."""
        m = _map(name="青州全图", image_path="maps/self/main.png")
        b1, b2 = uuid.uuid4(), uuid.uuid4()
        child1 = _map(name="清河县城图", image_path="maps/c1/main.png", root_location_id=b1)
        child2 = _map(name="青州分图", image_path="maps/c2/main.png", root_location_id=b2)
        target = _map(name="东大陆全图", image_path="maps/t/main.png")
        mock_repo.get = AsyncMock(side_effect=lambda mid: m if mid == m.id.int else target)
        mock_repo.children = AsyncMock(
            side_effect=lambda mid: [child1, child2] if mid == m.id.int else []
        )
        mock_repo.list_pins = AsyncMock(return_value=[_pin(location_id=b1)])  # b1 复用分支
        mock_world_repo.get = AsyncMock(return_value=_setting("青州分地"))  # b2 新建分支
        result = await service.delete_map(m.id, reparent_to=target.id)
        assert result is True
        mock_repo.list_pins.assert_awaited_once_with(target.id.int)
        mock_repo.add_pin.assert_awaited_once()  # b1 复用 → 仅 b2 新建一个 pin
        pin = mock_repo.add_pin.await_args.args[0]
        assert isinstance(pin, MapPin)
        assert pin.location_id == b2
        assert pin.x == 50.0 and pin.y == 50.0  # 默认居中
        assert pin.label == "青州分地"  # 地点名
        mock_world_repo.get.assert_awaited_once_with(b2.int)
        mock_repo.update.assert_not_awaited()  # 树平移靠 pin 转移，不 UPDATE root_location
        mock_repo.delete.assert_awaited_once_with(m.id.int)
        mock_asset_store.delete.assert_awaited_once_with(m.image_path)  # 子图文件保留


class TestPassthroughQueries:
    """list_maps / get_map / children — 透传 repo（UUID→int）。"""

    async def test_list_maps_forwards(self, service, mock_repo) -> None:
        """透传 repo.list（root_location_id 转 int；offset/limit/top_level_only 透传）."""
        m = _map(name="清河县城图")
        root = uuid.uuid4()
        mock_repo.list = AsyncMock(return_value=([m], 1))
        result = await service.list_maps(
            PID, root_location_id=root, top_level_only=True, offset=10, limit=20
        )
        assert result == ([m], 1)
        kwargs = mock_repo.list.await_args.kwargs
        assert kwargs["project_id"] == PID.int
        assert kwargs["root_location_id"] == root.int
        assert kwargs["top_level_only"] is True
        assert kwargs["offset"] == 10
        assert kwargs["limit"] == 20

    async def test_get_map_forwards(self, service, mock_repo) -> None:
        """透传 repo.get(map_id)（不存在 → None，router 转 404）."""
        m = _map(name="清河县城图")
        mock_repo.get = AsyncMock(return_value=m)
        assert await service.get_map(m.id) is m
        mock_repo.get.assert_awaited_once_with(m.id.int)

    async def test_children_forwards(self, service, mock_repo) -> None:
        """透传 repo.children(map_id)（drill-down 子地图；地点软删过滤由 repo 保证）."""
        child = _map(name="清河县城坊市图")
        map_id = uuid.uuid4()
        mock_repo.children = AsyncMock(return_value=[child])
        assert await service.children(map_id) == [child]
        mock_repo.children.assert_awaited_once_with(map_id.int)


class TestPins:
    """add_pin / list_pins / update_pin / delete_pin — 位置校验 + 透传（spec §5.4）。"""

    async def test_add_pin_map_missing_raises(self, service, mock_repo) -> None:
        """① repo.get(map_id) → None → MapNotFoundError（404 语义）."""
        with pytest.raises(MapNotFoundError):
            await service.add_pin(uuid.uuid4(), None, 42.5, 68.0, "清河县城")
        mock_repo.add_pin.assert_not_awaited()

    async def test_add_pin_location_invalid_raises(
        self, service, mock_repo, mock_world_repo
    ) -> None:
        """② location_id 提供 → world_repo.get(loc) None 或跨项目 → MapPinLocationNotFoundError."""
        m = _map(name="清河县城图")
        mock_repo.get = AsyncMock(return_value=m)
        loc = uuid.uuid4()
        with pytest.raises(MapPinLocationNotFoundError):  # 地点不存在
            await service.add_pin(m.id, loc, 42.5, 68.0, "清河县城")
        mock_world_repo.get = AsyncMock(return_value=_setting("他国", project_id=OTHER_PID))
        with pytest.raises(MapPinLocationNotFoundError):  # 跨项目
            await service.add_pin(m.id, loc, 42.5, 68.0, "清河县城")
        mock_repo.add_pin.assert_not_awaited()

    async def test_add_pin_success(self, service, mock_repo, mock_world_repo) -> None:
        """③ 成功: repo.add_pin(MapPin(map_id=m.id, location_id, x, y, label)) 返回."""
        m = _map(name="清河县城图")
        loc = uuid.uuid4()
        mock_repo.get = AsyncMock(return_value=m)
        mock_world_repo.get = AsyncMock(return_value=_setting("清河县城"))
        result = await service.add_pin(m.id, loc, 42.5, 68.0, "清河县城")
        pin = mock_repo.add_pin.await_args.args[0]
        assert isinstance(pin, MapPin)
        assert pin.map_id == m.id
        assert pin.location_id == loc
        assert pin.x == 42.5 and pin.y == 68.0
        assert pin.label == "清河县城"
        assert result is pin
        mock_world_repo.get.assert_awaited_once_with(loc.int)

    async def test_list_pins_forwards(self, service, mock_repo) -> None:
        """透传 repo.list_pins(map_id)；map 不存在返回空列表，无 404 校验（get 不调用）."""
        pins = [_pin(), _pin()]
        mock_repo.list_pins = AsyncMock(return_value=pins)
        assert await service.list_pins(uuid.uuid4()) == pins
        mock_repo.list_pins.assert_awaited_once()
        mock_repo.get.assert_not_awaited()

    async def test_update_pin_missing_returns_none(self, service, mock_repo) -> None:
        """① repo.get_pin → None → 返回 None（router 转 404）."""
        mock_repo.get_pin = AsyncMock(return_value=None)
        assert await service.update_pin(uuid.uuid4(), MapPinUpdate(x=60.0)) is None

    async def test_update_pin_location_not_found_raises(
        self, service, mock_repo, mock_world_repo
    ) -> None:
        """② location_id 出现且非 None → world_repo.get 校验 → MapPinLocationNotFoundError."""
        mock_repo.get_pin = AsyncMock(return_value=_pin(map_id=uuid.uuid4()))
        mock_world_repo.get = AsyncMock(return_value=None)
        with pytest.raises(MapPinLocationNotFoundError):
            await service.update_pin(uuid.uuid4(), MapPinUpdate(location_id=uuid.uuid4()))

    async def test_update_pin_success_passthrough(self, service, mock_repo) -> None:
        """③ 透传: get_pin 取现有 → 合并 update → repo.update_pin(完整 MapPin) 返回."""
        existing = _pin(x=50.0, y=50.0, label="清河县城", map_id=uuid.uuid4())
        updated = existing.model_copy(update={"x": 60.0})
        mock_repo.get_pin = AsyncMock(return_value=existing)
        mock_repo.update_pin = AsyncMock(return_value=updated)
        result = await service.update_pin(existing.id, MapPinUpdate(x=60.0))
        assert result is updated
        mock_repo.get_pin.assert_awaited_once_with(existing.id.int)
        pin_arg = mock_repo.update_pin.await_args.args[0]
        assert isinstance(pin_arg, MapPin)
        assert pin_arg.id == existing.id
        assert pin_arg.x == 60.0
        assert pin_arg.label == "清河县城"

    async def test_delete_pin_forwards(self, service, mock_repo) -> None:
        """透传 repo.delete_pin(pin_id)（真删单行，无级联）."""
        pin_id = uuid.uuid4()
        mock_repo.delete_pin = AsyncMock(return_value=True)
        assert await service.delete_pin(pin_id) is True
        mock_repo.delete_pin.assert_awaited_once_with(pin_id.int)


class TestCleanupHooks:
    """项目/地点硬删钩子（D10=b 显式级联，spec §5.4）。"""

    async def test_cleanup_project_deletes_db_then_files(
        self, service, mock_repo, mock_asset_store
    ) -> None:
        """① list_maps_by_project(pid) 收集 → ② delete_by_project 单事务删 pins+maps →
        ③ 每张图 delete(image_path)（失败 warning 不阻断）→ ④ 返回 len(maps)."""
        m1 = _map(name="清河县城图", image_path="maps/1/main.png")
        m2 = _map(name="青州全图", image_path="maps/2/main.png")
        mock_repo.list_maps_by_project = AsyncMock(return_value=[m1, m2])
        mock_repo.delete_by_project = AsyncMock(return_value=2)
        result = await service.cleanup_project(PID)
        assert result == 2
        mock_repo.list_maps_by_project.assert_awaited_once_with(PID.int)
        mock_repo.delete_by_project.assert_awaited_once_with(PID.int)
        mock_asset_store.delete.assert_any_await(m1.image_path)
        mock_asset_store.delete.assert_any_await(m2.image_path)
        assert mock_asset_store.delete.await_count == 2

    async def test_clear_location_pins_accumulates(self, service, mock_repo) -> None:
        """循环 repo.clear_location_pins(loc) 累加返回更新行数（硬删地点 → pin SET NULL）."""
        loc1, loc2 = uuid.uuid4(), uuid.uuid4()
        mock_repo.clear_location_pins = AsyncMock(side_effect=[3, 5])
        result = await service.clear_location_pins([loc1, loc2])
        assert result == 8
        assert mock_repo.clear_location_pins.await_args_list[0].args[0] == loc1.int
        assert mock_repo.clear_location_pins.await_args_list[1].args[0] == loc2.int


class TestMapErrorsModule:
    """错误类导出与默认文案（F16 遮蔽防护 + spec §3.3 异常映射表）。"""

    def test_map_errors_does_not_export_project_not_found(self) -> None:
        """map_errors【不导出】ProjectNotFoundError（复用 world_errors——F16 双入口教训）."""
        import inkflow.domain.ports.map_errors as map_errors_module

        assert not hasattr(map_errors_module, "ProjectNotFoundError")

    def test_error_default_messages(self) -> None:
        """默认消息文案逐字（父侧定稿契约，GREEN 实现按此落地）."""
        assert str(MapNameConflictError()) == "同名地图已存在（项目内）"
        assert str(MapRootLocationConflictError()) == "该地点已挂有一张地图"
        assert str(MapRootLocationNotFoundError()) == "父地点不存在或不在同一项目"
        assert str(MapPinLocationNotFoundError()) == "pin 关联地点不存在或不在同一项目"
        assert str(MapChildrenActionRequiredError()) == (
            "该地图存在子地图，必须指定 cascade=true（级联删除）或 "
            "reparent_to=<map_id>（子地图改挂新父）"
        )
        assert str(MapReparentTargetError()) == (
            "reparent 目标地图不存在/不在同一项目/是自身子孙地图"
        )
        assert str(MapNotFoundError()) == "地图不存在"
        assert str(MapPinNotFoundError()) == "pin 不存在"
        # 归属: 422 业务错误继承 MapServiceError；404/500 错误不继承
        assert issubclass(MapNameConflictError, MapServiceError)
        assert issubclass(MapRootLocationConflictError, MapServiceError)
        assert issubclass(MapRootLocationNotFoundError, MapServiceError)
        assert issubclass(MapPinLocationNotFoundError, MapServiceError)
        assert issubclass(MapChildrenActionRequiredError, MapServiceError)
        assert issubclass(MapReparentTargetError, MapServiceError)
        assert not issubclass(MapNotFoundError, MapServiceError)
        assert not issubclass(MapPinNotFoundError, MapServiceError)
        assert not issubclass(MapAssetError, MapServiceError)
