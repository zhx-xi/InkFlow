"""F12 一致性检查算法专项测试 — 构造序列用例 + 快照断言（spec §5/§9）.

覆盖 spec §9 检查算法全部场景（确定性算法，无 LLM）:
- 正叙/单逆序/混合/全逆序序列 → order_conflict 报告与完备性（§5.3）
- flashback / flashforward 声明 → 合法（计入 flashbacks，不影响 consistent）
- 未知标记值等同未标记；未标记 + 已标记混合只报未标记
- 同刻事件不冲突；时间未知计入 skipped；0/1 个事件恒一致
- include_flashbacks=false → flashbacks 空列表，conflicts/consistent 不变
- 真删事件不参与；快照断言（同一集合两次检查逐字段相等）
- 报告视图正确性（event_timeline 升序未知末尾 / narrative_order 叙事升序）

实现说明: 直接用真实 TimelineService + 内存 Fake repo（list_all 按
(narrative_position, created_at) 稳定排序并排除软删），比 Mock 更易
构造任意事件序列。

依据: specs/f12-timeline-service/spec.md §5.3/§5.4/§5.5 + §9。
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from inkflow.domain.models.project import Project
from inkflow.domain.models.timeline import ConsistencyReport, TimelineEvent
from inkflow.domain.services.timeline_service import TimelineService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


class FakeTimelineRepo:
    """内存版 TimelineRepositoryProtocol — 一致性检查测试用.

    list_all 按 (narrative_position ASC, created_at ASC) 稳定排序（真删
    契约下无软删状态，所有现存事件均参与，spec §8.1）。
    """

    def __init__(self, events: list[TimelineEvent]) -> None:
        self._events = list(events)

    async def add(self, event: TimelineEvent) -> TimelineEvent:
        self._events.append(event)
        return event

    async def get(self, event_id: int) -> TimelineEvent | None:
        return next((e for e in self._events if e.id.int == event_id), None)

    async def list(
        self,
        project_id: int,
        search: str | None = None,
        sort_by: str = "narrative_position",
        sort_desc: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TimelineEvent], int]:
        events = await self.list_all(project_id)
        if search:
            events = [e for e in events if search.lower() in e.title.lower()]
        return events, len(events)

    async def list_all(self, project_id: int) -> list[TimelineEvent]:
        events = [e for e in self._events if e.project_id.int == project_id]
        return sorted(events, key=lambda e: (e.narrative_position, e.created_at))

    async def next_position(self, project_id: int) -> int:
        events = await self.list_all(project_id)
        return max((e.narrative_position for e in events), default=0) + 1

    async def update(self, event: TimelineEvent) -> TimelineEvent:
        for i, e in enumerate(self._events):
            if e.id == event.id:
                self._events[i] = event
                return event
        raise KeyError(event.id)

    async def hard_delete(self, event_id: int) -> bool:
        before = len(self._events)
        self._events = [e for e in self._events if e.id.int != event_id]
        return len(self._events) < before


class FakeProjectRepo:
    """内存版 ProjectRepositoryProtocol — 项目存在性校验."""

    def __init__(self, exists: bool = True) -> None:
        self._exists = exists

    async def get(self, project_id: int) -> Project | None:
        if not self._exists:
            return None
        return Project(
            id=uuid.UUID(int=project_id),
            name="测试项目",
            created_at=TS,
            updated_at=TS,
        )


def _event(
    title: str,
    *,
    time_value: float | None = None,
    time_display: str = "",
    narrative_position: int = 1,
    timeline_flag: str = "",
) -> TimelineEvent:
    """构造测试用时间线事件实体（固定时间戳）。"""
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


def _seq(*values: float | None, flags: dict[int, str] | None = None) -> list[TimelineEvent]:
    """按叙事顺序构造事件序列：values 为各事件 time_value（None = 时间未知）。

    Args:
        values: 事件的世界内时间序列（顺序即叙事位置 1..n）.
        flags: 叙事位置 → timeline_flag 映射（可选）.

    Returns:
        按叙事位置 1..n 排列的事件列表.
    """
    flags = flags or {}
    return [
        _event(
            f"事件{i}",
            time_value=v,
            narrative_position=i,
            timeline_flag=flags.get(i, ""),
        )
        for i, v in enumerate(values, start=1)
    ]


def _make_service(events: list[TimelineEvent], *, project_exists: bool = True) -> TimelineService:
    """构造被测服务（真实 TimelineService + Fake repo）。"""
    return TimelineService(
        repository=FakeTimelineRepo(events),
        project_repo=FakeProjectRepo(project_exists),
    )


@pytest.mark.asyncio
async def test_forward_sequence_no_conflicts() -> None:
    """正叙序列 [1,2,3,4] → 无冲突，consistent=true，checked=4，skipped=0。"""
    report = await _make_service(_seq(1.0, 2.0, 3.0, 4.0)).check_consistency(PID)
    assert report is not None
    assert report.checked == 4
    assert report.skipped == 0
    assert report.consistent is True
    assert report.conflicts == []
    assert report.flashbacks == []


@pytest.mark.asyncio
async def test_single_inversion_reports_order_conflict() -> None:
    """单逆序对 [1,3,2,4] → 1 条 order_conflict（相邻对 3,2），message 按 §3.3 格式。"""
    report = await _make_service(_seq(1.0, 3.0, 2.0, 4.0)).check_consistency(PID)
    assert report is not None
    assert report.checked == 4
    assert report.consistent is False
    assert len(report.conflicts) == 1
    conflict = report.conflicts[0]
    assert conflict.conflict_type == "order_conflict"
    assert conflict.prev.title == "事件2"
    assert conflict.prev.narrative_position == 2
    assert conflict.prev.time_value == 3.0
    assert conflict.next.title == "事件3"
    assert conflict.next.narrative_position == 3
    assert conflict.next.time_value == 2.0
    assert conflict.message == (
        "叙事第 2 位事件「事件2」（3.0）晚于叙事第 3 位事件「事件3」（2.0）："
        "叙事顺序与世界内时间矛盾。若为倒叙/插叙请给后叙事件标记 "
        "timeline_flag=flashback（或前叙事件标记 flashforward）；"
        "否则请修正事件时间或叙事位置。"
    )


@pytest.mark.asyncio
async def test_mixed_sequence_reports_only_adjacent_inversion() -> None:
    """混合序列 [10,5,8] → 1 条冲突（相邻对 10,5），完备性：修正后重查即收敛。"""
    report = await _make_service(_seq(10.0, 5.0, 8.0)).check_consistency(PID)
    assert report is not None
    assert report.checked == 3
    assert report.consistent is False
    assert len(report.conflicts) == 1
    assert report.conflicts[0].prev.title == "事件1"
    assert report.conflicts[0].prev.time_value == 10.0
    assert report.conflicts[0].next.title == "事件2"
    assert report.conflicts[0].next.time_value == 5.0


@pytest.mark.asyncio
async def test_full_reversal_reports_all_inversions() -> None:
    """全逆序 [4,3,2,1] 未标记 → 3 条 order_conflict（每条独立可修正）。"""
    report = await _make_service(_seq(4.0, 3.0, 2.0, 1.0)).check_consistency(PID)
    assert report is not None
    assert report.checked == 4
    assert report.consistent is False
    assert len(report.conflicts) == 3
    assert [c.prev.narrative_position for c in report.conflicts] == [1, 2, 3]
    assert [c.next.narrative_position for c in report.conflicts] == [2, 3, 4]
    assert report.flashbacks == []


@pytest.mark.asyncio
async def test_flashback_declaration_is_legal() -> None:
    """逆序对 next 标记 flashback → flashbacks 含该项，conflicts 空，consistent=true。"""
    report = await _make_service(_seq(10.0, 5.0, flags={2: "flashback"})).check_consistency(PID)
    assert report is not None
    assert report.consistent is True
    assert report.conflicts == []
    assert len(report.flashbacks) == 1
    entry = report.flashbacks[0]
    assert entry.conflict_type == "flashback"
    assert entry.prev.title == "事件1"
    assert entry.next.title == "事件2"
    assert entry.message == (
        "叙事第 2 位事件「事件2」声明为倒叙（flashback）："
        "其世界内时间（5.0）早于前叙事件（10.0），已标记，判定合法。"
    )


@pytest.mark.asyncio
async def test_flashforward_declaration_is_legal() -> None:
    """逆序对 prev 标记 flashforward → flashbacks 含该项（flashforward 类型）。"""
    report = await _make_service(_seq(10.0, 5.0, flags={1: "flashforward"})).check_consistency(PID)
    assert report is not None
    assert report.consistent is True
    assert report.conflicts == []
    assert len(report.flashbacks) == 1
    entry = report.flashbacks[0]
    assert entry.conflict_type == "flashforward"
    assert entry.prev.title == "事件1"
    assert entry.next.title == "事件2"


@pytest.mark.asyncio
async def test_unknown_flag_treated_as_unmarked() -> None:
    """未知标记值（如拼写错误 \"flshback\"）→ 等同未标记 → order_conflict。"""
    report = await _make_service(_seq(10.0, 5.0, flags={2: "flshback"})).check_consistency(PID)
    assert report is not None
    assert report.consistent is False
    assert len(report.conflicts) == 1
    assert report.conflicts[0].conflict_type == "order_conflict"
    assert report.flashbacks == []


