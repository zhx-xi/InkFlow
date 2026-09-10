"""OutlineService 数据面变更事件测试（#1088 批 A3；spec §15.3.2/§15.3.3）。

自 test_outline_service.py 拆出（守 900 行护栏，同 #281 测试文件规模治理先例）：
outline / plot_point / story_arc 三个项目域——A 类取形参，B 类从已加载实体
解析 project_id；薄透传方法（delete_outline / delete_point / delete_arc）
发 None + warning（spec §15.3.2 已知例外）。

依赖全 Mock 注入（镜像 test_outline_service.py 的 fixture 形态）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.outline import (
    Outline,
    OutlineUpdate,
    PlotPoint,
    PlotPointUpdate,
    StoryArc,
    StoryArcUpdate,
)
from inkflow.domain.ports.outline_errors import (
    OutlineNameConflictError,
    OutlineNotFoundError,
)
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.services._outline_generator import OutlineGenerator
from inkflow.domain.services.outline_service import OutlineService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _outline(
    name: str,
    *,
    project_id: uuid.UUID = PID,
    description: str = "",
    sort_order: int = 0,
) -> Outline:
    """构造测试用大纲实体（固定时间戳，便于断言）。"""
    return Outline(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        description=description,
        sort_order=sort_order,
        created_at=TS,
        updated_at=TS,
    )


def _point(
    name: str,
    *,
    outline: Outline,
    type: str = "",
    position: int = 0,
    arc_id: uuid.UUID | None = None,
) -> PlotPoint:
    """构造测试用情节点实体。"""
    return PlotPoint(
        id=uuid.uuid4(),
        outline_id=outline.id,
        project_id=outline.project_id,
        name=name,
        type=type,
        position=position,
        arc_id=arc_id,
        created_at=TS,
        updated_at=TS,
    )


def _arc(name: str, *, project_id: uuid.UUID = PID, description: str = "") -> StoryArc:
    """构造测试用弧线实体。"""
    return StoryArc(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        description=description,
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock OutlineRepositoryProtocol — 默认全方法可用，测试按需覆盖。"""
    repo = MagicMock(spec=OutlineRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda o: o)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.update = AsyncMock(side_effect=lambda o: o)
    repo.hard_delete = AsyncMock(return_value=True)
    repo.add_point = AsyncMock(side_effect=lambda p: p)
    repo.get_point = AsyncMock(return_value=None)
    repo.list_points = AsyncMock(return_value=[])
    repo.list_points_by_arc = AsyncMock(return_value=[])
    repo.next_position = AsyncMock(return_value=1)
    repo.update_point = AsyncMock(side_effect=lambda p: p)
    repo.hard_delete_point = AsyncMock(return_value=True)
    repo.clear_arc_of_points = AsyncMock(return_value=None)
    repo.add_arc = AsyncMock(side_effect=lambda a: a)
    repo.get_arc = AsyncMock(return_value=None)
    repo.get_arc_by_name = AsyncMock(return_value=None)
    repo.list_arcs = AsyncMock(return_value=[])
    repo.update_arc = AsyncMock(side_effect=lambda a: a)
    repo.hard_delete_arc = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — generate 入口校验项目存在性。"""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_generator() -> MagicMock:
    """Mock OutlineGenerator — generate 入口的管线调用。"""
    generator = MagicMock(spec=OutlineGenerator)
    generator.generate = AsyncMock()
    return generator


@pytest.fixture
def service(
    mock_repo: MagicMock,
    mock_project_repo: MagicMock,
    mock_generator: MagicMock,
) -> OutlineService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return OutlineService(
        repository=mock_repo,
        generator=mock_generator,
        project_repo=mock_project_repo,
    )


class TestDataChangeEvents:
    """#1088 批 A3：大纲域写路径发布事件（项目域；薄透传方法发 None + warning）。"""

    async def test_create_outline_publishes_create(
        self, service, mock_repo, recorded_events
    ) -> None:
        """A 类：create_outline 成功 → outline/create，project_id 取形参。"""
        created = await service.create_outline(project_id=PID, name="第一卷大纲", level="overall")

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("outline", "create")
        assert event.resource_id == str(created.id)
        assert event.project_id == str(PID)

    async def test_create_outline_conflict_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：同名冲突（写失败）→ 不发布。"""
        mock_repo.get_by_name = AsyncMock(return_value=_outline("第一卷大纲"))

        with pytest.raises(OutlineNameConflictError):
            await service.create_outline(project_id=PID, name="第一卷大纲", level="overall")

        assert recorded_events == []

    async def test_update_outline_publishes_update_with_entity_project_id(
        self, service, mock_repo, recorded_events
    ) -> None:
        """B 类：update_outline 成功 → outline/update，project_id 从已加载实体解析。"""
        mock_repo.get = AsyncMock(return_value=_outline("旧名"))

        updated = await service.update_outline(uuid.uuid4(), OutlineUpdate(name="新名"))

        assert updated is not None
        assert len(recorded_events) == 1
        assert (recorded_events[0].domain, recorded_events[0].op) == ("outline", "update")
        assert recorded_events[0].project_id == str(PID)

    async def test_update_outline_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：大纲不存在（返回 None）→ 不发布。"""
        mock_repo.get = AsyncMock(return_value=None)

        assert await service.update_outline(uuid.uuid4(), OutlineUpdate(name="新名")) is None
        assert recorded_events == []

    async def test_delete_outline_publishes_none_project_id_with_warning(
        self, service, mock_repo, recorded_events, caplog
    ) -> None:
        """delete_outline 未加载实体（薄透传）→ None + warning（spec §15.3.2 已知例外）。"""
        outline_id = uuid.uuid4()
        caplog.set_level("WARNING", logger="inkflow.domain.services.outline_service")

        assert await service.delete_outline(outline_id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("outline", "delete")
        assert event.resource_id == str(outline_id)
        assert event.project_id is None
        assert any("project_id" in record.getMessage() for record in caplog.records)

    async def test_delete_outline_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：大纲不存在（返回 False）→ 不发布。"""
        mock_repo.hard_delete = AsyncMock(return_value=False)

        assert await service.delete_outline(uuid.uuid4()) is False
        assert recorded_events == []

    async def test_create_point_publishes_with_outline_project(
        self, service, mock_repo, recorded_events
    ) -> None:
        """plot_point/create：project_id 从已加载大纲推出。"""
        outline = _outline("第一卷大纲")
        mock_repo.get = AsyncMock(return_value=outline)

        point = await service.create_point(outline.id, "主角觉醒")

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("plot_point", "create")
        assert event.resource_id == str(point.id)
        assert event.project_id == str(PID)

    async def test_create_point_missing_outline_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：大纲不存在（写失败）→ 不发布。"""
        mock_repo.get = AsyncMock(return_value=None)

        with pytest.raises(OutlineNotFoundError):
            await service.create_point(uuid.uuid4(), "主角觉醒")

        assert recorded_events == []

    async def test_update_point_publishes_update(self, service, mock_repo, recorded_events) -> None:
        """plot_point/update：PlotPoint 自带 project_id → 从已加载实体解析。"""
        outline = _outline("第一卷大纲")
        mock_repo.get_point = AsyncMock(return_value=_point("旧点", outline=outline))

        updated = await service.update_point(uuid.uuid4(), PlotPointUpdate(name="新点"))

        assert updated is not None
        assert len(recorded_events) == 1
        assert (recorded_events[0].domain, recorded_events[0].op) == ("plot_point", "update")
        assert recorded_events[0].project_id == str(PID)

    async def test_update_point_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：情节点不存在（返回 None）→ 不发布。"""
        mock_repo.get_point = AsyncMock(return_value=None)

        assert await service.update_point(uuid.uuid4(), PlotPointUpdate(name="新点")) is None
        assert recorded_events == []

    async def test_delete_point_publishes_none_project_id_with_warning(
        self, service, mock_repo, recorded_events, caplog
    ) -> None:
        """delete_point 未加载实体（薄透传）→ None + warning（spec §15.3.2 已知例外）。"""
        point_id = uuid.uuid4()
        caplog.set_level("WARNING", logger="inkflow.domain.services.outline_service")

        assert await service.delete_point(point_id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("plot_point", "delete")
        assert event.resource_id == str(point_id)
        assert event.project_id is None
        assert any("project_id" in record.getMessage() for record in caplog.records)

    async def test_delete_point_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：情节点不存在（返回 False）→ 不发布。"""
        mock_repo.hard_delete_point = AsyncMock(return_value=False)

        assert await service.delete_point(uuid.uuid4()) is False
        assert recorded_events == []

    async def test_create_arc_publishes_create(self, service, mock_repo, recorded_events) -> None:
        """A 类：create_arc 成功 → story_arc/create，project_id 取形参。"""
        arc = await service.create_arc(PID, "觉醒弧")

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("story_arc", "create")
        assert event.resource_id == str(arc.id)
        assert event.project_id == str(PID)

    async def test_update_arc_publishes_update(self, service, mock_repo, recorded_events) -> None:
        """B 类：update_arc 成功 → story_arc/update，project_id 非 None。"""
        mock_repo.get_arc = AsyncMock(return_value=_arc("觉醒弧"))

        updated = await service.update_arc(uuid.uuid4(), StoryArcUpdate(name="新生弧"))

        assert updated is not None
        assert len(recorded_events) == 1
        assert (recorded_events[0].domain, recorded_events[0].op) == ("story_arc", "update")
        assert recorded_events[0].project_id == str(PID)

    async def test_update_arc_missing_publishes_nothing(
        self, service, mock_repo, recorded_events
    ) -> None:
        """反例：弧线不存在（返回 None）→ 不发布。"""
        mock_repo.get_arc = AsyncMock(return_value=None)

        assert await service.update_arc(uuid.uuid4(), StoryArcUpdate(name="新生弧")) is None
        assert recorded_events == []

    async def test_delete_arc_publishes_none_project_id_with_warning(
        self, service, mock_repo, recorded_events, caplog
    ) -> None:
        """delete_arc 未加载实体（薄透传）→ None + warning（spec §15.3.2 已知例外）。"""
        arc_id = uuid.uuid4()
        caplog.set_level("WARNING", logger="inkflow.domain.services.outline_service")

        assert await service.delete_arc(arc_id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("story_arc", "delete")
        assert event.resource_id == str(arc_id)
        assert event.project_id is None
        assert any("project_id" in record.getMessage() for record in caplog.records)
