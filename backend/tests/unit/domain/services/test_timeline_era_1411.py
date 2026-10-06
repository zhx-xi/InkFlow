"""#1411 跨纪元流速换算 — 一致性检查按轴分桶（f12 spec v1.5 §2.8 E11 / §5.3 / §5.5）。

【服务层职责（本契约钉住）】
- ``check_consistency`` / ``check_event`` 先按 ``era`` **分桶**：默认轴沿用 §2.7 归一日尺度
  （v1.4 口径**不变**），纪元轴用 ``to_global`` 换算后的**全局标量**；**跨桶**按换算后
  全局标量比较（ADR-065 §2.1，**R6-5 裁定 = 不降级**）；
- **假阳性归零**：跨纪元数据不再产生「未声明的倒叙」误报（对照 #1409 的 7 → 0 口径）；
- **默认轴零变化**：无纪元事件结论与 v1.4 逐字段一致（反例守护）；
- **连带面**：``check_event`` 与 F34 审计规则（``AuditService`` 的
  ``timeline.dual_consistency``）与 ``check_consistency`` 同口径。

实现说明: 真实 TimelineService + 内存 Fake repo（同 test_timeline_check.py 口径）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from inkflow.domain.models.project import Project
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.services.audit_service import AuditService
from inkflow.domain.services.timeline_service import TimelineService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 10, 6, 10, 0, 0)


class FakeTimelineRepo:
    """内存版 TimelineRepositoryProtocol（list_all 按叙事序稳定排序）。"""

    def __init__(self, events: list[TimelineEvent]) -> None:
        self._events = list(events)

    async def add(self, event: TimelineEvent) -> TimelineEvent:
        self._events.append(event)
        return event

    async def get(self, event_id: uuid.UUID) -> TimelineEvent | None:
        return next((e for e in self._events if e.id == event_id), None)

    async def list_all(self, project_id: uuid.UUID) -> list[TimelineEvent]:
        events = [e for e in self._events if e.project_id == project_id]
        return sorted(events, key=lambda e: (e.narrative_position, e.created_at))

    async def update(self, event: TimelineEvent) -> TimelineEvent:
        for i, e in enumerate(self._events):
            if e.id == event.id:
                self._events[i] = event
                return event
        raise KeyError(event.id)

    async def hard_delete(self, event_id: uuid.UUID) -> bool:
        before = len(self._events)
        self._events = [e for e in self._events if e.id != event_id]
        return len(self._events) < before


def _event(
    title: str,
    *,
    time_value: float | None = None,
    narrative_position: int = 1,
    era: str = "",
    era_value: float | None = None,
    era_scale: float = 1.0,
    timeline_flag: str = "",
) -> TimelineEvent:
    """构造测试用时间线事件（纪元由正式列承载，§2.8）。"""
    return TimelineEvent(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        time_value=time_value,
        narrative_position=narrative_position,
        timeline_flag=timeline_flag,
        era=era,
        era_value=era_value,
        era_scale=era_scale,
        created_at=TS,
        updated_at=TS,
    )


def _project() -> Project:
    return Project(id=PID, name="测试项目", created_at=TS, updated_at=TS)


def _service(events: list[TimelineEvent]) -> TimelineService:
    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=_project())
    return TimelineService(repository=FakeTimelineRepo(events), project_repo=project_repo)


class TestCrossEraBucketedComparison:
    """跨纪元经换算比较（§5.3）：等值不冲突；真逆序仍报；假阳性归零。"""

    async def test_equal_global_scalar_across_axes_no_conflict(self) -> None:
        """甲纪元 1 单位 = 乙纪元 2 单位（甲 scale=1 / 乙 scale=2）→ 换算后同值 → 0 冲突。"""
        events = [
            _event("甲轴事件", era="甲纪", era_value=1.0, era_scale=1.0, narrative_position=1),
            _event("乙轴事件", era="乙纪", era_value=2.0, era_scale=2.0, narrative_position=2),
        ]
        report = await _service(events).check_consistency(PID)
        assert report is not None
        assert report.checked == 2
        assert report.consistent is True
        assert report.conflicts == []

    async def test_true_cross_era_reverse_reported(self) -> None:
        """甲 5（全局 5）→ 乙 2（全局 1）：真实倒退 → 1 条 order_conflict。"""
        events = [
            _event("甲轴事件", era="甲纪", era_value=5.0, era_scale=1.0, narrative_position=1),
            _event("乙轴事件", era="乙纪", era_value=2.0, era_scale=2.0, narrative_position=2),
        ]
        report = await _service(events).check_consistency(PID)
        assert report is not None
        assert report.consistent is False
        assert [c.conflict_type for c in report.conflicts] == ["order_conflict"]

    async def test_false_positive_eliminated_by_conversion(self) -> None:
        """假阳性归零：旧口径（裸比，2 > 1）会误报；换算后同值 → 0 冲突。"""
        events = [
            _event(
                "乙轴先叙",
                era="乙纪",
                era_value=2.0,
                era_scale=2.0,
                time_value=2.0,  # 旧口径下会被直接比较 → 误报
                narrative_position=1,
            ),
            _event(
                "甲轴后叙",
                era="甲纪",
                era_value=1.0,
                era_scale=1.0,
                time_value=1.0,
                narrative_position=2,
            ),
        ]
        report = await _service(events).check_consistency(PID)
        assert report is not None
        assert report.conflicts == []

    async def test_era_scale_default_one_equivalent_to_raw_era_value(self) -> None:
        """scale 缺省 1.0 ⇒ 等价「直比轴内值」：2 > 1 → 真逆序（与 T1 行为一致）。"""
        events = [
            _event("甲", era="甲纪", era_value=2.0, narrative_position=1),
            _event("乙", era="乙纪", era_value=1.0, narrative_position=2),
        ]
        report = await _service(events).check_consistency(PID)
        assert report is not None
        assert len(report.conflicts) == 1

    async def test_era_value_none_is_skipped(self) -> None:
        """纪元轴内值未知 → 全局标量 None → 计入 skipped（不报冲突）。"""
        events = [
            _event("甲", era="甲纪", era_value=None, narrative_position=1),
            _event("乙", era="乙纪", era_value=3.0, narrative_position=2),
        ]
        report = await _service(events).check_consistency(PID)
        assert report is not None
        assert report.checked == 1
        assert report.skipped == 1
        assert report.conflicts == []


class TestDefaultAxisUnchanged:
    """反例守护：默认轴（era=""）事件结论与 v1.4 逐字段一致。"""

    async def test_no_era_events_behave_as_before(self) -> None:
        events = [
            _event("甲", time_value=10.0, narrative_position=1),
            _event("乙", time_value=5.0, narrative_position=2),
        ]
        report = await _service(events).check_consistency(PID)
        assert report is not None
        assert report.consistent is False
        assert len(report.conflicts) == 1

    async def test_event_timeline_sorted_by_global_scalar(self) -> None:
        """事件时间线按**全局标量**排序（纪元轴经 to_global 换算）。"""
        events = [
            _event("晚", era="甲纪", era_value=10.0, narrative_position=1),
            _event("早", era="甲纪", era_value=1.0, narrative_position=2),
        ]
        view = await _service(events).get_timeline_view(PID)
        assert view is not None
        assert [e.title for e in view.event_timeline] == ["早", "晚"]


class TestLinkedSurfacesSameSemantics:
    """连带面：check_event 与 F34 审计规则与 check_consistency 同口径。"""

    async def test_check_event_matches_consistency_for_cross_era(self) -> None:
        events = [
            _event("甲", era="甲纪", era_value=5.0, era_scale=1.0, narrative_position=1),
            _event("乙", era="乙纪", era_value=2.0, era_scale=2.0, narrative_position=2),
        ]
        svc = _service(events)
        report = await svc.check_consistency(PID)
        single = await svc.check_event(events[0].id)
        assert report is not None
        assert single is not None
        assert len(single.conflicts) == len(report.conflicts) == 1

    async def test_f34_audit_converts_cross_era_conflicts(self) -> None:
        events = [
            _event("甲", era="甲纪", era_value=5.0, era_scale=1.0, narrative_position=1),
            _event("乙", era="乙纪", era_value=2.0, era_scale=2.0, narrative_position=2),
        ]
        svc = _service(events)
        report = await svc.check_consistency(PID)
        empty_list = AsyncMock(return_value=([], 0))
        project_repo = MagicMock()
        project_repo.get = AsyncMock(return_value=_project())
        audit = AuditService(
            project_repo=project_repo,
            character_repo=MagicMock(
                list=empty_list,
                list_relations=AsyncMock(return_value=[]),
                list_groups=AsyncMock(return_value=[]),
            ),
            world_repo=MagicMock(list=empty_list),
            timeline_service=svc,
            foreshadowing_repo=MagicMock(list=empty_list),
            chapter_repo=MagicMock(list_chapters=empty_list),
            run_repo=MagicMock(list=empty_list),
        )
        audit_report = await audit.run_audit(PID)
        assert report is not None
        timeline_findings = [
            f for f in audit_report.findings if f.rule_id == "timeline.dual_consistency"
        ]
        assert len(timeline_findings) == len(report.conflicts) == 1