@pytest.mark.asyncio
async def test_mixed_marked_and_unmarked_reports_only_unmarked() -> None:
    """未标记 + 已标记混合 [10,5,8,2]（5 已声明 flashback）→ 只报未标记的 (8,2)。"""
    report = await _make_service(
        _seq(10.0, 5.0, 8.0, 2.0, flags={2: "flashback"})
    ).check_consistency(PID)
    assert report is not None
    assert report.consistent is False
    assert len(report.conflicts) == 1
    assert report.conflicts[0].prev.title == "事件3"
    assert report.conflicts[0].next.title == "事件4"
    assert len(report.flashbacks) == 1
    assert report.flashbacks[0].conflict_type == "flashback"
    assert report.flashbacks[0].prev.title == "事件1"


@pytest.mark.asyncio
async def test_same_time_events_no_conflict() -> None:
    """同刻事件 [3,3,4] → 相等时间不冲突（叙事顺序可任意排列）。"""
    report = await _make_service(_seq(3.0, 3.0, 4.0)).check_consistency(PID)
    assert report is not None
    assert report.consistent is True
    assert report.checked == 3
    assert report.conflicts == []
    assert report.flashbacks == []


@pytest.mark.asyncio
async def test_unknown_time_events_skipped() -> None:
    """时间未知事件计入 skipped，不参与比较：[None,5,3] → checked=2, skipped=1, 1 条冲突。"""
    report = await _make_service(_seq(None, 5.0, 3.0)).check_consistency(PID)
    assert report is not None
    assert report.checked == 2
    assert report.skipped == 1
    assert report.consistent is False
    assert len(report.conflicts) == 1
    assert report.conflicts[0].prev.narrative_position == 2
    assert report.conflicts[0].next.narrative_position == 3


