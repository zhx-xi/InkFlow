"""R-F1/R-F2/R-X1/R-X2 规则 + 服务编排 — Mock 各仓储 + TimelineService + AuditRepositoryProtocol。

覆盖: R-F1/F2 事件锚点与状态机 / R-X1/X2 来源与 run 缺口 + 编排（404/分页/counts）。

拆分自 test_audit_service.py（#281 测试文件规模治理）；
共享 helper/_Deps 定义见本文件（各拆分文件自包含副本）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.audit import AuditDimension, AuditSeverity
from inkflow.domain.models.chapter import Chapter
from inkflow.domain.models.character import (
    Character,
    CharacterGroup,
    CharacterRelation,
)
from inkflow.domain.models.extraction import ExtractionRun, ExtractionStatus, ExtractionType
from inkflow.domain.models.foreshadowing import Foreshadowing, ForeshadowingStatus
from inkflow.domain.models.project import Project
from inkflow.domain.models.timeline import (
    ConsistencyReport,
    TimelineConflict,
    TimelineEvent,
    TimelineEventRef,
    TimelineView,
)
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.audit_errors import ProjectNotFoundError
from inkflow.domain.services.audit_service import AuditService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)

# 常用实体 UUID（各测试共享，便于稳定断言）
# 注: #211 真删语义下 *_DELETED 常量用作「悬空引用 id」（不在活动集合 → error）
C_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
C_B = uuid.UUID("22222222-2222-4222-8222-222222222222")
C_DELETED = uuid.UUID("33333333-3333-4333-8333-333333333333")
C_MISSING = uuid.UUID("44444444-4444-4444-8444-444444444444")
G_ACTIVE = uuid.UUID("55555555-5555-4555-8555-555555555555")
G_DELETED = uuid.UUID("66666666-6666-4666-8666-666666666666")
G_MISSING = uuid.UUID("77777777-7777-4777-8777-777777777777")
EV_1 = uuid.UUID("88888888-8888-4888-8888-888888888888")
EV_2 = uuid.UUID("99999999-9999-4999-8999-999999999999")
EV_3 = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EV_4 = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
EV_DELETED = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
EV_MISSING = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
CH_1 = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
CH_2 = uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")


# ── 实体构造 helpers ──────────────────────────────────────────────


def _project() -> Project:
    """构造测试项目（属于 PID）。"""
    return Project(id=PID, name="测试项目", created_at=TS, updated_at=TS)


def _char(cid: uuid.UUID, name: str, *, group_id: uuid.UUID | None = None) -> Character:
    """构造测试角色实体。"""
    return Character(
        id=cid,
        project_id=PID,
        name=name,
        group_id=group_id,
        created_at=TS,
        updated_at=TS,
    )


def _group(gid: uuid.UUID, name: str = "分组") -> CharacterGroup:
    """构造测试分组实体。"""
    return CharacterGroup(id=gid, project_id=PID, name=name, created_at=TS, updated_at=TS)


def _rel(
    rid: uuid.UUID,
    from_id: uuid.UUID,
    to_id: uuid.UUID,
    relation_type: str = "敌对",
) -> CharacterRelation:
    """构造测试关系实体。"""
    return CharacterRelation(
        id=rid,
        project_id=PID,
        from_character_id=from_id,
        to_character_id=to_id,
        relation_type=relation_type,
        created_at=TS,
        updated_at=TS,
    )


def _setting(sid: uuid.UUID, name: str, content: str = "") -> WorldSetting:
    """构造测试世界条目实体。"""
    return WorldSetting(
        id=sid, project_id=PID, name=name, content=content, created_at=TS, updated_at=TS
    )


def _event(
    eid: uuid.UUID,
    title: str,
    *,
    source_chapter_id: uuid.UUID | None = None,
) -> TimelineEvent:
    """构造测试时间线事件实体。"""
    return TimelineEvent(
        id=eid,
        project_id=PID,
        title=title,
        source_chapter_id=source_chapter_id,
        created_at=TS,
        updated_at=TS,
    )


def _foreshadowing(
    fid: uuid.UUID,
    title: str,
    *,
    event_id: uuid.UUID | None = None,
    status: ForeshadowingStatus = ForeshadowingStatus.OPEN,
    resolved_at: datetime | None = None,
) -> Foreshadowing:
    """构造测试伏笔实体。"""
    return Foreshadowing(
        id=fid,
        project_id=PID,
        title=title,
        event_id=event_id,
        status=status,
        resolved_at=resolved_at,
        created_at=TS,
        updated_at=TS,
    )


def _chapter(cid: uuid.UUID, title: str) -> Chapter:
    """构造测试章节实体。"""
    return Chapter(id=cid, project_id=PID, title=title)


def _run(
    source_key: str,
    *,
    status: ExtractionStatus = ExtractionStatus.SUCCESS,
    error: str | None = None,
) -> ExtractionRun:
    """构造测试提取 run 记录（id=0 占位，DB 自增）。"""
    return ExtractionRun(
        id=0,
        project_id=PID,
        type=ExtractionType.CHARACTER,
        source_key=source_key,
        content_hash=f"hash-{source_key}",
        status=status,
        error=error,
        run_at=TS,
    )


def _view(events: list[TimelineEvent]) -> TimelineView:
    """构造双线视图 Mock 返回值（narrative_order 为审计事件数据源）。"""
    return TimelineView(
        project_id=PID, total=len(events), event_timeline=events, narrative_order=events
    )


def _ref(eid: uuid.UUID, title: str) -> TimelineEventRef:
    """构造一致性检查冲突对中的事件引用快照。"""
    return TimelineEventRef(
        id=eid,
        title=title,
        time_value=5.0,
        time_display="",
        narrative_position=1,
        timeline_flag="",
    )


def _conflict(
    conflict_type: str,
    prev_id: uuid.UUID,
    prev_title: str,
    next_id: uuid.UUID,
    next_title: str,
) -> TimelineConflict:
    """构造单条时间线冲突/倒叙记录。"""
    return TimelineConflict(
        conflict_type=conflict_type,
        prev=_ref(prev_id, prev_title),
        next=_ref(next_id, next_title),
        message=f"{prev_title} → {next_title}",
    )


def _empty_report() -> ConsistencyReport:
    """构造全一致的时间线检查报告。"""
    return ConsistencyReport(
        project_id=PID,
        checked=0,
        skipped=0,
        consistent=True,
        conflicts=[],
        flashbacks=[],
        event_timeline=[],
        narrative_order=[],
    )


# ── 依赖装配 ──────────────────────────────────────────────────────


def _paged(items: list, page_size: int = 100):
    """构造分页 list Mock side_effect：按 offset 切片返回 (页, 总数)。"""

    async def _list(*args, **kwargs):
        offset = kwargs.get("offset", 0)
        return items[offset : offset + page_size], len(items)

    return _list


class _Deps:
    """测试用依赖集合 — 全部 Mock，可逐项覆盖后调用 service() 装配 AuditService。"""

    def __init__(
        self,
        project: Project | None = None,
        *,
        events: list[TimelineEvent] | None = None,
        report: ConsistencyReport | None = None,
    ) -> None:
        self.project_repo = MagicMock()
        self.project_repo.get = AsyncMock(return_value=project)
        self.character_repo = MagicMock()
        self.character_repo.list = AsyncMock(return_value=([], 0))
        self.character_repo.list_relations = AsyncMock(return_value=[])
        self.character_repo.list_groups = AsyncMock(return_value=[])
        self.world_repo = MagicMock()
        self.world_repo.list = AsyncMock(return_value=([], 0))
        self.timeline_service = MagicMock()
        self.timeline_service.get_timeline_view = AsyncMock(return_value=_view(events or []))
        self.timeline_service.check_consistency = AsyncMock(
            return_value=report if report is not None else _empty_report()
        )
        self.foreshadowing_repo = MagicMock()
        self.foreshadowing_repo.list = AsyncMock(return_value=([], 0))
        self.chapter_repo = MagicMock()
        self.chapter_repo.list_chapters = AsyncMock(return_value=([], 0))
        self.run_repo = MagicMock()
        self.run_repo.list = AsyncMock(return_value=([], 0))
        self.audit_repo = MagicMock()

    def service(self) -> AuditService:
        """按 spec §8.1 构造签名装配审计服务（全部注入 Mock）。"""
        return AuditService(
            project_repo=self.project_repo,
            character_repo=self.character_repo,
            world_repo=self.world_repo,
            timeline_service=self.timeline_service,
            foreshadowing_repo=self.foreshadowing_repo,
            chapter_repo=self.chapter_repo,
            run_repo=self.run_repo,
            audit_repo=self.audit_repo,
        )


def _findings_by_rule(report, rule_id: str):
    """按 rule_id 过滤报告中的 findings。"""
    return [f for f in report.findings if f.rule_id == rule_id]


# ── R-C1 关系引用完整性 ───────────────────────────────────────────


async def test_rf1_event_id_active_no_finding():
    deps = _Deps(_project(), events=[_event(EV_1, "林晚入宫")])
    deps.foreshadowing_repo.list = AsyncMock(
        return_value=([_foreshadowing(uuid.uuid4(), "铜镜的秘密", event_id=EV_1)], 1)
    )

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "foreshadowing.event_anchor") == []


async def test_rf1_event_id_dangling_error():
    deps = _Deps(_project(), events=[_event(EV_1, "林晚入宫")])
    foreshadowing = _foreshadowing(uuid.uuid4(), "铜镜的秘密", event_id=EV_DELETED)
    deps.foreshadowing_repo.list = AsyncMock(return_value=([foreshadowing], 1))

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "foreshadowing.event_anchor")
    assert len(findings) == 1
    f = findings[0]
    assert f.id == f"foreshadowing.event_anchor:{foreshadowing.id}"
    assert f.dimension == AuditDimension.FORESHADOWING
    assert f.severity == AuditSeverity.ERROR
    assert f.entity_type == "foreshadowing"
    assert f.entity_id == foreshadowing.id
    assert f.entity_name == "铜镜的秘密"
    assert f.ref_type == "event"
    assert f.ref_id == EV_DELETED
    assert "不存在" in f.message


async def test_rf1_event_id_missing_error():
    deps = _Deps(_project(), events=[_event(EV_1, "林晚入宫")])
    foreshadowing = _foreshadowing(uuid.uuid4(), "身世之谜", event_id=EV_MISSING)
    deps.foreshadowing_repo.list = AsyncMock(return_value=([foreshadowing], 1))

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "foreshadowing.event_anchor")
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == AuditSeverity.ERROR
    assert f.ref_type == "event"
    assert f.ref_id == EV_MISSING
    assert "不存在" in f.message


async def test_rf1_event_id_none_skipped():
    deps = _Deps(_project(), events=[_event(EV_1, "林晚入宫")])
    deps.foreshadowing_repo.list = AsyncMock(
        return_value=([_foreshadowing(uuid.uuid4(), "铜镜的秘密", event_id=None)], 1)
    )

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "foreshadowing.event_anchor") == []


# ── R-F2 状态机一致性 ─────────────────────────────────────────────


async def test_rf2_resolved_without_resolved_at_error():
    deps = _Deps(_project())
    foreshadowing = _foreshadowing(
        uuid.uuid4(), "身世之谜", status=ForeshadowingStatus.RESOLVED, resolved_at=None
    )
    deps.foreshadowing_repo.list = AsyncMock(return_value=([foreshadowing], 1))

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "foreshadowing.status_time")
    assert len(findings) == 1
    f = findings[0]
    assert f.id == f"foreshadowing.status_time:{foreshadowing.id}"
    assert f.dimension == AuditDimension.FORESHADOWING
    assert f.severity == AuditSeverity.ERROR
    assert f.entity_type == "foreshadowing"
    assert f.entity_id == foreshadowing.id
    assert f.entity_name == "身世之谜"
    assert "resolved_at" in f.message


async def test_rf2_open_with_resolved_at_error():
    deps = _Deps(_project())
    foreshadowing = _foreshadowing(
        uuid.uuid4(), "铜镜的秘密", status=ForeshadowingStatus.OPEN, resolved_at=TS
    )
    deps.foreshadowing_repo.list = AsyncMock(return_value=([foreshadowing], 1))

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "foreshadowing.status_time")
    assert len(findings) == 1
    assert findings[0].severity == AuditSeverity.ERROR
    assert "resolved_at" in findings[0].message


async def test_rf2_resolved_with_resolved_at_no_finding():
    deps = _Deps(_project())
    deps.foreshadowing_repo.list = AsyncMock(
        return_value=(
            [
                _foreshadowing(
                    uuid.uuid4(),
                    "身世之谜",
                    status=ForeshadowingStatus.RESOLVED,
                    resolved_at=TS,
                )
            ],
            1,
        )
    )

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "foreshadowing.status_time") == []


async def test_rf2_open_without_resolved_at_no_finding():
    deps = _Deps(_project())
    deps.foreshadowing_repo.list = AsyncMock(
        return_value=([_foreshadowing(uuid.uuid4(), "铜镜的秘密")], 1)
    )

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "foreshadowing.status_time") == []


# ── R-X1 事件来源章节 ─────────────────────────────────────────────


async def test_rx1_source_chapter_active_no_finding():
    deps = _Deps(_project(), events=[_event(EV_1, "林晚入宫", source_chapter_id=CH_1)])
    deps.chapter_repo.list_chapters = AsyncMock(return_value=([_chapter(CH_1, "第一章")], 1))

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "timeline.source_chapter") == []


async def test_rx1_source_chapter_missing_error():
    deps = _Deps(_project(), events=[_event(EV_1, "林晚入宫", source_chapter_id=CH_2)])
    deps.chapter_repo.list_chapters = AsyncMock(return_value=([_chapter(CH_1, "第一章")], 1))

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "timeline.source_chapter")
    assert len(findings) == 1
    f = findings[0]
    assert f.id == f"timeline.source_chapter:{EV_1}"
    assert f.dimension == AuditDimension.CROSS
    assert f.severity == AuditSeverity.ERROR
    assert f.entity_type == "event"
    assert f.entity_id == EV_1
    assert f.entity_name == "林晚入宫"
    assert f.ref_type == "chapter"
    assert f.ref_id == CH_2
    assert "不存在" in f.message


async def test_rx1_source_chapter_none_skipped():
    """手工事件（source_chapter_id=None）不参与检查。"""
    deps = _Deps(_project(), events=[_event(EV_1, "林晚入宫", source_chapter_id=None)])
    deps.chapter_repo.list_chapters = AsyncMock(return_value=([_chapter(CH_1, "第一章")], 1))

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "timeline.source_chapter") == []


# ── R-X2 提取 run 缺口 ────────────────────────────────────────────


async def test_rx2_error_run_warning():
    deps = _Deps(_project())
    run = _run(str(CH_1), status=ExtractionStatus.ERROR, error="LLM 调用超时")
    deps.run_repo.list = AsyncMock(return_value=([run], 1))
    deps.chapter_repo.list_chapters = AsyncMock(return_value=([_chapter(CH_1, "第一章")], 1))

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "extraction.run_gap")
    assert len(findings) == 1
    f = findings[0]
    assert f.id == f"extraction.run_gap:{run.source_key}"
    assert f.dimension == AuditDimension.CROSS
    assert f.severity == AuditSeverity.WARNING
    assert f.entity_type == "run"
    assert f.entity_id is None
    assert f.data["error"] == "LLM 调用超时"
    assert "提取失败" in f.message


async def test_rx2_chapter_with_run_no_info():
    deps = _Deps(_project())
    deps.run_repo.list = AsyncMock(return_value=([_run(str(CH_1))], 1))
    deps.chapter_repo.list_chapters = AsyncMock(return_value=([_chapter(CH_1, "第一章")], 1))

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "extraction.run_gap") == []


async def test_rx2_chapter_without_run_info():
    deps = _Deps(_project())
    deps.run_repo.list = AsyncMock(return_value=([_run(str(CH_1))], 1))
    deps.chapter_repo.list_chapters = AsyncMock(
        return_value=([_chapter(CH_1, "第一章"), _chapter(CH_2, "第二章")], 2)
    )

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "extraction.run_gap")
    assert len(findings) == 1
    f = findings[0]
    assert f.id == f"extraction.run_gap:{CH_2!s}"
    assert f.severity == AuditSeverity.INFO
    assert f.entity_type == "chapter"
    assert f.entity_id == CH_2
    assert f.entity_name == "第二章"
    assert "从未" in f.message


async def test_rx2_manual_run_not_chapter_coverage():
    """source_key='manual' 的 run 不参与章节比对——章节仍报「从未提取」info。"""
    deps = _Deps(_project())
    deps.run_repo.list = AsyncMock(return_value=([_run("manual")], 1))
    deps.chapter_repo.list_chapters = AsyncMock(return_value=([_chapter(CH_1, "第一章")], 1))

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "extraction.run_gap")
    assert len(findings) == 1
    assert findings[0].severity == AuditSeverity.INFO
    assert findings[0].entity_id == CH_1


async def test_rx2_no_runs_all_chapters_info():
    deps = _Deps(_project())
    deps.run_repo.list = AsyncMock(return_value=([], 0))
    deps.chapter_repo.list_chapters = AsyncMock(
        return_value=([_chapter(CH_1, "第一章"), _chapter(CH_2, "第二章")], 2)
    )

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "extraction.run_gap")
    assert len(findings) == 2
    assert {f.entity_id for f in findings} == {CH_1, CH_2}
    assert all(f.severity == AuditSeverity.INFO for f in findings)


async def test_rx2_no_chapters_no_finding():
    deps = _Deps(_project())
    deps.run_repo.list = AsyncMock(return_value=([_run("manual")], 1))
    deps.chapter_repo.list_chapters = AsyncMock(return_value=([], 0))

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "extraction.run_gap") == []


# ── 服务编排 ──────────────────────────────────────────────────────


async def test_project_not_found_raises():
    """project_repo.get → None → ProjectNotFoundError（404 语义，spec §5.1 步骤 ①）。"""
    deps = _Deps(None)

    with pytest.raises(ProjectNotFoundError):
        await deps.service().run_audit(PID)


async def test_pagination_loops_until_page_exhausted():
    """角色 250 条（100/页）→ 循环拉 3 页取全 250；counts.characters=250。"""
    deps = _Deps(_project())
    chars = [_char(uuid.uuid4(), f"角色{i}") for i in range(250)]
    deps.character_repo.list = AsyncMock(side_effect=_paged(chars))

    report = await deps.service().run_audit(PID)

    assert report.summary.counts["characters"] == 250
    assert deps.character_repo.list.await_count == 3


async def test_pagination_empty_page_terminates():
    """list 返回空页 → 循环立即终止（防死循环）。"""
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(return_value=([], 0))

    report = await deps.service().run_audit(PID)

    assert report.summary.counts["characters"] == 0
    assert deps.character_repo.list.await_count == 1


async def test_counts_all_keys():
    """counts 8 键全部正确（与规则扫描共享同一次全量读取）。"""
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(return_value=([_char(C_A, "林晚"), _char(C_B, "沈砚")], 2))
    deps.character_repo.list_relations = AsyncMock(return_value=[_rel(uuid.uuid4(), C_A, C_B)])
    deps.character_repo.list_groups = AsyncMock(return_value=[_group(G_ACTIVE)])
    deps.world_repo.list = AsyncMock(
        return_value=(
            [
                _setting(uuid.uuid4(), "青云城", content="都城"),
                _setting(uuid.uuid4(), "北境", content="苦寒之地"),
            ],
            2,
        )
    )
    deps.timeline_service.get_timeline_view = AsyncMock(
        return_value=_view(
            [
                _event(EV_1, "林晚入宫"),
                _event(EV_2, "外门往事"),
                _event(EV_3, "青云城之变"),
            ]
        )
    )
    deps.foreshadowing_repo.list = AsyncMock(
        return_value=([_foreshadowing(uuid.uuid4(), "铜镜的秘密")], 1)
    )
    deps.chapter_repo.list_chapters = AsyncMock(
        return_value=([_chapter(CH_1, "第一章"), _chapter(CH_2, "第二章")], 2)
    )
    deps.run_repo.list = AsyncMock(return_value=([_run("manual"), _run(str(CH_1))], 2))

    report = await deps.service().run_audit(PID)

    assert report.summary.counts == {
        "characters": 2,
        "relations": 1,
        "groups": 1,
        "world_settings": 2,
        "events": 3,
        "foreshadowings": 1,
        "chapters": 2,
        "extraction_runs": 2,
    }
    deps.timeline_service.get_timeline_view.assert_awaited_once_with(PID)


async def test_consistent_true_with_warning_info_only():
    """仅 warning/info findings → consistent=True（spec §6.2: consistent 仅由 error 决定）。"""
    deps = _Deps(_project(), events=[_event(EV_1, "林晚入宫")])
    deps.character_repo.list = AsyncMock(return_value=([_char(C_A, "沈砚", group_id=None)], 1))
    deps.world_repo.list = AsyncMock(return_value=([_setting(uuid.uuid4(), "青云城")], 1))
    deps.chapter_repo.list_chapters = AsyncMock(
        return_value=([_chapter(CH_1, "第一章"), _chapter(CH_2, "第二章")], 2)
    )
    deps.run_repo.list = AsyncMock(
        return_value=([_run(str(CH_1), status=ExtractionStatus.ERROR, error="LLM 调用超时")], 1)
    )

    report = await deps.service().run_audit(PID)

    assert report.summary.consistent is True
    assert report.summary.total == 3
    assert all(f.severity != AuditSeverity.ERROR for f in report.findings)
    assert report.summary.by_dimension[AuditDimension.CROSS].warning == 1
    assert report.summary.by_dimension[AuditDimension.WORLD].info == 1
    assert report.summary.by_dimension[AuditDimension.CROSS].info == 1
    assert report.summary.by_dimension[AuditDimension.TIMELINE].error == 0
    assert report.summary.by_dimension[AuditDimension.FORESHADOWING].error == 0


async def test_consistent_false_with_error():
    """任一 error finding → consistent=False（混合数据集，见排序测试同款）。"""
    deps = _Deps(_project(), events=[_event(EV_1, "林晚入宫")])
    deps.character_repo.list = AsyncMock(return_value=([_char(C_A, "林晚", group_id=G_MISSING)], 1))

    report = await deps.service().run_audit(PID)

    assert report.summary.consistent is False
    assert report.summary.total == 1
    assert report.summary.by_dimension[AuditDimension.CHARACTER].error == 1


async def test_findings_sorted_stable_order():
    (
        "findings 按 (dimension 序, severity error→warning→info, "
        "entity_name) 稳定排序（spec §6.3）。"
    )
    deps = _Deps(_project(), events=[_event(EV_1, "林晚入宫")])
    c_shen = _char(C_A, "沈砚", group_id=G_MISSING)  # R-C2 error（悬空分组）
    c_lin = _char(C_B, "林晚", group_id=G_DELETED)  # R-C2 error（悬空分组，真删无 warning 档）
    deps.character_repo.list = AsyncMock(return_value=([c_shen, c_lin], 2))
    deps.character_repo.list_groups = AsyncMock(return_value=[])
    setting = _setting(uuid.uuid4(), "青云城")
    deps.world_repo.list = AsyncMock(return_value=([setting], 1))
    foreshadowing = _foreshadowing(uuid.uuid4(), "铜镜的秘密", event_id=EV_DELETED)
    deps.foreshadowing_repo.list = AsyncMock(return_value=([foreshadowing], 1))
    deps.chapter_repo.list_chapters = AsyncMock(return_value=([_chapter(CH_1, "第一章")], 1))
    deps.run_repo.list = AsyncMock(return_value=([], 0))
    deps.timeline_service.check_consistency = AsyncMock(
        return_value=ConsistencyReport(
            project_id=PID,
            checked=2,
            skipped=0,
            consistent=False,
            conflicts=[_conflict("order_conflict", EV_1, "林晚入宫", EV_2, "外门往事")],
            flashbacks=[],
            event_timeline=[],
            narrative_order=[],
        )
    )

    report = await deps.service().run_audit(PID)

    assert [f.id for f in report.findings] == [
        f"character.group_ref:{c_shen.id}",  # character · error（同维度 error 按 id 稳定序）
        f"character.group_ref:{c_lin.id}",  # character · error
        f"timeline.dual_consistency:{EV_1}:{EV_2}",  # timeline · error
        f"world.entry_content:{setting.id}",  # world · info
        f"foreshadowing.event_anchor:{foreshadowing.id}",  # foreshadowing · error
        f"extraction.run_gap:{CH_1!s}",  # cross · info（跨维度排最后）
    ]
    assert report.summary.total == 6
    assert report.summary.by_dimension[AuditDimension.CHARACTER].error == 2
    assert report.summary.by_dimension[AuditDimension.CHARACTER].warning == 0
    assert report.summary.by_dimension[AuditDimension.TIMELINE].error == 1
    assert report.summary.by_dimension[AuditDimension.WORLD].info == 1
    assert report.summary.by_dimension[AuditDimension.FORESHADOWING].error == 1
    assert report.summary.by_dimension[AuditDimension.CROSS].info == 1


async def test_deterministic_snapshot():
    """同一 Mock 数据集两次 run_audit → summary/findings/timeline_check 逐字段相等（spec §6.4）。"""
    deps = _Deps(_project(), events=[_event(EV_1, "林晚入宫")])
    deps.character_repo.list = AsyncMock(return_value=([_char(C_A, "林晚", group_id=G_MISSING)], 1))
    deps.world_repo.list = AsyncMock(return_value=([_setting(uuid.uuid4(), "青云城")], 1))
    deps.chapter_repo.list_chapters = AsyncMock(return_value=([_chapter(CH_1, "第一章")], 1))
    deps.run_repo.list = AsyncMock(return_value=([], 0))

    service = deps.service()
    first = await service.run_audit(PID)
    second = await service.run_audit(PID)

    assert first.summary == second.summary
    assert first.findings == second.findings
    assert first.timeline_check == second.timeline_check
    assert first.project_id == second.project_id
    assert len({f.id for f in first.findings}) == len(first.findings)  # finding.id 去重锚点


async def test_repo_failure_propagates():
    """任一档案仓储读取失败 → run_audit 抛异常（不产出部分报告，spec §5.1 要点 6）。"""
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(side_effect=RuntimeError("db down"))

    with pytest.raises(RuntimeError, match="db down"):
        await deps.service().run_audit(PID)
