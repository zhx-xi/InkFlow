"""F13 伏笔服务单元测试 — Mock Repository（F13 服务层 RED→GREEN）.

覆盖 spec §9 服务测试 + §7 边界表（镜像 F12 test_timeline_service.py）:
- 创建全流程：默认 status=open / priority=50；event_id 挂接编排
- 同名活动伏笔 → ForeshadowingNameConflictError（422 语义）
- event_id 校验：不存在 → EventNotFoundError、跨项目 → EventNotInProjectError、
  合法通过（timeline_repo.get 命中同项目事件）
- 项目不存在 → ProjectNotFoundError（404 语义）；project_repo / timeline_repo
  未注入 → ForeshadowingServiceError（配置错误，防静默降级）
- update 部分更新：exclude_unset 合并；event_id None 不修改、"" 解除挂接、
  UUID 挂接（仅变化时校验）；title 改名同名冲突 → 422；status/resolved_at
  不可经 update 修改
- resolve（open→resolved + resolved_at 设置；已 resolved 幂等不更新
  resolved_at；不存在 → None）/ reopen（resolved→open + resolved_at 清空；
  已 open 幂等）
- 404 全路径：get/update/resolve/reopen 不存在 → None；soft_delete → False

依据: specs/f13-foreshadowing-service/spec.md §7 + §9 测试策略。
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
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.ports.foreshadowing_errors import (
    EventNotFoundError,
    EventNotInProjectError,
    ForeshadowingNameConflictError,
    ForeshadowingServiceError,
    ProjectNotFoundError,
)
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.services.foreshadowing_service import ForeshadowingService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
OTHER_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
EVENT_ID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _foreshadowing(
    title: str,
    *,
    status: ForeshadowingStatus = ForeshadowingStatus.OPEN,
    priority: int = 50,
    event_id: uuid.UUID | None = None,
    resolved_at: datetime | None = None,
    description: str = "",
    location: str = "",
) -> Foreshadowing:
    """构造测试用伏笔实体（固定时间戳，便于断言）。"""
    return Foreshadowing(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        description=description,
        priority=priority,
        status=status,
        location=location,
        event_id=event_id,
        resolved_at=resolved_at,
        created_at=TS,
        updated_at=TS,
    )


def _project() -> Project:
    """构造测试用项目实体（config 全默认）。"""
    return Project(id=PID, name="测试项目", created_at=TS, updated_at=TS)


def _event(project_id: uuid.UUID = PID) -> TimelineEvent:
    """构造测试用时间线事件实体（F12 领域模型，event_id 校验命中对象）。"""
    return TimelineEvent(
        id=EVENT_ID,
        project_id=project_id,
        title="林尘觉醒金手指",
        time_value=317.5,
        time_display="青元历 317 年秋",
        narrative_position=1,
        timeline_flag="",
        created_at=TS,
        updated_at=TS,
    )


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
    repo.soft_delete = AsyncMock(return_value=True)
    repo.restore = AsyncMock(return_value=None)
    repo.hard_delete = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — 项目存在性校验（默认项目存在）。"""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=_project())
    return repo


@pytest.fixture
def mock_timeline_repo() -> MagicMock:
    """Mock TimelineRepositoryProtocol（F12）— 事件锚点校验（默认事件存在）。"""
    repo = MagicMock(spec=TimelineRepositoryProtocol)
    repo.get = AsyncMock(return_value=_event())
    return repo


@pytest.fixture
def service(
    mock_repo: MagicMock,
    mock_project_repo: MagicMock,
    mock_timeline_repo: MagicMock,
) -> ForeshadowingService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return ForeshadowingService(
        repository=mock_repo,
        project_repo=mock_project_repo,
        timeline_repo=mock_timeline_repo,
    )