@pytest.mark.asyncio
async def test_all_unknown_times_consistent() -> None:
    """全部时间未知 → checked=0, skipped=n, consistent=true（未定时间不产生矛盾）。"""
    report = await _make_service(_seq(None, None, None)).check_consistency(PID)
    assert report is not None
    assert report.checked == 0
    assert report.skipped == 3
    assert report.consistent is True
    assert report.conflicts == []
    assert report.flashbacks == []


@pytest.mark.asyncio
async def test_zero_and_one_event_consistent() -> None:
    """0 / 1 个事件 → consistent=true（空时间线无矛盾可言）。"""
    empty = await _make_service([]).check_consistency(PID)
    assert empty is not None
    assert empty.checked == 0
    assert empty.skipped == 0
    assert empty.consistent is True

    single = await _make_service(_seq(1.0)).check_consistency(PID)
    assert single is not None
    assert single.checked == 1
    assert single.consistent is True


@pytest.mark.asyncio
async def test_include_flashbacks_false_empties_flashbacks() -> None:
    """include_flashbacks=false → flashbacks 空列表；conflicts/consistent 不受影响。"""
    events = _seq(10.0, 5.0, 8.0, 2.0, flags={2: "flashback"})
    report = await _make_service(events).check_consistency(PID, include_flashbacks=False)
    assert report is not None
    assert report.flashbacks == []
    assert len(report.conflicts) == 1  # (8,2) 未标记冲突仍报告
    assert report.consistent is False

    # 纯合法倒叙场景：flashbacks 被清空后 consistent 仍为 true
    legal = await _make_service(_seq(10.0, 5.0, flags={2: "flashback"})).check_consistency(
        PID, include_flashbacks=False
    )
    assert legal is not None
    assert legal.flashbacks == []
    assert legal.conflicts == []
    assert legal.consistent is True


@pytest.mark.asyncio
async def test_deterministic_snapshot_equality() -> None:
    """快照断言：同一事件集合两次检查 → 报告逐字段相等（确定性算法）。"""
    events = _seq(10.0, 5.0, 8.0, None, 2.0, flags={2: "flashback"})
    svc = _make_service(events)
    first = await svc.check_consistency(PID)
    second = await svc.check_consistency(PID)
    assert first is not None and second is not None
    assert first == second
    assert first.model_dump() == second.model_dump()
    assert isinstance(first, ConsistencyReport)


