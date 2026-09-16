"""TimelineService 数据面变更事件测试（#1090 批次 B；spec §15.3.2/§15.3.3/§15.6.4）。

契约来源：W3C 设计裁定表 §2.4（父侧单一真相源）+ spec §15.3.3 四不变量。
- create_event 成功 → timeline_event/create（project_id 取形参）。
- update_event 成功 → timeline_event/update（existing 已加载 → project_id 非 None）；
  不存在（None）→ 零发布。
- delete_event 为**薄透传** hard_delete → project_id=None + logger.warning（消息含
  "project_id"）；返回 False → 零发布。

依赖全 Mock 注入（镜像 test_timeline_service.py 的 fixture 形态）。
RED 阶段预期：正例断言 FAIL，负例可能已 PASS。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.project import Project
from inkflow.domain.models.timeline import TimelineEvent, TimelineEventUpdate
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_errors import ProjectNotFoundError
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.services.timeline_service import TimelineService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
LOGGER_NAME = "inkflow.domain.services.timeline_service"


def _event(title: str = "林尘觉醒金手指", *, time_value: float | None = 317.5) -> TimelineEvent:
    """构造测试用时间线事件实体（固定时间戳，便于断言）。"""
    return TimelineEvent(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        time_value=time_value,
        narrative_position=1,
        created_at=TS,
        updated_at=TS,
    )


def _project() -> Project:
    """构造测试用项目实体（config 全默认）。"""
    return Project(id=PID, name="测试项目", created_at=TS, updated_at=TS)


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock TimelineRepositoryProtocol — 默认全方法可用，测试按需覆盖。"""
    repo = MagicMock(spec=TimelineRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda e: e)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_all = AsyncMock(return_value=[])
    repo.next_position = AsyncMock(return_value=1)
    repo.update = AsyncMock(side_effect=lambda e: e)
    repo.hard_delete = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — 项目存在性校验（默认项目存在）。"""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=_project())
    return repo


@pytest.fixture
def service(mock_repo: MagicMock, mock_project_repo: MagicMock) -> TimelineService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return TimelineService(repository=mock_repo, project_repo=mock_project_repo)


class TestDataChangeEvents:
    """#1090 批次 B：时间线域写路径发布事件。"""

    async def test_create_event_publishes_create(
        self, service: TimelineService, recorded_events
    ) -> None:
        """create_event 成功 → timeline_event/create，project_id 取形参。"""
        created = await service.create_event(PID, "林尘觉醒金手指", time_value=317.5)

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("timeline_event", "create")
        assert event.resource_id == str(created.id)
        assert event.project_id == str(PID)

    async def test_create_event_project_missing_publishes_nothing(
        self,
        service: TimelineService,
        mock_project_repo: MagicMock,
        recorded_events,
    ) -> None:
        """反例：项目不存在（写失败）→ 零发布。"""
        mock_project_repo.get = AsyncMock(return_value=None)

        with pytest.raises(ProjectNotFoundError):
            await service.create_event(PID, "林尘觉醒金手指")

        assert recorded_events == []

    async def test_update_event_publishes_update(
        self, service: TimelineService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """update_event 成功 → timeline_event/update，project_id 从已加载实体解析。"""
        existing = _event()
        mock_repo.get = AsyncMock(return_value=existing)

        updated = await service.update_event(existing.id, TimelineEventUpdate(description="新描述"))

        assert updated is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("timeline_event", "update")
        assert event.resource_id == str(updated.id)
        assert event.project_id == str(PID)

    async def test_update_event_missing_publishes_nothing(
        self, service: TimelineService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：事件不存在（返回 None）→ 零发布。"""
        mock_repo.get = AsyncMock(return_value=None)

        assert (
            await service.update_event(uuid.uuid4(), TimelineEventUpdate(description="x")) is None
        )
        assert recorded_events == []

    async def test_delete_event_publishes_none_project_id_with_warning(
        self, service: TimelineService, mock_repo: MagicMock, recorded_events, caplog
    ) -> None:
        """delete_event 薄透传 hard_delete → None + warning（spec §15.3.2 已知例外）。"""
        event_id = uuid.uuid4()
        caplog.set_level("WARNING", logger=LOGGER_NAME)

        assert await service.delete_event(event_id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("timeline_event", "delete")
        assert event.resource_id == str(event_id)
        assert event.project_id is None
        assert any("project_id" in record.getMessage() for record in caplog.records)

    async def test_delete_event_missing_publishes_nothing(
        self, service: TimelineService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：事件不存在（返回 False）→ 零发布。"""
        mock_repo.hard_delete = AsyncMock(return_value=False)

        assert await service.delete_event(uuid.uuid4()) is False
        assert recorded_events == []
