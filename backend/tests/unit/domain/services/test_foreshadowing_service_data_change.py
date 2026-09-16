"""ForeshadowingService 数据面变更事件测试（#1090 批次 B；spec §15.3.2/§15.3.3/§15.6.4）。

契约来源：W3C 设计裁定表 §2.3（父侧单一真相源）+ spec §15.3.3 四不变量。
- 写成功才发布（异常 / 返回 None / False / 幂等无变化 → 零发布）。
- resolve / reopen 仅在**真实状态迁移**时发（op="update"，§15.6.4 语义边界）；
  已 resolved 再 resolve、已 open 再 reopen 属幂等无变化 → 不发。
- delete 为**薄透传**（未加载实体）→ project_id=None + logger.warning（消息含
  "project_id"，镜像 character_service 已知例外形态）。

依赖全 Mock 注入（镜像 test_foreshadowing_service.py 的 fixture 形态）。
RED 阶段预期：正例断言 FAIL（实现尚未接 publish_change），负例可能已 PASS。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.foreshadowing import (
    Foreshadowing,
    ForeshadowingCreate,
    ForeshadowingStatus,
    ForeshadowingUpdate,
)
from inkflow.domain.models.project import Project
from inkflow.domain.ports.foreshadowing_errors import ForeshadowingNameConflictError
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.services.foreshadowing_service import ForeshadowingService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
LOGGER_NAME = "inkflow.domain.services.foreshadowing_service"


def _foreshadowing(
    title: str,
    *,
    status: ForeshadowingStatus = ForeshadowingStatus.OPEN,
    resolved_at: datetime | None = None,
) -> Foreshadowing:
    """构造测试用伏笔实体（固定时间戳，便于断言）。"""
    return Foreshadowing(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        status=status,
        resolved_at=resolved_at,
        created_at=TS,
        updated_at=TS,
    )


def _project() -> Project:
    """构造测试用项目实体（config 全默认）。"""
    return Project(id=PID, name="测试项目", created_at=TS, updated_at=TS)


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock ForeshadowingRepositoryProtocol — 默认全方法可用，测试按需覆盖。"""
    repo = MagicMock(spec=ForeshadowingRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda f: f)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_title = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_open = AsyncMock(return_value=[])
    repo.update = AsyncMock(side_effect=lambda f: f)
    repo.hard_delete = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — 项目存在性校验（默认项目存在）。"""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=_project())
    return repo


@pytest.fixture
def service(mock_repo: MagicMock, mock_project_repo: MagicMock) -> ForeshadowingService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return ForeshadowingService(repository=mock_repo, project_repo=mock_project_repo)


class TestDataChangeEvents:
    """#1090 批次 B：伏笔域写路径发布事件。"""

    async def test_create_publishes_create(
        self, service: ForeshadowingService, recorded_events
    ) -> None:
        """create 成功 → foreshadowing/create，project_id 取 DTO 形参。"""
        created = await service.create(ForeshadowingCreate(project_id=PID, title="青铜钥匙"))

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("foreshadowing", "create")
        assert event.resource_id == str(created.id)
        assert event.project_id == str(PID)

    async def test_create_conflict_publishes_nothing(
        self, service: ForeshadowingService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：同名冲突（写失败）→ 零发布。"""
        mock_repo.get_by_title = AsyncMock(return_value=_foreshadowing("青铜钥匙"))

        with pytest.raises(ForeshadowingNameConflictError):
            await service.create(ForeshadowingCreate(project_id=PID, title="青铜钥匙"))

        assert recorded_events == []

    async def test_update_publishes_update(
        self, service: ForeshadowingService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """update 成功 → foreshadowing/update，project_id 从已加载实体解析。"""
        existing = _foreshadowing("青铜钥匙")
        mock_repo.get = AsyncMock(return_value=existing)

        updated = await service.update(existing.id, ForeshadowingUpdate(description="锈迹斑斑"))

        assert updated is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("foreshadowing", "update")
        assert event.resource_id == str(updated.id)
        assert event.project_id == str(PID)

    async def test_update_missing_publishes_nothing(
        self, service: ForeshadowingService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：伏笔不存在（返回 None）→ 零发布。"""
        mock_repo.get = AsyncMock(return_value=None)

        assert await service.update(uuid.uuid4(), ForeshadowingUpdate(description="x")) is None
        assert recorded_events == []

    async def test_resolve_publishes_update(
        self, service: ForeshadowingService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """resolve 真实迁移（open→resolved）→ foreshadowing/update（§15.6.4 op 边界）。"""
        existing = _foreshadowing("青铜钥匙", status=ForeshadowingStatus.OPEN)
        mock_repo.get = AsyncMock(return_value=existing)

        resolved = await service.resolve(existing.id)

        assert resolved is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("foreshadowing", "update")
        assert event.resource_id == str(existing.id)
        assert event.project_id == str(PID)

    async def test_resolve_already_resolved_publishes_nothing(
        self, service: ForeshadowingService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：已 resolved 再 resolve（幂等无变化）→ 零发布。"""
        existing = _foreshadowing("青铜钥匙", status=ForeshadowingStatus.RESOLVED, resolved_at=TS)
        mock_repo.get = AsyncMock(return_value=existing)

        assert await service.resolve(existing.id) is existing
        assert recorded_events == []

    async def test_reopen_publishes_update(
        self, service: ForeshadowingService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """reopen 真实迁移（resolved→open）→ foreshadowing/update。"""
        existing = _foreshadowing("青铜钥匙", status=ForeshadowingStatus.RESOLVED, resolved_at=TS)
        mock_repo.get = AsyncMock(return_value=existing)

        reopened = await service.reopen(existing.id)

        assert reopened is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("foreshadowing", "update")
        assert event.resource_id == str(existing.id)
        assert event.project_id == str(PID)

    async def test_reopen_already_open_publishes_nothing(
        self, service: ForeshadowingService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：已 open 再 reopen（幂等无变化）→ 零发布。"""
        existing = _foreshadowing("青铜钥匙", status=ForeshadowingStatus.OPEN)
        mock_repo.get = AsyncMock(return_value=existing)

        assert await service.reopen(existing.id) is existing
        assert recorded_events == []

    async def test_delete_publishes_none_project_id_with_warning(
        self, service: ForeshadowingService, mock_repo: MagicMock, recorded_events, caplog
    ) -> None:
        """delete 薄透传（未加载实体）→ None + warning（spec §15.3.2 已知例外）。"""
        foreshadowing_id = uuid.uuid4()
        caplog.set_level("WARNING", logger=LOGGER_NAME)

        assert await service.delete(foreshadowing_id) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("foreshadowing", "delete")
        assert event.resource_id == str(foreshadowing_id)
        assert event.project_id is None
        assert any("project_id" in record.getMessage() for record in caplog.records)

    async def test_delete_missing_publishes_nothing(
        self, service: ForeshadowingService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：伏笔不存在（返回 False）→ 零发布。"""
        mock_repo.hard_delete = AsyncMock(return_value=False)

        assert await service.delete(uuid.uuid4()) is False
        assert recorded_events == []