@pytest.mark.asyncio
async def test_report_views_sorted_correctly() -> None:
    """报告视图正确性：event_timeline 按 time_value 升序（未知排末尾）、
    narrative_order 按叙事位置升序。"""
    events = [
        _event("时间未知", time_value=None, narrative_position=3),
        _event("事件A", time_value=5.0, narrative_position=1),
        _event("事件B", time_value=3.0, narrative_position=4),
        _event("事件C", time_value=4.0, narrative_position=2),
    ]
    report = await _make_service(events).check_consistency(PID)
    assert report is not None
    assert [e.title for e in report.event_timeline] == [
        "事件B",
        "事件C",
        "事件A",
        "时间未知",
    ]
    assert [e.title for e in report.narrative_order] == [
        "事件A",
        "事件C",
        "时间未知",
        "事件B",
    ]
    assert report.checked == 3
    assert report.skipped == 1


@pytest.mark.asyncio
async def test_check_project_missing_raises_not_found() -> None:
    """项目不存在 → check 入口抛 ProjectNotFoundError（router 层转 404）。"""
    svc = _make_service([], project_exists=False)
    from inkflow.domain.ports.timeline_errors import ProjectNotFoundError

    with pytest.raises(ProjectNotFoundError):
        await svc.check_consistency(PID)


# ══════════════════════════════════════════════════════════════════════
# F43 P4 追加段：单事件检查 check_event 契约（spec §2.9/§3.7/§9.7 T 系列）
# 纯插入追加（git diff 删除列 0），严禁覆盖既有用例。RED 预期形态:
# - TB1-TB4 service: TimelineService 无 check_event 方法 → AttributeError（FAILED）
# - TB5 api: EventCheckReport 缺失 → 用例体 lazy import ImportError（FAILED 形态，
#   非收集 ERROR）；GREEN 后若端点漏注册 → assert 200 == 404 兜底
# GREEN 必实现:
# - domain/models/timeline.py 新增 EventCheckReport（event_id: uuid.UUID、
#   checked: bool、consistent: bool、conflicts: list[TimelineConflict] = []、
#   flashbacks: list[TimelineConflict] = []，spec §2.9）
# - TimelineService.check_event(event_id) → EventCheckReport | None:
#   repo.get 取事件（不存在 → 返回 None）；取该事件叙事相邻事件（prev/next），
#   复用 check_consistency 相邻对分类（prev.time > next.time 且 next 标
#   flashback → flashbacks；prev 标 flashforward → flashbacks；否则 conflicts）；
#   事件 time_value None → checked=false 且 conflicts/flashbacks 空 consistent=true
# - api/routers/timeline.py: GET /timeline/events/{event_id}/check →
#   _run_service(svc.check_event(eid))；None → 404「事件不存在」；
#   否则 report.model_dump(mode="json")
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_tb1_check_event_reports_participating_order_conflict() -> None:
    """TB1 service：check_event 返回该事件参与的逆序冲突（order_conflict）.

    [1.0, 3.0, 2.0, 4.0]：唯一逆序对 (事件2, 事件3)；目标=事件2（作为 prev 参与）→
    conflicts 恰 1 条 order_conflict，flashbacks 空。
    RED 预期: TimelineService 无 check_event 方法 → AttributeError（service 层失败形态）。
    """
    events = _seq(1.0, 3.0, 2.0, 4.0)
    target = events[1]  # 事件2（time=3.0，逆序对 prev）
    report = await _make_service(events).check_event(target.id)  # RED: AttributeError
    assert report is not None
    assert report.event_id == target.id
    assert report.checked is True
    assert report.consistent is False
    assert len(report.conflicts) == 1
    conflict = report.conflicts[0]
    assert conflict.conflict_type == "order_conflict"
    assert conflict.prev.id == target.id
    assert conflict.next.id == events[2].id
    assert report.flashbacks == []


