"""F12 时间线服务单元测试 — Mock Repository（F12 服务层 RED→GREEN）.

覆盖 spec §9 服务测试 + §7 边界表（镜像 F10 test_world_service.py）:
- 事件创建全流程：narrative_position 显式传入 / 缺省时 next_position 编排
- 项目不存在各操作 → ProjectNotFoundError（404 语义）；project_repo 未注入
  → TimelineServiceError（配置错误，防静默降级）
- 更新清除语义：time_value "" → 置 None、None → 不修改；timeline_flag ""
  → 置 ""（清除标记）；其余字段 None → 不修改；更新不存在 → None
- delete_event 真删委托 repo.hard_delete；get_event None（router 层转 404）
- list 透传搜索/排序/分页；view 编排（两种排序视图）；check 编排

依据: specs/f12-timeline-service/spec.md §7 + §9 测试策略。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.project import Project
from inkflow.domain.models.timeline import (
    TimelineEvent,
    TimelineEventUpdate,
)
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_errors import (
    ProjectNotFoundError,
    TimelineServiceError,
)
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.services.timeline_service import TimelineService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _event(
    title: str,
    *,
    time_value: float | None = None,
    time_display: str = "",
    narrative_position: int = 1,
    timeline_flag: str = "",
) -> TimelineEvent:
    """构造测试用时间线事件实体（固定时间戳，便于断言）。"""
    return TimelineEvent(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        time_value=time_value,
        time_display=time_display,
        narrative_position=narrative_position,
        timeline_flag=timeline_flag,
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


class TestCreateEvent:
    """事件创建 — 显式位置 / next_position 编排 / 项目校验。"""

    async def test_create_event_explicit_position_persists(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """显式 narrative_position → repo.add 收到完整实体，不调用 next_position。"""
        created = await service.create_event(
            PID,
            "林尘觉醒金手指",
            description="古鼎第一次亮起",
            time_value=317.5,
            time_unit="年",
            time_display="青元历 317 年秋",
            narrative_position=3,
            timeline_flag="",
        )
        assert created.title == "林尘觉醒金手指"
        mock_repo.next_position.assert_not_awaited()
        added = mock_repo.add.await_args.args[0]
        assert isinstance(added, TimelineEvent)
        assert added.project_id == PID
        assert added.description == "古鼎第一次亮起"
        assert added.time_value == 317.5
        assert added.time_unit == "年"
        assert added.time_display == "青元历 317 年秋"
        assert added.narrative_position == 3
        assert added.timeline_flag == ""

    async def test_create_event_auto_position_calls_next_position(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """narrative_position=None → 先 next_position 再 add（追加到叙事末尾）。"""
        mock_repo.next_position = AsyncMock(return_value=5)
        await service.create_event(PID, "宗门大比")
        mock_repo.next_position.assert_awaited_once_with(PID.int)
        added = mock_repo.add.await_args.args[0]
        assert added.narrative_position == 5

    async def test_create_event_project_missing_raises(
        self,
        service: TimelineService,
        mock_repo: MagicMock,
        mock_project_repo: MagicMock,
    ) -> None:
        """项目不存在 → ProjectNotFoundError（404 语义），不落库。"""
        mock_project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            await service.create_event(PID, "林尘觉醒金手指")
        mock_repo.add.assert_not_awaited()

    async def test_create_event_project_repo_unconfigured_raises(
        self, mock_repo: MagicMock
    ) -> None:
        """project_repo 未注入 → TimelineServiceError（配置错误，防静默降级）。"""
        svc = TimelineService(repository=mock_repo)
        with pytest.raises(TimelineServiceError):
            await svc.create_event(PID, "林尘觉醒金手指")
        mock_repo.add.assert_not_awaited()


class TestListGet:
    """事件列表与详情 — 透传与 None 语义。"""

    async def test_list_events_forwards_filters_and_pagination(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """列表查询透传搜索/排序/分页（UUID→int 转换，默认叙事位置升序）。"""
        event = _event("宗门大比", time_value=319.0)
        mock_repo.list = AsyncMock(return_value=([event], 1))
        items, total = await service.list_events(
            project_id=PID,
            search="大比",
            sort_by="time_value",
            sort_desc=False,
            offset=10,
            limit=5,
        )
        assert items == [event]
        assert total == 1
        kwargs = mock_repo.list.await_args.kwargs
        assert kwargs["project_id"] == PID.int
        assert kwargs["search"] == "大比"
        assert kwargs["sort_by"] == "time_value"
        assert kwargs["sort_desc"] is False
        assert kwargs["offset"] == 10
        assert kwargs["limit"] == 5

    async def test_list_events_default_sort_by_narrative_position(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """列表默认 sort_by=narrative_position（时间线语境下叙事顺序为自然默认）。"""
        await service.list_events(PID)
        kwargs = mock_repo.list.await_args.kwargs
        assert kwargs["sort_by"] == "narrative_position"
        assert kwargs["sort_desc"] is False
        assert kwargs["offset"] == 0
        assert kwargs["limit"] == 50

    async def test_get_event_returns_entity_or_none(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """事件存在 → 返回实体；不存在 → None（router 层转 404）。"""
        event = _event("林尘觉醒金手指")
        mock_repo.get = AsyncMock(return_value=event)
        result = await service.get_event(event.id)
        assert result == event
        mock_repo.get.assert_awaited_once_with(event.id.int)

        mock_repo.get = AsyncMock(return_value=None)
        assert await service.get_event(uuid.uuid4()) is None


class TestUpdateEvent:
    """事件更新 — exclude_unset 合并 + 清除语义。"""

    async def test_update_event_merges_provided_fields(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """部分更新：仅覆盖传入字段；time_value "" → 置 None（清除时间）。"""
        existing = _event(
            "林尘觉醒金手指",
            time_value=317.5,
            time_display="青元历 317 年秋",
            narrative_position=2,
        )
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.update = AsyncMock(side_effect=lambda e: e)

        update = TimelineEventUpdate(
            title="林尘觉醒金手指（改）", time_value="", timeline_flag="flashback"
        )
        result = await service.update_event(existing.id, update)

        merged = mock_repo.update.await_args.args[0]
        assert isinstance(merged, TimelineEvent)
        assert merged.id == existing.id
        assert merged.title == "林尘觉醒金手指（改）"
        assert merged.time_value is None  # "" = 清除世界内时间（置为未知）
        assert merged.time_display == "青元历 317 年秋"  # 未传入字段保持不变
        assert merged.narrative_position == 2
        assert merged.timeline_flag == "flashback"
        assert merged.created_at == TS
        assert result == merged

    async def test_update_event_none_means_no_change(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """None 语义：time_value/timeline_flag/title=None 均不修改；"" 清除。"""
        existing = _event(
            "林尘觉醒金手指",
            time_value=317.5,
            time_display="青元历 317 年秋",
            timeline_flag="flashback",
        )
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.update = AsyncMock(side_effect=lambda e: e)

        # time_value=None / timeline_flag=None / title=None → 全部不修改
        await service.update_event(
            existing.id, TimelineEventUpdate(time_value=None, timeline_flag=None, title=None)
        )
        merged = mock_repo.update.await_args.args[0]
        assert merged.time_value == 317.5
        assert merged.timeline_flag == "flashback"
        assert merged.title == "林尘觉醒金手指"

        # "" 清除语义：time_value "" → None、timeline_flag "" → ""、time_unit "" → ""
        mock_repo.update = AsyncMock(side_effect=lambda e: e)
        await service.update_event(
            existing.id,
            TimelineEventUpdate(time_value="", timeline_flag="", time_unit=""),
        )
        merged2 = mock_repo.update.await_args.args[0]
        assert merged2.time_value is None
        assert merged2.timeline_flag == ""
        assert merged2.time_unit == ""

    async def test_update_event_returns_none_when_missing(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """事件不存在 → None（router 层转 404），不触发仓储更新。"""
        mock_repo.get = AsyncMock(return_value=None)
        result = await service.update_event(uuid.uuid4(), TimelineEventUpdate(title="新标题"))
        assert result is None
        mock_repo.update.assert_not_awaited()


class TestDeleteEvent:
    """真删 — 委托仓储。"""

    async def test_delete_event_delegates(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """真删事件（v1.1）：委托 repo.hard_delete；不存在 → False。"""
        event = _event("宗门大比")
        result = await service.delete_event(event.id)
        assert result is True
        mock_repo.hard_delete.assert_awaited_once_with(event.id.int)

        mock_repo.hard_delete = AsyncMock(return_value=False)
        assert await service.delete_event(uuid.uuid4()) is False


class TestP5DeleteEventTriggersMapCleanup:
    """C8：delete_event 触发 map_cleanup 钩子——RED 预期 FAIL（现无钩子调用）."""

    async def test_delete_event_calls_map_cleanup_hook(self, mock_repo, mock_project_repo) -> None:
        """删除成功 → map_cleanup 钩子被调用（clear_ref_pins('event', [eid])）."""
        map_cleanup = AsyncMock()
        svc = TimelineService(
            repository=mock_repo,
            project_repo=mock_project_repo,
            map_cleanup=map_cleanup,
        )
        event = _event("宗门大比")
        mock_repo.hard_delete = AsyncMock(return_value=True)

        result = await svc.delete_event(event.id)

        assert result is True
        map_cleanup.assert_awaited_once()
        call = map_cleanup.await_args
        assert call is not None and call.args[0] == event.id.int

    async def test_delete_event_missing_skips_map_cleanup(
        self, mock_repo, mock_project_repo
    ) -> None:
        """删除失败（事件不存在）→ 钩子不被调用."""
        map_cleanup = AsyncMock()
        svc = TimelineService(
            repository=mock_repo,
            project_repo=mock_project_repo,
            map_cleanup=map_cleanup,
        )
        mock_repo.hard_delete = AsyncMock(return_value=False)

        result = await svc.delete_event(uuid.uuid4())

        assert result is False
        map_cleanup.assert_not_awaited()


class TestViewCheck:
    """双线视图与一致性检查 — 编排。"""

    async def test_get_timeline_view_sorts_both_timelines(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """双线视图：event_timeline 按 time_value 升序（未知排末尾），
        narrative_order 为 list_all 原样（契约已按叙事位置排序），total=事件数。"""
        e1 = _event("外门往事", time_value=312.0, narrative_position=3)
        e2 = _event("林尘觉醒金手指", time_value=317.5, narrative_position=2)
        e3 = _event("时间未知事件", time_value=None, narrative_position=1)
        # list_all 契约: (narrative_position ASC, created_at ASC) 稳定排序
        mock_repo.list_all = AsyncMock(return_value=[e3, e2, e1])

        view = await service.get_timeline_view(PID)

        assert view is not None
        assert view.project_id == PID
        assert view.total == 3
        assert [e.title for e in view.event_timeline] == [
            "外门往事",
            "林尘觉醒金手指",
            "时间未知事件",
        ]
        assert [e.title for e in view.narrative_order] == [
            "时间未知事件",
            "林尘觉醒金手指",
            "外门往事",
        ]
        mock_repo.list_all.assert_awaited_once_with(PID.int)

    async def test_get_timeline_view_project_missing_raises(
        self, service: TimelineService, mock_project_repo: MagicMock
    ) -> None:
        """项目不存在 → ProjectNotFoundError（router 层转 404）。"""
        mock_project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            await service.get_timeline_view(PID)

    async def test_check_consistency_orchestration(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """check 编排：list_all → 相邻对扫描 → 报告（视图排序正确）。"""
        e1 = _event("事件一", time_value=5.0, narrative_position=1)
        e2 = _event("事件二", time_value=3.0, narrative_position=2)
        mock_repo.list_all = AsyncMock(return_value=[e1, e2])

        report = await service.check_consistency(PID, include_flashbacks=True)

        assert report is not None
        assert report.project_id == PID
        assert report.checked == 2
        assert report.skipped == 0
        assert report.consistent is False
        assert len(report.conflicts) == 1
        assert report.conflicts[0].conflict_type == "order_conflict"
        assert [e.title for e in report.event_timeline] == ["事件二", "事件一"]
        assert [e.title for e in report.narrative_order] == ["事件一", "事件二"]
        mock_repo.list_all.assert_awaited_once_with(PID.int)
        mock_repo.next_position.assert_not_awaited()

    async def test_check_consistency_project_missing_raises(
        self, service: TimelineService, mock_project_repo: MagicMock
    ) -> None:
        """项目不存在 → ProjectNotFoundError（router 层转 404），不触达仓储。"""
        mock_project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            await service.check_consistency(PID)

    async def test_check_consistency_project_repo_unconfigured_raises(
        self, mock_repo: MagicMock
    ) -> None:
        """project_repo 未注入 → TimelineServiceError（配置错误，防静默降级）。"""
        svc = TimelineService(repository=mock_repo)
        with pytest.raises(TimelineServiceError):
            await svc.check_consistency(PID)


# ── Phase 3 覆盖率补齐（#104）──────────────────────────────────


class TestIntIdAndDelete:
    """int id 直传路径 + 真删编排。"""

    async def test_get_event_with_int_id(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """int id 直传仓储，不做 UUID 转换。"""
        mock_repo.get = AsyncMock(return_value=None)
        assert await service.get_event(42) is None
        mock_repo.get.assert_awaited_once_with(42)

    async def test_delete_event_with_int_id(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """delete_event → 委托 repo.hard_delete（int id），返回结果透传。"""
        assert await service.delete_event(42) is True
        mock_repo.hard_delete.assert_awaited_once_with(42)


class TestConsistencyFlashbacksExcluded:
    """include_flashbacks=False → 已声明倒叙/插叙的对不进入任何分类。"""

    async def test_check_consistency_flashback_excluded(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """后叙事件标记 flashback → 不收集、也不算冲突。"""
        e1 = _event("事件一", time_value=5.0, narrative_position=1)
        e2 = _event("事件二", time_value=3.0, narrative_position=2, timeline_flag="flashback")
        mock_repo.list_all = AsyncMock(return_value=[e1, e2])

        report = await service.check_consistency(PID, include_flashbacks=False)

        assert report is not None
        assert report.flashbacks == []
        assert report.conflicts == []
        assert report.consistent is True
        assert report.checked == 2

    async def test_check_consistency_flashforward_excluded(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """前叙事件标记 flashforward → 不收集、也不算冲突。"""
        e1 = _event("事件一", time_value=10.0, narrative_position=1, timeline_flag="flashforward")
        e2 = _event("事件二", time_value=5.0, narrative_position=2)
        mock_repo.list_all = AsyncMock(return_value=[e1, e2])

        report = await service.check_consistency(PID, include_flashbacks=False)

        assert report is not None
        assert report.flashbacks == []
        assert report.conflicts == []
        assert report.consistent is True

    async def test_check_consistency_flashforward_included(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """include_flashbacks=True → 已声明插叙计入 flashbacks（合法），不影响 consistent。"""
        e1 = _event("事件一", time_value=10.0, narrative_position=1, timeline_flag="flashforward")
        e2 = _event("事件二", time_value=5.0, narrative_position=2)
        mock_repo.list_all = AsyncMock(return_value=[e1, e2])

        report = await service.check_consistency(PID, include_flashbacks=True)

        assert report is not None
        assert len(report.flashbacks) == 1
        assert report.flashbacks[0].conflict_type == "flashforward"
        assert report.flashbacks[0].prev.title == "事件一"
        assert report.flashbacks[0].next.title == "事件二"
        assert report.conflicts == []
        assert report.consistent is True
