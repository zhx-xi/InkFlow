"""F37 世界观跨书复制服务单元测试 — WorldCopyService（RED 阶段，只写测试不改 src/）.

被测类: inkflow.domain.services.copy_service.WorldCopyService（尚未实现——本文件为 RED 契约）。
镜像: tests/unit/test_map_service.py（F36）——service 层全 mock（AsyncMock）；fixture 全部
方法显式设默认值（裸 AsyncMock 陷阱: 未配置方法返回 child mock，真值判断静默错）。

RED 预期: 收集期 ModuleNotFoundError: No module named 'inkflow.domain.services.copy_service'
（顶部 import 主契约模块 = 预期 RED；错误类 stub 先于主 import 吞自身 ImportError）。

设计假设（父侧定稿契约——GREEN 实现按此落地，逐字记录）:

【domain/models/copy.py（CREATE）】
class WorldCopyRequest(BaseModel):
    source_project_id: uuid.UUID
    root_setting_id: uuid.UUID | None = None

class WorldCopyResult(BaseModel):
    created: list[WorldSetting]
    skipped: list[str]
    maps_created: list[WorldMap]
    pins_created: int
    warnings: list[str]

【domain/services/copy_service.py（CREATE）】
class WorldCopyService:
    def __init__(self, *, repository: WorldRepositoryProtocol,
                 project_repo: ProjectRepositoryProtocol,
                 map_repo: MapRepositoryProtocol | None = None,
                 asset_store: MapAssetStoreProtocol | None = None) -> None
    async def copy(self, source_project_id: int | uuid.UUID,
                   target_project_id: int | uuid.UUID,
                   root_setting_id: int | uuid.UUID | None = None) -> WorldCopyResult

【world_errors.py 新增（继承 Exception，非 WorldServiceError——404 语义）】
class CopySourceNotFoundError(Exception): 默认文案「源项目不存在」
class CopyRootNotFoundError(Exception):   默认文案「复制起点条目不存在或不在源项目」

【复制算法（spec §5.1，测试断言依据）】
copy(source_pid, target_pid, root_id=None):
  ① project_repo.get(target_int) → None → ProjectNotFoundError（复用 world_errors）
  ② project_repo.get(source_int) → None → CopySourceNotFoundError
  ③ root_id 提供 → repository.get(root_int) → None 或 setting.project_id != source
     → CopyRootNotFoundError；复制集合 = repository.list_descendants(root_int)（含自身层序）
     缺省 → repository.list_all_active(source_int)（created_at ASC 稳定排序，
     契约见 test_world_repo.py TestListAllActive）
  ④ 冲突预筛（层序遍历）: 对每个源条目 parent_new = id_map.get(src.parent_id.int)
     （父被跳过/不在集合 → None）→ repository.get_by_parent_and_name(target_int,
     parent_new_int, name) 命中 → skipped.append(name) + warning，不入映射
  ⑤ 落库: 逐个 add（新 UUID + project_id=target + parent_id 经 old→new 映射 +
     name/category/content/extra 原样）→ id_map[src.id.int] = new_id
  ⑥ 地图复制（map_repo 与 asset_store 均非 None 才执行）:
     maps = map_repo.list_by_root_locations(source_int, [复制地点 id ints],
                                            include_global=True)
     每个源图: map_repo.get_by_name(target_int, name) 命中 → 跳过 + warning
       asset_store.copy(src.image_path, map_id=new_uuid) 抛 MapAssetError → 跳过
       + warning（DB 行不复制）
       map_repo.add（关联图 root_location_id 重映射 / 全局图保持 None）→ maps_created
       pins: map_repo.list_pins(src_map.id.int) → 每个 pin:
         location_id ∈ 映射 → 重映射；∉（或 None）→ 转纯注释（location_id=None，
         label/坐标保留）+ warning 汇总
         map_repo.add_pin（新 UUID + map_id 重映射）→ pins_created += 1
  ⑦ 落库阶段任何 repo 写方法抛错 → 异常原样传播（不吞错），复制立即中断，
     后续写操作零调用（fail-fast；mock 轨「单事务回滚」= 失败传播 + 失败点后
     零写调用，真实回滚由 GREEN 单事务承载——spec §7 边界 9）
  ⑧ 返回 WorldCopyResult(created=新条目列表, skipped=冲突源条目名,
     maps_created=新图列表, pins_created=N, warnings=[...])

【惰性 import 约定】WorldSetting/WorldMap/MapPin 工厂在函数体内惰性 import（RED 阶段
仅主契约顶部 import——收集错误唯一聚焦 copy_service）；工厂返回注解省略（F821 防护）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

try:
    from inkflow.domain.ports.world_errors import (
        CopyRootNotFoundError,
        CopySourceNotFoundError,
        ProjectNotFoundError,
    )
except ImportError:  # pragma: no cover  # F37 错误类未落地——stub 吞自身 ImportError
    CopyRootNotFoundError = type("CopyRootNotFoundError", (Exception,), {})
    CopySourceNotFoundError = type("CopySourceNotFoundError", (Exception,), {})
    ProjectNotFoundError = type("ProjectNotFoundError", (Exception,), {})

from inkflow.domain.ports.map_errors import MapAssetError
from inkflow.domain.ports.map_repository import MapRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_errors import WorldServiceError
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.copy_service import WorldCopyService

SOURCE_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TARGET_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
OTHER_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000003")  # 跨项目校验用
SOURCE_INT = SOURCE_PID.int
TARGET_INT = TARGET_PID.int
TS = datetime(2026, 8, 1, 10, 0, 0)


def _setting(
    name: str, *, project_id: uuid.UUID = SOURCE_PID, parent_id: uuid.UUID | None = None, **kw
):
    """构造测试用世界观条目（惰性 import 领域模型；工厂返回注解省略防 F821）."""
    from inkflow.domain.models.world import WorldSetting  # 惰性：RED 阶段仅主契约顶部 import

    values = {
        "id": uuid.uuid4(),
        "project_id": project_id,
        "name": name,
        "category": "",
        "content": "",
        "extra": {"scale": 1.0},
        "is_deleted": False,
        "parent_id": parent_id,
        "created_at": TS,
        "updated_at": TS,
    }
    values.update(kw)
    return WorldSetting(**values)


def _map(
    name: str, *, project_id: uuid.UUID = SOURCE_PID, root_location_id: uuid.UUID | None = None
):
    """构造测试用地图实体（惰性 import；工厂返回注解省略防 F821）."""
    from inkflow.domain.models.map import WorldMap  # 惰性：RED 阶段仅主契约顶部 import

    return WorldMap(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        image_path="maps/src/main.png",
        description="",
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
    label: str = "pin",
):
    """构造测试用 pin 实体（惰性 import；工厂返回注解省略防 F821）."""
    from inkflow.domain.models.map import MapPin  # 惰性：RED 阶段仅主契约顶部 import

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


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock WorldRepositoryProtocol — 全部方法显式默认值（裸 AsyncMock 陷阱防护）.

    list_all_active/list_pins 为 F37 新增（Protocol 扩展），spec 外属性可设置（F35 实测）。
    """
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.add = AsyncMock(side_effect=lambda s: s)
    repo.list_all_active = AsyncMock(return_value=[])
    repo.list_descendants = AsyncMock(return_value=[])
    repo.get_by_parent_and_name = AsyncMock(return_value=None)
    repo.list_pins = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — 目标/源项目均存在（按 int 分发）；错误用例覆写."""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(
        side_effect=lambda pid: SimpleNamespace(id=pid) if pid in (SOURCE_INT, TARGET_INT) else None
    )
    return repo


@pytest.fixture
def mock_map_repo() -> MagicMock:
    """Mock MapRepositoryProtocol — 地图复制默认零图零 pin."""
    repo = MagicMock(spec=MapRepositoryProtocol)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list_by_root_locations = AsyncMock(return_value=[])
    repo.add = AsyncMock(side_effect=lambda m: m)
    repo.list_pins = AsyncMock(return_value=[])
    repo.add_pin = AsyncMock(side_effect=lambda p: p)
    return repo


@pytest.fixture
def mock_asset_store() -> MagicMock:
    """Mock MapAssetStoreProtocol — copy 返回固定新相对路径."""
    store = MagicMock()
    store.copy = AsyncMock(return_value="maps/copied/main.png")
    return store


@pytest.fixture
def service(mock_repo, mock_project_repo, mock_map_repo, mock_asset_store) -> WorldCopyService:
    """被测 WorldCopyService 实例（全 Mock 依赖注入）."""
    return WorldCopyService(
        repository=mock_repo,
        project_repo=mock_project_repo,
        map_repo=mock_map_repo,
        asset_store=mock_asset_store,
    )


class TestTreeCopy:
    """整棵/子树复制 — 层序、parent 映射、字段原样（spec §9 场景 1/2 + §2 语义规则 3）."""

    async def test_full_tree_three_levels(self, service, mock_repo) -> None:
        """整棵 3 层树: created 3 条、parent 映射正确、字段原样（extra.scale）、顶层 None."""
        from inkflow.domain.models.copy import WorldCopyResult  # 惰性：RED 阶段模块未实现

        country = _setting("大越国", category="地理", content="国", extra={"scale": 1.0})
        state = _setting("青州", parent_id=country.id)
        county = _setting("清河县城", parent_id=state.id)
        mock_repo.list_all_active = AsyncMock(return_value=[country, state, county])

        result = await service.copy(SOURCE_PID, TARGET_PID)

        assert isinstance(result, WorldCopyResult)
        calls = mock_repo.add.await_args_list
        assert len(calls) == 3
        c_new, s_new, t_new = (c.args[0] for c in calls)
        assert c_new.parent_id is None
        assert s_new.parent_id == c_new.id
        assert t_new.parent_id == s_new.id
        assert c_new.project_id == TARGET_PID
        assert c_new.name == "大越国" and c_new.category == "地理" and c_new.content == "国"
        assert c_new.extra == {"scale": 1.0}
        assert [s.id for s in result.created] == [c_new.id, s_new.id, t_new.id]
        assert result.skipped == []
        mock_repo.list_all_active.assert_awaited_once_with(SOURCE_INT)
        mock_repo.list_descendants.assert_not_awaited()
        assert mock_repo.get_by_parent_and_name.await_count == 3

    async def test_subtree_with_root_copies_state_and_county(self, service, mock_repo) -> None:
        """子树复制: root=州 → 州+县复制、国不复制；州 parent 不在集合 → 目标顶层."""
        country = _setting("大越国")
        state = _setting("青州", parent_id=country.id)
        county = _setting("清河县城", parent_id=state.id)
        mock_repo.get = AsyncMock(side_effect=lambda sid: state if sid == state.id.int else None)
        mock_repo.list_descendants = AsyncMock(return_value=[state, county])

        result = await service.copy(SOURCE_PID, TARGET_PID, root_setting_id=state.id)

        calls = mock_repo.add.await_args_list
        assert len(calls) == 2
        s_new, t_new = (c.args[0] for c in calls)
        assert s_new.name == "青州"
        assert s_new.parent_id is None  # 国不在复制集合 → 置顶层
        assert t_new.parent_id == s_new.id
        assert [s.name for s in result.created] == ["青州", "清河县城"]
        mock_repo.get.assert_awaited_once_with(state.id.int)
        mock_repo.list_descendants.assert_awaited_once_with(state.id.int)
        mock_repo.list_all_active.assert_not_awaited()

    async def test_default_uses_list_all_active(self, service, mock_repo) -> None:
        """缺省 root → list_all_active(source) 取整棵；list_descendants 不调用."""
        country = _setting("大越国")
        mock_repo.list_all_active = AsyncMock(return_value=[country])

        result = await service.copy(SOURCE_PID, TARGET_PID)

        assert [s.name for s in result.created] == ["大越国"]
        mock_repo.list_all_active.assert_awaited_once_with(SOURCE_INT)
        mock_repo.list_descendants.assert_not_awaited()

    async def test_root_missing_or_cross_project_raises(self, service, mock_repo) -> None:
        """③ root 校验: repository.get → None 或 project_id != source → CopyRootNotFoundError."""
        root = uuid.uuid4()
        with pytest.raises(CopyRootNotFoundError):  # 不存在
            await service.copy(SOURCE_PID, TARGET_PID, root_setting_id=root)
        mock_repo.get = AsyncMock(return_value=_setting("他国", project_id=OTHER_PID))
        with pytest.raises(CopyRootNotFoundError):  # 跨项目
            await service.copy(SOURCE_PID, TARGET_PID, root_setting_id=root)
        mock_repo.add.assert_not_awaited()
        mock_repo.list_descendants.assert_not_awaited()

    async def test_copy_accepts_int_ids(self, service, mock_repo) -> None:
        """int 入参分支（_to_int_id 直通）: copy(SOURCE_INT, TARGET_INT) → 正常复制."""
        country = _setting("大越国")
        mock_repo.list_all_active = AsyncMock(return_value=[country])

        result = await service.copy(SOURCE_INT, TARGET_INT)

        assert len(result.created) == 1
        assert result.created[0].name == "大越国"
        assert result.created[0].project_id == TARGET_PID  # int target → UUID 落库
        mock_repo.list_all_active.assert_awaited_once_with(SOURCE_INT)


class TestConflictSkip:
    """名称冲突预筛（spec §7 边界 4/5）— 跳过 + warning，不覆盖目标."""

    async def test_same_name_target_skipped_others_copied(self, service, mock_repo) -> None:
        """目标已有同名（同父）→ skipped=[名] + warning；其余复制；add 不覆盖目标."""
        country = _setting("大越国")
        state = _setting("青州", parent_id=country.id)
        mock_repo.list_all_active = AsyncMock(return_value=[country, state])
        existing = _setting("青州", project_id=TARGET_PID)
        mock_repo.get_by_parent_and_name = AsyncMock(
            side_effect=lambda pid, parent, name: existing if name == "青州" else None
        )

        result = await service.copy(SOURCE_PID, TARGET_PID)

        assert result.skipped == ["青州"]
        assert [s.name for s in result.created] == ["大越国"]
        mock_repo.add.assert_awaited_once()  # 青州未落库（不覆盖目标既有内容）
        assert any("青州" in w for w in result.warnings)

    async def test_parent_skipped_child_promoted(self, service, mock_repo) -> None:
        """父被跳过 → 子 parent_id=None（置顶）+ warning；子树仍完整复制."""
        country = _setting("大越国")
        state = _setting("青州", parent_id=country.id)
        county = _setting("清河县城", parent_id=state.id)
        mock_repo.list_all_active = AsyncMock(return_value=[country, state, county])
        existing = _setting("大越国", project_id=TARGET_PID)
        mock_repo.get_by_parent_and_name = AsyncMock(
            side_effect=lambda pid, parent, name: existing if name == "大越国" else None
        )

        result = await service.copy(SOURCE_PID, TARGET_PID)

        assert result.skipped == ["大越国"]
        calls = mock_repo.add.await_args_list
        s_new, t_new = (c.args[0] for c in calls)
        assert s_new.parent_id is None  # 父无映射 → 置顶
        assert t_new.parent_id == s_new.id
        assert any("大越国" in w for w in result.warnings)

    async def test_prescreen_uses_target_and_mapped_parent(self, service, mock_repo) -> None:
        """冲突预筛: get_by_parent_and_name(target, 映射后父 id, name)——父先落库再预筛子."""
        country = _setting("大越国")
        state = _setting("青州", parent_id=country.id)
        mock_repo.list_all_active = AsyncMock(return_value=[country, state])

        await service.copy(SOURCE_PID, TARGET_PID)

        calls = mock_repo.get_by_parent_and_name.await_args_list
        assert len(calls) == 2
        assert calls[0] == call(TARGET_INT, None, "大越国")
        c_new = mock_repo.add.await_args_list[0].args[0]
        assert calls[1] == call(TARGET_INT, c_new.id.int, "青州")


class TestMapCopy:
    """地图复制（F36 依赖，spec §5.1 ⑥ / §9 场景 5/6）— 关联图/全局图/pin 处理."""

    async def test_linked_map_remaps_root_location(
        self, service, mock_repo, mock_map_repo, mock_asset_store
    ) -> None:
        """关联图: list_by_root_locations(源, 复制地点 ints, include_global=True) →
        copy 文件 → add（root 重映射到新地点）→ maps_created."""
        country = _setting("大越国")
        state = _setting("青州", parent_id=country.id)
        county = _setting("清河县城", parent_id=state.id)
        mock_repo.list_all_active = AsyncMock(return_value=[country, state, county])
        src_map = _map("清河县城图", root_location_id=county.id)
        mock_map_repo.list_by_root_locations = AsyncMock(return_value=[src_map])

        result = await service.copy(SOURCE_PID, TARGET_PID)

        loc_call = mock_map_repo.list_by_root_locations.await_args
        assert loc_call.args[0] == SOURCE_INT
        assert set(loc_call.args[1]) == {country.id.int, state.id.int, county.id.int}
        assert loc_call.kwargs.get("include_global", True) is not False
        added = mock_map_repo.add.await_args.args[0]
        assert added.project_id == TARGET_PID
        assert added.name == "清河县城图"
        c_new = mock_repo.add.await_args_list[2].args[0]
        assert added.root_location_id == c_new.id  # 关联图 root 重映射
        assert added.image_path == "maps/copied/main.png"  # copy 返回的新路径
        mock_asset_store.copy.assert_awaited_once_with(src_map.image_path, map_id=added.id)
        assert result.maps_created == [added]

    async def test_global_map_keeps_root_none(self, service, mock_repo, mock_map_repo) -> None:
        """全局图（root NULL，Q3=B）: root 保持 None（目标项目全局图）."""
        country = _setting("大越国")
        mock_repo.list_all_active = AsyncMock(return_value=[country])
        src_global = _map("世界观总览图")
        mock_map_repo.list_by_root_locations = AsyncMock(return_value=[src_global])

        result = await service.copy(SOURCE_PID, TARGET_PID)

        added = mock_map_repo.add.await_args.args[0]
        assert added.root_location_id is None
        assert added.name == "世界观总览图"
        assert result.maps_created == [added]
        assert result.pins_created == 0

    async def test_global_map_pin_remaps_in_set(self, service, mock_repo, mock_map_repo) -> None:
        """全局图 + pin 关联复制集合内地点 → 目标 root NULL、pin 重挂（Q3=B，§9 场景 6）."""
        country = _setting("大越国")
        mock_repo.list_all_active = AsyncMock(return_value=[country])
        src_global = _map("世界观总览图")
        mock_map_repo.list_by_root_locations = AsyncMock(return_value=[src_global])
        src_pin = _pin(map_id=src_global.id, location_id=country.id, label="国都")
        mock_map_repo.list_pins = AsyncMock(return_value=[src_pin])

        result = await service.copy(SOURCE_PID, TARGET_PID)

        added = mock_map_repo.add.await_args.args[0]
        assert added.root_location_id is None
        pin = mock_map_repo.add_pin.await_args.args[0]
        c_new = mock_repo.add.await_args.args[0]
        assert pin.location_id == c_new.id
        assert result.pins_created == 1
        assert result.warnings == []  # 全部重挂 → 无转纯注释 warning

    async def test_subtree_map_query_uses_subtree_locations(
        self, service, mock_repo, mock_map_repo
    ) -> None:
        """子树复制时 list_by_root_locations 只收到子树地点 ints（国不在集合不查询其图）."""
        country = _setting("大越国")
        state = _setting("青州", parent_id=country.id)
        county = _setting("清河县城", parent_id=state.id)
        mock_repo.get = AsyncMock(side_effect=lambda sid: state if sid == state.id.int else None)
        mock_repo.list_descendants = AsyncMock(return_value=[state, county])

        await service.copy(SOURCE_PID, TARGET_PID, root_setting_id=state.id)

        loc_call = mock_map_repo.list_by_root_locations.await_args
        assert set(loc_call.args[1]) == {state.id.int, county.id.int}
        assert country.id.int not in loc_call.args[1]

    async def test_pin_remaps_location_in_set(self, service, mock_repo, mock_map_repo) -> None:
        """pin 关联地点在复制集合 → 重挂新地点；label/坐标保留；pins_created 计数."""
        country = _setting("大越国")
        state = _setting("青州", parent_id=country.id)
        county = _setting("清河县城", parent_id=state.id)
        mock_repo.list_all_active = AsyncMock(return_value=[country, state, county])
        src_map = _map("清河县城图", root_location_id=county.id)
        mock_map_repo.list_by_root_locations = AsyncMock(return_value=[src_map])
        src_pin = _pin(map_id=src_map.id, location_id=county.id, x=33.0, y=44.0, label="县城")
        mock_map_repo.list_pins = AsyncMock(return_value=[src_pin])

        result = await service.copy(SOURCE_PID, TARGET_PID)

        added = mock_map_repo.add.await_args.args[0]
        c_new = mock_repo.add.await_args_list[2].args[0]
        pin = mock_map_repo.add_pin.await_args.args[0]
        assert pin.map_id == added.id
        assert pin.location_id == c_new.id  # 重挂新地点
        assert pin.x == 33.0 and pin.y == 44.0 and pin.label == "县城"
        assert result.pins_created == 1

    async def test_pin_outside_set_becomes_note(self, service, mock_repo, mock_map_repo) -> None:
        """pin 关联地点不在复制集合 → 转纯注释（location=None，label/坐标保留）+ warning."""
        country = _setting("大越国")
        mock_repo.list_all_active = AsyncMock(return_value=[country])
        src_map = _map("清河县城图", root_location_id=country.id)
        mock_map_repo.list_by_root_locations = AsyncMock(return_value=[src_map])
        outside = uuid.uuid4()
        src_pin = _pin(map_id=src_map.id, location_id=outside, x=10.0, y=20.0, label="城外")
        mock_map_repo.list_pins = AsyncMock(return_value=[src_pin])

        result = await service.copy(SOURCE_PID, TARGET_PID)

        pin = mock_map_repo.add_pin.await_args.args[0]
        assert pin.location_id is None
        assert pin.x == 10.0 and pin.y == 20.0 and pin.label == "城外"
        assert result.pins_created == 1
        assert any("纯注释" in w for w in result.warnings)

    async def test_note_pin_stays_note(self, service, mock_repo, mock_map_repo) -> None:
        """纯注释 pin（location 本就 None）→ 保持 None，label/坐标保留."""
        country = _setting("大越国")
        mock_repo.list_all_active = AsyncMock(return_value=[country])
        src_map = _map("清河县城图", root_location_id=country.id)
        mock_map_repo.list_by_root_locations = AsyncMock(return_value=[src_map])
        src_pin = _pin(map_id=src_map.id, location_id=None, x=5.0, y=6.0, label="注释")
        mock_map_repo.list_pins = AsyncMock(return_value=[src_pin])

        result = await service.copy(SOURCE_PID, TARGET_PID)

        pin = mock_map_repo.add_pin.await_args.args[0]
        assert pin.location_id is None
        assert pin.x == 5.0 and pin.y == 6.0 and pin.label == "注释"
        assert result.pins_created == 1

    async def test_target_map_name_conflict_skips_map(
        self, service, mock_repo, mock_map_repo, mock_asset_store
    ) -> None:
        """目标已有同名图 → 该图跳过 + warning（add/copy 不调用）；条目复制照常."""
        country = _setting("大越国")
        mock_repo.list_all_active = AsyncMock(return_value=[country])
        src_map = _map("清河县城图", root_location_id=country.id)
        mock_map_repo.list_by_root_locations = AsyncMock(return_value=[src_map])
        mock_map_repo.get_by_name = AsyncMock(
            return_value=_map("清河县城图", project_id=TARGET_PID)
        )

        result = await service.copy(SOURCE_PID, TARGET_PID)

        assert [s.name for s in result.created] == ["大越国"]
        assert result.maps_created == []
        mock_map_repo.add.assert_not_awaited()
        mock_asset_store.copy.assert_not_awaited()
        assert any("清河县城图" in w for w in result.warnings)

    async def test_asset_copy_failure_skips_map(
        self, service, mock_repo, mock_map_repo, mock_asset_store
    ) -> None:
        """asset_store.copy 抛 MapAssetError → 该图跳过 + warning（DB 行不复制）；条目照常."""
        country = _setting("大越国")
        mock_repo.list_all_active = AsyncMock(return_value=[country])
        src_map = _map("清河县城图", root_location_id=country.id)
        mock_map_repo.list_by_root_locations = AsyncMock(return_value=[src_map])
        mock_asset_store.copy = AsyncMock(side_effect=MapAssetError("源文件缺失"))

        result = await service.copy(SOURCE_PID, TARGET_PID)

        assert [s.name for s in result.created] == ["大越国"]
        assert result.maps_created == []
        mock_map_repo.add.assert_not_awaited()
        assert any("清河县城图" in w for w in result.warnings)

    async def test_map_repo_none_defensive(self, mock_repo, mock_project_repo) -> None:
        """F36 未合入防御（spec §7 边界 12）: map_repo=None → 地图复制静默跳过、条目照常."""
        country = _setting("大越国")
        mock_repo.list_all_active = AsyncMock(return_value=[country])
        svc = WorldCopyService(repository=mock_repo, project_repo=mock_project_repo)

        result = await svc.copy(SOURCE_PID, TARGET_PID)

        assert [s.name for s in result.created] == ["大越国"]
        assert result.maps_created == [] and result.pins_created == 0
        assert result.warnings == []


class TestRollbackAndEmptySource:
    """失败传播（spec §7 边界 9）与空源（边界 6）."""

    async def test_add_failure_propagates_stops_writes(
        self, service, mock_repo, mock_map_repo, mock_asset_store
    ) -> None:
        """落库中途 add 抛错 → 异常原样传播；失败点后零写调用（fail-fast）.

        mock 轨「单事务回滚」= 失败传播 + 失败点后零写调用（真实回滚由 GREEN
        单事务承载——spec §7 边界 9）.
        """
        country = _setting("大越国")
        state = _setting("青州", parent_id=country.id)
        county = _setting("清河县城", parent_id=state.id)
        mock_repo.list_all_active = AsyncMock(return_value=[country, state, county])
        added = []

        def _flaky(s):
            added.append(s)
            if len(added) == 2:
                raise RuntimeError("db down")
            return s

        mock_repo.add = AsyncMock(side_effect=_flaky)

        with pytest.raises(RuntimeError, match="db down"):
            await service.copy(SOURCE_PID, TARGET_PID)

        assert mock_repo.add.await_count == 2
        mock_map_repo.add.assert_not_awaited()
        mock_map_repo.add_pin.assert_not_awaited()
        mock_asset_store.copy.assert_not_awaited()

    async def test_empty_source_returns_empty_report(self, service, mock_repo) -> None:
        """空源（list_all_active=[]）→ 空报告 created/skipped/maps_created=[]、
        pins_created=0、warnings=[]——非错误（spec §7 边界 6）."""
        result = await service.copy(SOURCE_PID, TARGET_PID)

        assert result.created == [] and result.skipped == []
        assert result.maps_created == [] and result.pins_created == 0
        assert result.warnings == []
        mock_repo.add.assert_not_awaited()


class TestProjectValidation:
    """项目存在性校验（spec §3.3 异常映射表）— ①②."""

    async def test_target_project_missing_raises(
        self, service, mock_project_repo, mock_repo
    ) -> None:
        """① 目标项目不存在 → ProjectNotFoundError；零写入."""
        mock_project_repo.get = AsyncMock(
            side_effect=lambda pid: SimpleNamespace(id=pid) if pid == SOURCE_INT else None
        )
        with pytest.raises(ProjectNotFoundError):
            await service.copy(SOURCE_PID, TARGET_PID)
        mock_repo.add.assert_not_awaited()

    async def test_source_project_missing_raises(
        self, service, mock_project_repo, mock_repo
    ) -> None:
        """② 源项目不存在 → CopySourceNotFoundError；零写入."""
        mock_project_repo.get = AsyncMock(
            side_effect=lambda pid: SimpleNamespace(id=pid) if pid == TARGET_INT else None
        )
        with pytest.raises(CopySourceNotFoundError):
            await service.copy(SOURCE_PID, TARGET_PID)
        mock_repo.add.assert_not_awaited()


class TestCopyDtos:
    """复制请求/结果 DTO 契约（domain/models/copy.py，spec §2）."""

    def test_copy_request_dto_fields(self) -> None:
        """WorldCopyRequest: source_project_id 必填、root_setting_id 缺省 None."""
        from inkflow.domain.models.copy import WorldCopyRequest  # 惰性：RED 阶段模块未实现

        req = WorldCopyRequest(source_project_id=SOURCE_PID)
        assert req.source_project_id == SOURCE_PID
        assert req.root_setting_id is None


class TestCopyErrorsModule:
    """Copy 错误类默认文案与继承（world_errors 新增，404 语义）."""

    def test_error_default_messages_and_hierarchy(self) -> None:
        """默认文案逐字 + 继承 Exception 非 WorldServiceError（404 语义）."""
        assert str(CopySourceNotFoundError()) == "源项目不存在"
        assert str(CopyRootNotFoundError()) == "复制起点条目不存在或不在源项目"
        assert issubclass(CopySourceNotFoundError, Exception)
        assert issubclass(CopyRootNotFoundError, Exception)
        assert not issubclass(CopySourceNotFoundError, WorldServiceError)
        assert not issubclass(CopyRootNotFoundError, WorldServiceError)


class TestSelfOnlyCopy:
    """F43 P1 复制 self_only 分支契约（spec §2.5/§5.6）— 仅本体复制集合=[root].

    【RED 预期】copy 签名尚无 self_only 参数 → 显式传 self_only 触发 TypeError
    （FAILED）；缺省用例（守护）当前即 PASS——GREEN 后缺省 False 保持既有子树语义。
    契约锁定: self_only 以 kwargs 形态传入（copy(..., self_only=True)）。
    """

    async def test_self_only_true_copies_root_only(self, service, mock_repo, mock_map_repo) -> None:
        """root + self_only=True → 复制集合=[root]：list_descendants 不调用、仅 root 落库、
        map 查询自动收窄到 root（spec §2.5）."""
        country = _setting("大越国")
        state = _setting("青州", parent_id=country.id)
        county = _setting("清河县城", parent_id=state.id)
        mock_repo.get = AsyncMock(side_effect=lambda sid: state if sid == state.id.int else None)
        mock_repo.list_descendants = AsyncMock(return_value=[state, county])

        result = await service.copy(
            SOURCE_PID, TARGET_PID, root_setting_id=state.id, self_only=True
        )

        assert [s.name for s in result.created] == ["青州"]
        mock_repo.add.assert_awaited_once()
        mock_repo.list_descendants.assert_not_awaited()
        mock_repo.list_all_active.assert_not_awaited()
        loc_call = mock_map_repo.list_by_root_locations.await_args
        assert set(loc_call.args[1]) == {state.id.int}
        assert country.id.int not in loc_call.args[1]

    async def test_self_only_false_uses_descendants(self, service, mock_repo) -> None:
        """root + self_only=False（显式）→ list_descendants 被调用（既有子树语义不破坏）."""
        country = _setting("大越国")
        state = _setting("青州", parent_id=country.id)
        county = _setting("清河县城", parent_id=state.id)
        mock_repo.get = AsyncMock(side_effect=lambda sid: state if sid == state.id.int else None)
        mock_repo.list_descendants = AsyncMock(return_value=[state, county])

        result = await service.copy(
            SOURCE_PID, TARGET_PID, root_setting_id=state.id, self_only=False
        )

        assert [s.name for s in result.created] == ["青州", "清河县城"]
        mock_repo.list_descendants.assert_awaited_once_with(state.id.int)

    async def test_self_only_default_uses_descendants(self, service, mock_repo) -> None:
        """不传 self_only（缺省 False）→ 既有子树语义（守护用例，RED 阶段即 PASS）."""
        country = _setting("大越国")
        state = _setting("青州", parent_id=country.id)
        mock_repo.get = AsyncMock(side_effect=lambda sid: state if sid == state.id.int else None)
        mock_repo.list_descendants = AsyncMock(return_value=[state])

        result = await service.copy(SOURCE_PID, TARGET_PID, root_setting_id=state.id)

        assert [s.name for s in result.created] == ["青州"]
        mock_repo.list_descendants.assert_awaited_once_with(state.id.int)