@pytest.mark.asyncio
async def test_tb2_check_event_flashback_flashforward_classification() -> None:
    """TB2 service：check_event flashback/flashforward 分类正确.

    - [10.0, 5.0] flags={2: flashback}：逆序对 next 标 flashback → 目标=事件2 →
      flashbacks[0].conflict_type == "flashback"
    - [10.0, 5.0] flags={1: flashforward}：逆序对 prev 标 flashforward → 目标=事件1 →
      flashbacks[0].conflict_type == "flashforward"
    RED 预期: check_event 缺失 → AttributeError（service 层失败形态）。
    """
    fb_events = _seq(10.0, 5.0, flags={2: "flashback"})
    fb_target = fb_events[1]
    fb = await _make_service(fb_events).check_event(fb_target.id)
    assert fb is not None
    assert fb.checked is True
    assert fb.conflicts == []
    assert len(fb.flashbacks) == 1
    assert fb.flashbacks[0].conflict_type == "flashback"
    assert fb.flashbacks[0].next.id == fb_target.id

    ff_events = _seq(10.0, 5.0, flags={1: "flashforward"})
    ff_target = ff_events[0]
    ff = await _make_service(ff_events).check_event(ff_target.id)
    assert ff is not None
    assert ff.conflicts == []
    assert len(ff.flashbacks) == 1
    assert ff.flashbacks[0].conflict_type == "flashforward"
    assert ff.flashbacks[0].prev.id == ff_target.id


@pytest.mark.asyncio
async def test_tb3_check_event_unknown_time_checked_false() -> None:
    """TB3 service：check_event time_value None → checked=false，consistent=true.

    目标=事件2（time_value=None，两侧邻居时间已知）；不参与检查 →
    checked=false 且 conflicts/flashbacks 均空（非冲突）。
    RED 预期: check_event 缺失 → AttributeError（service 层失败形态）。
    """
    events = _seq(1.0, None, 3.0)
    target = events[1]
    report = await _make_service(events).check_event(target.id)
    assert report is not None
    assert report.event_id == target.id
    assert report.checked is False
    assert report.consistent is True
    assert report.conflicts == []
    assert report.flashbacks == []


@pytest.mark.asyncio
async def test_tb4_check_event_missing_event_returns_none() -> None:
    """TB4 service：check_event 事件不存在 → 返回 None（router 转 404「事件不存在」）.

    RED 预期: check_event 缺失 → AttributeError（service 层失败形态）。
    GREEN 必实现: repo.get 未命中 → return None。
    """
    svc = _make_service(_seq(1.0, 2.0))
    report = await svc.check_event(uuid.uuid4())  # RED: AttributeError
    assert report is None


def test_tb5_api_event_check_returns_report() -> None:
    """TB5 api：GET /timeline/events/{id}/check 返回 EventCheckReport.

    含 event_id/checked/consistent/conflicts 字段；RED 预期: ① EventCheckReport
    缺失 → 用例体 lazy import ImportError（FAILED 形态，非收集 ERROR）；
    ② GREEN 后端点漏注册 → 404 → assert 200 == 404 兜底。
    GREEN 必实现: router 新增 GET /timeline/events/{event_id}/check →
    _run_service(svc.check_event(eid))；check_event 返回 None → 404「事件不存在」；
    否则 report.model_dump(mode="json")。
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi.testclient import TestClient

    from inkflow.api.app import app
    from inkflow.domain.models.timeline import (  # RED: ImportError（EventCheckReport 缺失）
        EventCheckReport,
        TimelineConflict,
        TimelineEventRef,
    )

    event_id = uuid.uuid4()
    report = EventCheckReport(
        event_id=event_id,
        checked=True,
        consistent=False,
        conflicts=[
            TimelineConflict(
                conflict_type="order_conflict",
                prev=TimelineEventRef(
                    id=uuid.uuid4(),
                    title="宗门大比夺冠",
                    time_value=319.0,
                    time_display="青元历 319 年夏",
                    narrative_position=4,
                    timeline_flag="",
                ),
                next=TimelineEventRef(
                    id=event_id,
                    title="外门往事",
                    time_value=312.0,
                    time_display="青元历 312 年",
                    narrative_position=5,
                    timeline_flag="",
                ),
                message="叙事顺序与世界内时间矛盾。",
            )
        ],
        flashbacks=[],
    )
    with patch("inkflow.api.routers.timeline.get_timeline_service") as mock_get_svc:
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.check_event = AsyncMock(return_value=report)

        client = TestClient(app)
        response = client.get(f"/api/v1/timeline/events/{event_id}/check")
        assert response.status_code == 200
        data = response.json()
        assert data["event_id"] == str(event_id)
        assert data["checked"] is True
        assert data["consistent"] is False
        assert data["conflicts"][0]["conflict_type"] == "order_conflict"
        assert data["flashbacks"] == []
        svc.check_event.assert_awaited_once_with(event_id)
