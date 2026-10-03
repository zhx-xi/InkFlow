"""#1353 时间线纪元承载 — 服务层契约（f12 spec v1.3 §2.8 + §5.5 边界 + §7）。

【服务层职责（本契约钉住）】
- ``create_event`` / ``update_event`` 接受 ``era`` / ``era_value``，经 ``apply_era``
  落进 ``TimelineEvent.extra``（E1/E2），落库实体（repo.add/repo.update 入参）同样承载
- 成对语义（E4）在服务层被完整执行：未传=不变 / ``""``=删两键 / 非空=写入
- **反例守护（E5/E6）**：未设纪元事件的 create / 一致性检查结论与本 spec v1.2
  **逐字段一致** —— 纪元不进一致性检查（同一批事件加不加纪元，报告等价）

【零 DDL】本契约不新增列、不新增 ``ensure_*``；一切走既有 extra JSON 列。

【RED 预期】服务方法尚无 era 参数 / extra 未落库 → TypeError / AssertionError；
零 SyntaxError / ReferenceError。
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
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.services.timeline_service import TimelineService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 10, 2, 10, 0, 0)


def _event(
    title: str,
    *,
    time_value: float | None = None,
    time_display: str = "",
    narrative_position: int = 1,
    timeline_flag: str = "",
    extra: dict | None = None,
) -> TimelineEvent:
    """构造测试用时间线事件实体（固定时间戳；extra 可注入纪元承载）。"""
    return TimelineEvent(
        id=uuid.uuid4(),
        project_id=PID,
        title=title,
        time_value=time_value,
        time_display=time_display,
        narrative_position=narrative_position,
        timeline_flag=timeline_flag,
        extra=extra or {},
        created_at=TS,
        updated_at=TS,
    )


def _project() -> Project:
    return Project(id=PID, name="测试项目", created_at=TS, updated_at=TS)


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock TimelineRepositoryProtocol（默认全方法可用，测试按需覆盖）。"""
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
def service(mock_repo: MagicMock) -> TimelineService:
    project_repo = MagicMock(spec=ProjectRepositoryProtocol)
    project_repo.get = AsyncMock(return_value=_project())
    return TimelineService(repository=mock_repo, project_repo=project_repo)


class TestCreateEventEra:
    """创建：era/era_value → extra 承载（E1/E2/E4）。"""

    async def test_create_with_era_and_value_writes_extra(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        created = await service.create_event(PID, "事件甲", era="示例历", era_value=317.5)

        assert created.extra == {"era": "示例历", "era_value": 317.5}
        stored = mock_repo.add.await_args.args[0]
        assert stored.extra == {"era": "示例历", "era_value": 317.5}

    async def test_create_with_era_without_value(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        created = await service.create_event(PID, "事件甲", era="示例历")

        assert created.extra == {"era": "示例历"}

    async def test_create_without_era_keeps_empty_extra(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """反例守护：不传纪元 → extra 仍是 {}（与 spec v1.2 完全相同）。"""
        created = await service.create_event(PID, "事件甲")

        assert created.extra == {}
        assert mock_repo.add.await_args.args[0].extra == {}


class TestUpdateEventEra:
    """更新：成对语义四分支（E4）+ 其余 extra 键不受影响。"""

    async def test_update_era_empty_removes_both_keys(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        existing = _event("事件甲", extra={"era": "示例历", "era_value": 317.5, "tags": ["甲"]})
        mock_repo.get = AsyncMock(return_value=existing)

        updated = await service.update_event(existing.id, TimelineEventUpdate(era=""))

        assert updated is not None
        assert updated.extra == {"tags": ["甲"]}

    async def test_update_era_value_alone_is_ignored(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        existing = _event("事件甲", extra={"era": "示例历", "era_value": 317.5})
        mock_repo.get = AsyncMock(return_value=existing)

        updated = await service.update_event(existing.id, TimelineEventUpdate(era_value=999.0))

        assert updated is not None
        assert updated.extra == {"era": "示例历", "era_value": 317.5}

    async def test_update_rename_axis_keeps_value(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        existing = _event("事件甲", extra={"era": "示例历", "era_value": 317.5})
        mock_repo.get = AsyncMock(return_value=existing)

        updated = await service.update_event(existing.id, TimelineEventUpdate(era="示例仙历"))

        assert updated is not None
        assert updated.extra == {"era": "示例仙历", "era_value": 317.5}

    async def test_update_era_value_empty_with_axis_clears_value_only(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """§2.8 E4 ③：era 非空 + era_value="" ⇒ 只删轴内值键，保留轴名。"""
        existing = _event("事件甲", extra={"era": "示例历", "era_value": 317.5})
        mock_repo.get = AsyncMock(return_value=existing)

        updated = await service.update_event(
            existing.id, TimelineEventUpdate(era="示例历", era_value="")
        )

        assert updated is not None
        assert updated.extra == {"era": "示例历"}

    async def test_update_era_value_empty_without_axis_is_ignored(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """§2.8 E4 ①：era 未传 ⇒ extra 整体不变（`era_value=""` 亦被忽略，不产生静默改写）。"""
        existing = _event("事件甲", extra={"era": "示例历", "era_value": 317.5})
        mock_repo.get = AsyncMock(return_value=existing)

        updated = await service.update_event(existing.id, TimelineEventUpdate(era_value=""))

        assert updated is not None
        assert updated.extra == {"era": "示例历", "era_value": 317.5}

    async def test_update_without_era_keeps_extra_untouched(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        """反例守护：只改标题 → extra 原样（纪元不受影响）。"""
        existing = _event("事件甲", extra={"era": "示例历", "era_value": 317.5})
        mock_repo.get = AsyncMock(return_value=existing)

        updated = await service.update_event(existing.id, TimelineEventUpdate(title="事件乙"))

        assert updated is not None
        assert updated.title == "事件乙"
        assert updated.extra == {"era": "示例历", "era_value": 317.5}


class TestEraDoesNotAffectCheck:
    """反例守护（E6）：纪元不进一致性检查 —— 同一批事件加不加纪元，报告等价。"""

    async def test_check_report_equivalent_with_and_without_era(
        self, service: TimelineService, mock_repo: MagicMock
    ) -> None:
        plain = [
            _event("事件甲", time_value=10.0, narrative_position=1),
            _event("事件乙", time_value=5.0, narrative_position=2),
            _event("事件丙", time_value=None, narrative_position=3),
        ]
        with_era = [
            e.model_copy(update={"extra": {"era": "示例历", "era_value": float(i)}})
            if e.time_value is not None
            else e
            for i, e in enumerate(plain, start=1)
        ]

        mock_repo.list_all = AsyncMock(return_value=plain)
        without = await service.check_consistency(PID)
        mock_repo.list_all = AsyncMock(return_value=with_era)
        withx = await service.check_consistency(PID)

        assert without is not None
        assert withx is not None
        assert (withx.checked, withx.skipped, withx.consistent) == (
            without.checked,
            without.skipped,
            without.consistent,
        )
        assert [c.conflict_type for c in withx.conflicts] == [
            c.conflict_type for c in without.conflicts
        ]
        assert [(c.prev.id, c.next.id) for c in withx.conflicts] == [
            (c.prev.id, c.next.id) for c in without.conflicts
        ]
        # 事件时间线视图顺序（归一日尺度排序）不因纪元改变
        assert [e.id for e in withx.event_timeline] == [e.id for e in without.event_timeline]