class TestCreate:
    """伏笔创建 — 默认值 / 同名冲突 / 事件锚点校验 / 项目校验。"""

    async def test_create_defaults_open_and_priority_50(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """最小创建：status=open、priority=50、event_id=None、未软删除。"""
        created = await service.create(ForeshadowingCreate(project_id=PID, title="林晚的身世"))
        assert created.title == "林晚的身世"
        mock_repo.get_by_title.assert_awaited_once_with(PID.int, "林晚的身世")
        added = mock_repo.add.await_args.args[0]
        assert isinstance(added, Foreshadowing)
        assert added.project_id == PID
        assert added.status == ForeshadowingStatus.OPEN
        assert added.priority == 50
        assert added.event_id is None
        assert added.resolved_at is None
        assert added.is_deleted is False

    async def test_create_with_event_id_validates_and_attaches(
        self,
        service: ForeshadowingService,
        mock_repo: MagicMock,
        mock_timeline_repo: MagicMock,
    ) -> None:
        """event_id 非 None → 经 timeline_repo.get 校验后挂接（合法通过）。"""
        created = await service.create(
            ForeshadowingCreate(project_id=PID, title="林晚的身世", priority=80, event_id=EVENT_ID)
        )
        mock_timeline_repo.get.assert_awaited_once_with(EVENT_ID.int)
        added = mock_repo.add.await_args.args[0]
        assert added.event_id == EVENT_ID
        assert created.event_id == EVENT_ID

    async def test_create_duplicate_title_raises_name_conflict(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """项目内已存在同名活动伏笔 → ForeshadowingNameConflictError（422）。"""
        mock_repo.get_by_title = AsyncMock(return_value=_foreshadowing("林晚的身世"))
        with pytest.raises(ForeshadowingNameConflictError):
            await service.create(ForeshadowingCreate(project_id=PID, title="林晚的身世"))
        mock_repo.add.assert_not_awaited()

    async def test_create_event_missing_raises_event_not_found(
        self,
        service: ForeshadowingService,
        mock_repo: MagicMock,
        mock_timeline_repo: MagicMock,
    ) -> None:
        """event_id 指向不存在事件（含已软删，F12 get 不含软删）→ EventNotFoundError。"""
        mock_timeline_repo.get = AsyncMock(return_value=None)
        with pytest.raises(EventNotFoundError):
            await service.create(
                ForeshadowingCreate(project_id=PID, title="铜镜的秘密", event_id=EVENT_ID)
            )
        mock_repo.add.assert_not_awaited()

    async def test_create_event_cross_project_raises_event_not_in_project(
        self,
        service: ForeshadowingService,
        mock_repo: MagicMock,
        mock_timeline_repo: MagicMock,
    ) -> None:
        """event_id 指向其他项目的事件 → EventNotInProjectError（422）。"""
        mock_timeline_repo.get = AsyncMock(return_value=_event(project_id=OTHER_PID))
        with pytest.raises(EventNotInProjectError):
            await service.create(
                ForeshadowingCreate(project_id=PID, title="铜镜的秘密", event_id=EVENT_ID)
            )
        mock_repo.add.assert_not_awaited()

    async def test_create_project_missing_raises(
        self,
        service: ForeshadowingService,
        mock_repo: MagicMock,
        mock_project_repo: MagicMock,
    ) -> None:
        """项目不存在 → ProjectNotFoundError（404 语义），不落库。"""
        mock_project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            await service.create(ForeshadowingCreate(project_id=PID, title="林晚的身世"))
        mock_repo.add.assert_not_awaited()

    async def test_create_project_repo_unconfigured_raises(self, mock_repo: MagicMock) -> None:
        """project_repo 未注入 → ForeshadowingServiceError（配置错误，防静默降级）。"""
        svc = ForeshadowingService(repository=mock_repo)
        with pytest.raises(ForeshadowingServiceError):
            await svc.create(ForeshadowingCreate(project_id=PID, title="林晚的身世"))
        mock_repo.add.assert_not_awaited()

    async def test_create_event_validation_unconfigured_raises(
        self, mock_repo: MagicMock, mock_project_repo: MagicMock
    ) -> None:
        """timeline_repo 未注入且 event_id 非 None → ForeshadowingServiceError。"""
        svc = ForeshadowingService(repository=mock_repo, project_repo=mock_project_repo)
        with pytest.raises(ForeshadowingServiceError):
            await svc.create(
                ForeshadowingCreate(project_id=PID, title="铜镜的秘密", event_id=EVENT_ID)
            )
        mock_repo.add.assert_not_awaited()


class TestListGet:
    """伏笔列表与详情 — 透传与 None 语义。"""

    async def test_list_forwards_filters_and_pagination(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """列表查询透传搜索/状态/排序/分页（UUID→int 转换）。"""
        f = _foreshadowing("林晚的身世", priority=80)
        mock_repo.list = AsyncMock(return_value=([f], 1))
        items, total = await service.list(
            project_id=PID,
            search="身世",
            status="open",
            sort_by="priority",
            sort_desc=True,
            offset=10,
            limit=5,
        )
        assert items == [f]
        assert total == 1
        kwargs = mock_repo.list.await_args.kwargs
        assert kwargs["project_id"] == PID.int
        assert kwargs["search"] == "身世"
        assert kwargs["status"] == "open"
        assert kwargs["sort_by"] == "priority"
        assert kwargs["sort_desc"] is True
        assert kwargs["offset"] == 10
        assert kwargs["limit"] == 5

        # 缺省参数：sort_by=priority / sort_desc=True / offset=0 / limit=50
        mock_repo.list = AsyncMock(return_value=([], 0))
        await service.list(PID)
        defaults = mock_repo.list.await_args.kwargs
        assert defaults["sort_by"] == "priority"
        assert defaults["sort_desc"] is True
        assert defaults["offset"] == 0
        assert defaults["limit"] == 50

    async def test_list_project_missing_raises(
        self, service: ForeshadowingService, mock_project_repo: MagicMock
    ) -> None:
        """项目不存在 → ProjectNotFoundError（router 层转 404）。"""
        mock_project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            await service.list(PID)

    async def test_get_returns_entity_or_none(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """伏笔存在 → 返回实体；不存在 → None（router 层转 404）。"""
        f = _foreshadowing("林晚的身世")
        mock_repo.get = AsyncMock(return_value=f)
        result = await service.get(f.id)
        assert result == f
        mock_repo.get.assert_awaited_once_with(f.id.int)

        mock_repo.get = AsyncMock(return_value=None)
        assert await service.get(uuid.uuid4()) is None


class TestUpdate:
    """伏笔更新 — exclude_unset 合并 + event_id 双语义 + 改名同名检查。"""

    async def test_update_merges_provided_fields(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """部分更新：仅覆盖传入字段；status/resolved_at 不可经 update 修改。"""
        existing = _foreshadowing(
            "林晚的身世",
            description="胎记与信物相同",
            priority=80,
            location="第 5 章·林晚沐浴场景",
        )
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.update = AsyncMock(side_effect=lambda f: f)

        update = ForeshadowingUpdate(
            title="林晚的身世（改）",
            priority=90,
            location="",  # "" = 清除埋设位置
            status="resolved",  # 未知字段：Pydantic 忽略，不生效
        )
        result = await service.update(existing.id, update)

        merged = mock_repo.update.await_args.args[0]
        assert isinstance(merged, Foreshadowing)
        assert merged.id == existing.id
        assert merged.title == "林晚的身世（改）"
        assert merged.priority == 90
        assert merged.location == ""
        assert merged.description == "胎记与信物相同"  # 未传入字段保持不变
        assert merged.status == ForeshadowingStatus.OPEN  # status 不可经 update 修改
        assert merged.resolved_at is None
        assert merged.created_at == TS
        assert result == merged

    async def test_update_event_id_none_does_not_change(
        self,
        service: ForeshadowingService,
        mock_repo: MagicMock,
        mock_timeline_repo: MagicMock,
    ) -> None:
        """event_id=None → 不修改现有挂接，且不触发事件校验。"""
        existing = _foreshadowing("林晚的身世", event_id=EVENT_ID)
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.update = AsyncMock(side_effect=lambda f: f)

        await service.update(existing.id, ForeshadowingUpdate(event_id=None))
        merged = mock_repo.update.await_args.args[0]
        assert merged.event_id == EVENT_ID
        mock_timeline_repo.get.assert_not_awaited()

    async def test_update_event_id_empty_string_clears_attachment(
        self,
        service: ForeshadowingService,
        mock_repo: MagicMock,
        mock_timeline_repo: MagicMock,
    ) -> None:
        """event_id="" → 解除事件挂接（置 None），无需事件校验。"""
        existing = _foreshadowing("林晚的身世", event_id=EVENT_ID)
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.update = AsyncMock(side_effect=lambda f: f)

        result = await service.update(existing.id, ForeshadowingUpdate(event_id=""))
        merged = mock_repo.update.await_args.args[0]
        assert merged.event_id is None
        mock_timeline_repo.get.assert_not_awaited()
        assert result == merged

    async def test_update_event_id_uuid_attaches_after_validation(
        self,
        service: ForeshadowingService,
        mock_repo: MagicMock,
        mock_timeline_repo: MagicMock,
    ) -> None:
        """event_id=UUID → 校验通过后挂接；与现有值相同则不重复校验。"""
        existing = _foreshadowing("林晚的身世")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.update = AsyncMock(side_effect=lambda f: f)

        await service.update(existing.id, ForeshadowingUpdate(event_id=EVENT_ID))
        mock_timeline_repo.get.assert_awaited_once_with(EVENT_ID.int)
        merged = mock_repo.update.await_args.args[0]
        assert merged.event_id == EVENT_ID

        # 与现有值相同 → 跳过校验（避免对未变字段重复校验）
        attached = _foreshadowing("林晚的身世", event_id=EVENT_ID)
        mock_repo.get = AsyncMock(return_value=attached)
        mock_timeline_repo.get = AsyncMock(return_value=_event())
        await service.update(attached.id, ForeshadowingUpdate(event_id=EVENT_ID))
        mock_timeline_repo.get.assert_not_awaited()

    async def test_update_title_conflict_raises(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """改名与项目内其他活动伏笔同名 → ForeshadowingNameConflictError（422）。"""
        existing = _foreshadowing("林晚的身世")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.get_by_title = AsyncMock(return_value=_foreshadowing("铜镜的秘密"))
        with pytest.raises(ForeshadowingNameConflictError):
            await service.update(existing.id, ForeshadowingUpdate(title="铜镜的秘密"))
        mock_repo.update.assert_not_awaited()

    async def test_update_title_unchanged_skips_conflict_check(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """title 未变化 → 不触发同名检查（get_by_title 不被调用）。"""
        existing = _foreshadowing("林晚的身世")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.update = AsyncMock(side_effect=lambda f: f)

        await service.update(existing.id, ForeshadowingUpdate(title="林晚的身世", priority=60))
        merged = mock_repo.update.await_args.args[0]
        assert merged.title == "林晚的身世"
        assert merged.priority == 60
        mock_repo.get_by_title.assert_not_awaited()

    async def test_update_returns_none_when_missing(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """伏笔不存在 → None（router 层转 404），不触发仓储更新。"""
        mock_repo.get = AsyncMock(return_value=None)
        result = await service.update(uuid.uuid4(), ForeshadowingUpdate(title="新标题"))
        assert result is None
        mock_repo.update.assert_not_awaited()


class TestResolveReopen:
    """状态机迁移 — resolve/reopen 编排与幂等。"""

    async def test_resolve_open_to_resolved_sets_resolved_at(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """open → resolved：自动设置 resolved_at=now(UTC) 并落库。"""
        existing = _foreshadowing("林晚的身世")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.update = AsyncMock(side_effect=lambda f: f)

        result = await service.resolve(existing.id)

        assert result is not None
        assert result.status == ForeshadowingStatus.RESOLVED
        assert result.resolved_at is not None
        merged = mock_repo.update.await_args.args[0]
        assert merged.status == ForeshadowingStatus.RESOLVED
        assert merged.resolved_at is not None
        assert merged.id == existing.id

    async def test_resolve_already_resolved_idempotent_keeps_resolved_at(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """已 resolved 再 resolve → 幂等：原样返回，resolved_at 不更新、不落库。"""
        existing = _foreshadowing("林晚的身世", status=ForeshadowingStatus.RESOLVED, resolved_at=TS)
        mock_repo.get = AsyncMock(return_value=existing)

        result = await service.resolve(existing.id)

        assert result == existing
        assert result.status == ForeshadowingStatus.RESOLVED
        assert result.resolved_at == TS
        mock_repo.update.assert_not_awaited()

    async def test_reopen_resolved_to_open_clears_resolved_at(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """resolved → open：清空 resolved_at 并落库。"""
        existing = _foreshadowing("林晚的身世", status=ForeshadowingStatus.RESOLVED, resolved_at=TS)
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.update = AsyncMock(side_effect=lambda f: f)

        result = await service.reopen(existing.id)

        assert result is not None
        assert result.status == ForeshadowingStatus.OPEN
        assert result.resolved_at is None
        merged = mock_repo.update.await_args.args[0]
        assert merged.status == ForeshadowingStatus.OPEN
        assert merged.resolved_at is None

    async def test_reopen_already_open_idempotent(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """已 open 再 reopen → 幂等：原样返回，不落库。"""
        existing = _foreshadowing("林晚的身世")
        mock_repo.get = AsyncMock(return_value=existing)

        result = await service.reopen(existing.id)

        assert result == existing
        assert result.status == ForeshadowingStatus.OPEN
        mock_repo.update.assert_not_awaited()

    async def test_resolve_reopen_missing_returns_none(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """不存在/已软删除的伏笔执行 resolve/reopen → None（router 转 404）。"""
        mock_repo.get = AsyncMock(return_value=None)
        assert await service.resolve(uuid.uuid4()) is None
        assert await service.reopen(uuid.uuid4()) is None
        mock_repo.update.assert_not_awaited()


class TestDeleteRestore:
    """软删/恢复/硬删 — 委托仓储。"""

    async def test_soft_delete_delegates(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """软删伏笔：委托 repo.soft_delete；不存在 → False。"""
        f = _foreshadowing("林晚的身世")
        result = await service.soft_delete(f.id)
        assert result is True
        mock_repo.soft_delete.assert_awaited_once_with(f.id.int)

        mock_repo.soft_delete = AsyncMock(return_value=False)
        assert await service.soft_delete(uuid.uuid4()) is False

    async def test_hard_delete_delegates(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """硬删伏笔：委托 repo.hard_delete；不存在 → False。"""
        f = _foreshadowing("林晚的身世")
        result = await service.hard_delete(f.id)
        assert result is True
        mock_repo.hard_delete.assert_awaited_once_with(f.id.int)

        mock_repo.hard_delete = AsyncMock(return_value=False)
        assert await service.hard_delete(uuid.uuid4()) is False

    async def test_restore_returns_entity_or_none(
        self, service: ForeshadowingService, mock_repo: MagicMock
    ) -> None:
        """恢复软删伏笔：委托 repo.restore；不存在 → None（重复操作无毒）。"""
        f = _foreshadowing("林晚的身世")
        mock_repo.restore = AsyncMock(return_value=f)
        result = await service.restore(f.id)
        assert result == f
        mock_repo.restore.assert_awaited_once_with(f.id.int)

        mock_repo.restore = AsyncMock(return_value=None)
        assert await service.restore(uuid.uuid4()) is None
