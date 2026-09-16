"""WorldService 数据面变更事件测试（#1090 批次 B；spec §15.3.2/§15.3.3/§15.6.4）。

契约来源：W3C 设计裁定表 §2.2（父侧单一真相源）+ spec §15.3.3 四不变量。
- world_setting：create/update/delete 三分支（cascade / reparent / 普通真删）各自成功后
  发**一条**事件；cascade 子树与 reparent 子改挂不逐条发（GUI 一次失效收敛）。
- world_category：create/rename（op="update"）/delete（薄透传 → None + warning）。
- extract（AI 提取）**不发**：批量内部写入走 extractor 管线（§15.6.4 中间态）。

依赖全 Mock 注入（镜像 test_world_service.py 的 fixture 形态）。
RED 阶段预期：正例断言 FAIL，负例可能已 PASS。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.project import Project
from inkflow.domain.models.world import (
    WorldCategory,
    WorldExtractRequest,
    WorldSetting,
    WorldUpdate,
)
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_errors import (
    WorldCategoryNameConflictError,
    WorldChildrenActionRequiredError,
    WorldNameConflictError,
)
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._world_extractor import WorldExtractor
from inkflow.domain.services.world_service import WorldService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
LOGGER_NAME = "inkflow.domain.services.world_service"


def _setting(
    name: str = "清河县城",
    *,
    project_id: uuid.UUID = PID,
    parent_id: uuid.UUID | None = None,
) -> WorldSetting:
    """构造测试用世界观条目实体（固定时间戳，便于断言）。"""
    return WorldSetting(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        parent_id=parent_id,
        created_at=TS,
        updated_at=TS,
    )


def _category(name: str = "地理", *, project_id: uuid.UUID = PID) -> WorldCategory:
    """构造测试用世界观分类实体。"""
    return WorldCategory(
        id=uuid.uuid4(), project_id=project_id, name=name, kind="geo", created_at=TS, updated_at=TS
    )


def _project() -> Project:
    """构造测试用项目实体（config 全默认）。"""
    return Project(id=PID, name="测试项目", created_at=TS, updated_at=TS)


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock WorldRepositoryProtocol — 默认全方法可用，测试按需覆盖。"""
    repo = MagicMock(spec=WorldRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_categories = AsyncMock(return_value=[])
    repo.add = AsyncMock(side_effect=lambda s: s)
    repo.update = AsyncMock(side_effect=lambda s: s)
    repo.hard_delete = AsyncMock(return_value=True)
    repo.get_by_parent_and_name = AsyncMock(return_value=None)
    repo.collect_ancestor_ids = AsyncMock(return_value=[])
    repo.list_descendants = AsyncMock(return_value=[])
    repo.hard_delete_many = AsyncMock(return_value=0)
    repo.delete_with_reparent = AsyncMock(return_value=True)
    # ── 分类（v1.2 #389）默认值 ──
    repo.create_category = AsyncMock(
        side_effect=lambda project_id, name, kind="geo": _category(name)
    )
    repo.get_category = AsyncMock(return_value=None)
    repo.get_category_by_name = AsyncMock(return_value=None)
    repo.rename_category = AsyncMock(side_effect=lambda category_id, name: _category(name))
    repo.delete_category = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — get 默认 = 项目存在（#1138 落库前校验）。"""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=_project())
    return repo


@pytest.fixture
def mock_extractor() -> MagicMock:
    """Mock WorldExtractor — extract 入口的管线调用。"""
    extractor = MagicMock(spec=WorldExtractor)
    extractor.extract = AsyncMock()
    return extractor


@pytest.fixture
def service(
    mock_repo: MagicMock,
    mock_project_repo: MagicMock,
    mock_extractor: MagicMock,
) -> WorldService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return WorldService(
        repository=mock_repo, extractor=mock_extractor, project_repo=mock_project_repo
    )


class TestWorldSettingDataChange:
    """world_setting 域写路径发布事件。"""

    async def test_create_setting_publishes_create(
        self, service: WorldService, recorded_events
    ) -> None:
        """create_setting 成功 → world_setting/create，project_id 取形参。"""
        created = await service.create_setting(PID, "大越国")

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("world_setting", "create")
        assert event.resource_id == str(created.id)
        assert event.project_id == str(PID)

    async def test_create_setting_conflict_publishes_nothing(
        self, service: WorldService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：同名冲突（写失败）→ 零发布。"""
        mock_repo.get_by_name = AsyncMock(return_value=_setting(name="大越国"))

        with pytest.raises(WorldNameConflictError):
            await service.create_setting(PID, "大越国")

        assert recorded_events == []

    async def test_update_setting_publishes_update(
        self, service: WorldService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """update_setting 成功 → world_setting/update，project_id 从已加载实体解析。"""
        existing = _setting(name="清河县城")
        mock_repo.get = AsyncMock(return_value=existing)

        updated = await service.update_setting(existing.id, WorldUpdate(content="水患频发"))

        assert updated is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("world_setting", "update")
        assert event.resource_id == str(updated.id)
        assert event.project_id == str(PID)

    async def test_update_setting_missing_publishes_nothing(
        self, service: WorldService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：条目不存在（返回 None）→ 零发布。"""
        mock_repo.get = AsyncMock(return_value=None)

        assert await service.update_setting(uuid.uuid4(), WorldUpdate(content="x")) is None
        assert recorded_events == []

    async def test_delete_setting_plain_publishes_delete(
        self, service: WorldService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """普通真删分支（无子地点）→ world_setting/delete，project_id 从已加载实体解析。"""
        setting = _setting(name="清河县城")
        mock_repo.get = AsyncMock(return_value=setting)
        mock_repo.list = AsyncMock(return_value=([], 0))

        assert await service.delete_setting(setting.id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("world_setting", "delete")
        assert event.resource_id == str(setting.id)
        assert event.project_id == str(PID)

    async def test_delete_setting_plain_hard_delete_false_publishes_nothing(
        self, service: WorldService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：普通分支 hard_delete 返回 False → 零发布。"""
        setting = _setting(name="清河县城")
        mock_repo.get = AsyncMock(return_value=setting)
        mock_repo.list = AsyncMock(return_value=([], 0))
        mock_repo.hard_delete = AsyncMock(return_value=False)

        assert await service.delete_setting(setting.id) is False
        assert recorded_events == []

    async def test_delete_setting_cascade_publishes_single_event(
        self, service: WorldService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """cascade 分支：整棵子树删除后只发**一条**域级事件（子树不逐条发）。"""
        setting = _setting(name="大越国")
        child = _setting(name="青州", parent_id=setting.id)
        mock_repo.get = AsyncMock(return_value=setting)
        mock_repo.list = AsyncMock(return_value=([child], 1))
        mock_repo.list_descendants = AsyncMock(return_value=[setting, child])

        assert await service.delete_setting(setting.id, cascade=True) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("world_setting", "delete")
        assert event.resource_id == str(setting.id)
        assert event.project_id == str(PID)

    async def test_delete_setting_reparent_publishes_single_event(
        self, service: WorldService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """reparent 分支：自身真删 + 子改挂后只发**一条**域级事件（子改挂不逐条发）。"""
        setting = _setting(name="青州")
        child = _setting(name="清河县城", parent_id=setting.id)
        target = _setting(name="大越国")
        mock_repo.get = AsyncMock(
            side_effect=lambda sid: target if sid == target.id.int else setting
        )
        mock_repo.list = AsyncMock(return_value=([child], 1))
        mock_repo.list_descendants = AsyncMock(return_value=[setting])

        assert await service.delete_setting(setting.id, reparent_to=target.id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("world_setting", "delete")
        assert event.resource_id == str(setting.id)
        assert event.project_id == str(PID)

    async def test_delete_setting_with_children_publishes_nothing(
        self, service: WorldService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：有子地点且未指定 cascade/reparent_to（写失败）→ 零发布。"""
        setting = _setting(name="青州")
        mock_repo.get = AsyncMock(return_value=setting)
        mock_repo.list = AsyncMock(return_value=([_setting(name="清河县城")], 1))

        with pytest.raises(WorldChildrenActionRequiredError):
            await service.delete_setting(setting.id)

        assert recorded_events == []

    async def test_extract_publishes_nothing(
        self, service: WorldService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """extract（AI 提取）**不发**事件（§15.6.4 中间态；GUI 提取流程自带刷新路径）。"""
        await service.extract(WorldExtractRequest(project_id=PID, text="大越国地处东陆。"))

        assert recorded_events == []


class TestWorldCategoryDataChange:
    """world_category 域写路径发布事件。"""

    async def test_create_category_publishes_create(
        self, service: WorldService, recorded_events
    ) -> None:
        """create_category 成功 → world_category/create，project_id 取形参。"""
        created = await service.create_category(PID, "地理")

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("world_category", "create")
        assert event.resource_id == str(created.id)
        assert event.project_id == str(PID)

    async def test_create_category_conflict_publishes_nothing(
        self, service: WorldService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：分类同名冲突（写失败）→ 零发布。"""
        mock_repo.get_category_by_name = AsyncMock(return_value=_category("地理"))

        with pytest.raises(WorldCategoryNameConflictError):
            await service.create_category(PID, "地理")

        assert recorded_events == []

    async def test_rename_category_publishes_update(
        self, service: WorldService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """rename_category 成功 → world_category/update（§15.6.4 语义化操作映射 update）。"""
        existing = _category("地理")
        mock_repo.get_category = AsyncMock(return_value=existing)

        renamed = await service.rename_category(existing.id, "山川地理")

        assert renamed is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("world_category", "update")
        assert event.resource_id == str(existing.id)
        assert event.project_id == str(PID)

    async def test_rename_category_missing_publishes_nothing(
        self, service: WorldService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：分类不存在（返回 None）→ 零发布。"""
        mock_repo.get_category = AsyncMock(return_value=None)

        assert await service.rename_category(uuid.uuid4(), "山川地理") is None
        assert recorded_events == []

    async def test_delete_category_publishes_none_project_id_with_warning(
        self, service: WorldService, mock_repo: MagicMock, recorded_events, caplog
    ) -> None:
        """delete_category 薄透传 → None + warning（spec §15.3.2 已知例外）。"""
        category_id = uuid.uuid4()
        caplog.set_level("WARNING", logger=LOGGER_NAME)

        assert await service.delete_category(category_id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("world_category", "delete")
        assert event.resource_id == str(category_id)
        assert event.project_id is None
        assert any("project_id" in record.getMessage() for record in caplog.records)

    async def test_delete_category_missing_publishes_nothing(
        self, service: WorldService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：分类不存在（返回 False）→ 零发布。"""
        mock_repo.delete_category = AsyncMock(return_value=False)

        assert await service.delete_category(uuid.uuid4()) is False
        assert recorded_events == []
