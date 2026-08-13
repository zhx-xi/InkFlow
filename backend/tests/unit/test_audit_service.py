"""R-C1/R-C2/R-T1/R-W1/R-W2 规则 — Mock 各仓储 + TimelineService + AuditRepositoryProtocol。

覆盖: R-C1/R-C2 引用完整性 / R-T1 时间线委托 / R-W1/W2 内容与档案健康。

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


async def test_rc1_both_ends_active_no_finding():
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(return_value=([_char(C_A, "林晚"), _char(C_B, "沈砚")], 2))
    deps.character_repo.list_relations = AsyncMock(return_value=[_rel(uuid.uuid4(), C_A, C_B)])

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "character.relation_ref") == []
    assert report.summary.counts["relations"] == 1


async def test_rc1_to_end_dangling_error():
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(return_value=([_char(C_A, "林晚")], 1))
    rel = _rel(uuid.uuid4(), C_A, C_DELETED)
    deps.character_repo.list_relations = AsyncMock(return_value=[rel])

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "character.relation_ref")
    assert len(findings) == 1
    f = findings[0]
    assert f.id == f"character.relation_ref:{rel.id}"
    assert f.dimension == AuditDimension.CHARACTER
    assert f.severity == AuditSeverity.ERROR
    assert f.entity_type == "relation"
    assert f.entity_id == rel.id
    assert f.entity_name
    assert f.ref_type == "character"
    assert f.ref_id == C_DELETED
    assert "不存在" in f.message


async def test_rc1_from_end_dangling_error():
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(return_value=([_char(C_B, "沈砚")], 1))
    rel = _rel(uuid.uuid4(), C_DELETED, C_B)
    deps.character_repo.list_relations = AsyncMock(return_value=[rel])

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "character.relation_ref")
    assert len(findings) == 1
    f = findings[0]
    assert f.id == f"character.relation_ref:{rel.id}"
    assert f.dimension == AuditDimension.CHARACTER
    assert f.severity == AuditSeverity.ERROR
    assert f.entity_type == "relation"
    assert f.entity_id == rel.id
    assert f.entity_name
    assert f.ref_type == "character"
    assert f.ref_id == C_DELETED
    assert "不存在" in f.message


async def test_rc1_to_end_missing_error():
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(return_value=([_char(C_A, "林晚")], 1))
    rel = _rel(uuid.uuid4(), C_A, C_MISSING)
    deps.character_repo.list_relations = AsyncMock(return_value=[rel])

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "character.relation_ref")
    assert len(findings) == 1
    f = findings[0]
    assert f.id == f"character.relation_ref:{rel.id}"
    assert f.severity == AuditSeverity.ERROR
    assert f.ref_type == "character"
    assert f.ref_id == C_MISSING
    assert "不存在" in f.message


async def test_rc1_from_end_missing_error():
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(return_value=([_char(C_B, "沈砚")], 1))
    rel = _rel(uuid.uuid4(), C_MISSING, C_B)
    deps.character_repo.list_relations = AsyncMock(return_value=[rel])

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "character.relation_ref")
    assert len(findings) == 1
    assert findings[0].severity == AuditSeverity.ERROR
    assert findings[0].ref_id == C_MISSING


async def test_rc1_empty_relations_no_finding():
    (
        "空关系列表 → 无 finding；#211 删除为真删，仓储层不返回已删关系，"
        "审计只扫描返回的活动关系。"
    )
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(return_value=([_char(C_A, "林晚")], 1))
    deps.character_repo.list_relations = AsyncMock(return_value=[])

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "character.relation_ref") == []


# ── R-C2 分组引用完整性 ───────────────────────────────────────────


async def test_rc2_group_id_active_no_finding():
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(return_value=([_char(C_A, "林晚", group_id=G_ACTIVE)], 1))
    deps.character_repo.list_groups = AsyncMock(return_value=[_group(G_ACTIVE)])

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "character.group_ref") == []


async def test_rc2_group_id_dangling_error():
    deps = _Deps(_project())
    char = _char(C_A, "沈砚", group_id=G_DELETED)
    deps.character_repo.list = AsyncMock(return_value=([char], 1))
    deps.character_repo.list_groups = AsyncMock(return_value=[])

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "character.group_ref")
    assert len(findings) == 1
    f = findings[0]
    assert f.id == f"character.group_ref:{char.id}"
    assert f.dimension == AuditDimension.CHARACTER
    assert f.severity == AuditSeverity.ERROR
    assert f.entity_type == "character"
    assert f.entity_id == char.id
    assert f.entity_name == "沈砚"
    assert f.ref_type == "group"
    assert f.ref_id == G_DELETED
    assert "不存在" in f.message


async def test_rc2_group_id_missing_error():
    deps = _Deps(_project())
    char = _char(C_A, "林晚", group_id=G_MISSING)
    deps.character_repo.list = AsyncMock(return_value=([char], 1))
    deps.character_repo.list_groups = AsyncMock(return_value=[])

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "character.group_ref")
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == AuditSeverity.ERROR
    assert f.ref_type == "group"
    assert f.ref_id == G_MISSING
    assert "不存在" in f.message


async def test_rc2_group_id_none_skipped():
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(return_value=([_char(C_A, "林晚", group_id=None)], 1))
    deps.character_repo.list_groups = AsyncMock(return_value=[])

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "character.group_ref") == []


async def test_rc2_empty_characters_no_finding():
    deps = _Deps(_project())
    deps.character_repo.list = AsyncMock(return_value=([], 0))
    deps.character_repo.list_groups = AsyncMock(return_value=[])

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "character.group_ref") == []


# ── R-T1 时间线委托 ───────────────────────────────────────────────


async def test_rt1_conflicts_and_flashbacks_converted():
    """2 条 order_conflict → 2 error；1 条 flashback → 1 info；转换字段完整。"""
    report = ConsistencyReport(
        project_id=PID,
        checked=3,
        skipped=0,
        consistent=False,
        conflicts=[
            _conflict("order_conflict", EV_1, "林晚入宫", EV_2, "外门往事"),
            _conflict("order_conflict", EV_3, "事件三", EV_4, "事件四"),
        ],
        flashbacks=[_conflict("flashback", EV_2, "往事", EV_1, "前尘")],
        event_timeline=[],
        narrative_order=[],
    )
    deps = _Deps(_project(), report=report)

    audit_report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(audit_report, "timeline.dual_consistency")
    assert len(findings) == 3
    errors = [f for f in findings if f.severity == AuditSeverity.ERROR]
    infos = [f for f in findings if f.severity == AuditSeverity.INFO]
    assert len(errors) == 2
    assert len(infos) == 1

    f = errors[0]
    assert f.id == f"timeline.dual_consistency:{EV_1}:{EV_2}"
    assert f.dimension == AuditDimension.TIMELINE
    assert f.entity_type == "event"
    assert f.entity_id == EV_1
    assert f.entity_name == "林晚入宫"
    assert f.ref_type == "event"
    assert f.ref_id == EV_2
    assert f.data["conflict_type"] == "order_conflict"
    prev_snapshot = f.data["prev"]
    prev_id = prev_snapshot["id"] if isinstance(prev_snapshot, dict) else prev_snapshot.id
    next_snapshot = f.data["next"]
    next_id = next_snapshot["id"] if isinstance(next_snapshot, dict) else next_snapshot.id
    assert prev_id == EV_1
    assert next_id == EV_2

    assert infos[0].severity == AuditSeverity.INFO
    assert infos[0].data["conflict_type"] == "flashback"
    assert infos[0].id == f"timeline.dual_consistency:{EV_2}:{EV_1}"


async def test_rt1_consistent_report_no_finding():
    deps = _Deps(_project(), report=_empty_report())

    audit_report = await deps.service().run_audit(PID)

    assert _findings_by_rule(audit_report, "timeline.dual_consistency") == []
    assert audit_report.timeline_check is not None
    assert audit_report.timeline_check.consistent is True


async def test_rt1_checked_zero_skipped_n_no_finding():
    """全部事件时间未知 → checked=0、skipped=n，无 finding（观测透传嵌套报告）。"""
    report = ConsistencyReport(
        project_id=PID,
        checked=0,
        skipped=3,
        consistent=True,
        conflicts=[],
        flashbacks=[],
        event_timeline=[],
        narrative_order=[],
    )
    deps = _Deps(_project(), report=report)

    audit_report = await deps.service().run_audit(PID)

    assert _findings_by_rule(audit_report, "timeline.dual_consistency") == []
    assert audit_report.timeline_check.skipped == 3


async def test_rt1_delegation_args_and_nested_passthrough():
    (
        "委托调用断言：check_consistency 收到 project_id 且 "
        "include_flashbacks 生效（True/默认 True）；嵌套报告原样透传。"
    )
    deps = _Deps(_project())

    audit_report = await deps.service().run_audit(PID)

    deps.timeline_service.check_consistency.assert_awaited_once()
    call_args, call_kwargs = deps.timeline_service.check_consistency.await_args
    assert call_args[0] == PID
    assert call_kwargs.get("include_flashbacks", True) is True
    deps.timeline_service.get_timeline_view.assert_awaited_once_with(PID)
    assert audit_report.timeline_check == _empty_report()


async def test_rt1_delegation_failure_propagates():
    """委托 F12 check_consistency 抛异常 → run_audit 透传（不产出部分报告）。"""
    deps = _Deps(_project())
    deps.timeline_service.check_consistency = AsyncMock(side_effect=RuntimeError("委托失败"))

    with pytest.raises(RuntimeError, match="委托失败"):
        await deps.service().run_audit(PID)


# ── R-W1 条目内容健康度 ───────────────────────────────────────────


async def test_rw1_empty_content_info():
    deps = _Deps(_project())
    setting = _setting(uuid.uuid4(), "青云城", content="")
    deps.world_repo.list = AsyncMock(return_value=([setting], 1))

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "world.entry_content")
    assert len(findings) == 1
    f = findings[0]
    assert f.id == f"world.entry_content:{setting.id}"
    assert f.dimension == AuditDimension.WORLD
    assert f.severity == AuditSeverity.INFO
    assert f.entity_type == "world_setting"
    assert f.entity_id == setting.id
    assert f.entity_name == "青云城"
    assert "缺少内容" in f.message


async def test_rw1_whitespace_content_info():
    deps = _Deps(_project())
    deps.world_repo.list = AsyncMock(
        return_value=([_setting(uuid.uuid4(), "青云城", content="   ")], 1)
    )

    report = await deps.service().run_audit(PID)

    assert len(_findings_by_rule(report, "world.entry_content")) == 1


async def test_rw1_non_empty_content_no_finding():
    deps = _Deps(_project())
    deps.world_repo.list = AsyncMock(
        return_value=([_setting(uuid.uuid4(), "青云城", content="雄踞北境的千年都城")], 1)
    )

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "world.entry_content") == []


# ── R-W2 档案缺口 ─────────────────────────────────────────────────


async def test_rw2_chapters_without_world_archive_gap_info():
    deps = _Deps(_project())
    deps.chapter_repo.list_chapters = AsyncMock(
        return_value=([_chapter(CH_1, "第一章"), _chapter(CH_2, "第二章")], 2)
    )
    deps.world_repo.list = AsyncMock(return_value=([], 0))

    report = await deps.service().run_audit(PID)

    findings = _findings_by_rule(report, "world.archive_gap")
    assert len(findings) == 1
    f = findings[0]
    assert f.id == f"world.archive_gap:{PID}"
    assert f.dimension == AuditDimension.WORLD
    assert f.severity == AuditSeverity.INFO
    assert f.entity_type == "project"
    assert f.entity_id == PID
    assert "尚未建立世界观档案" in f.message


async def test_rw2_no_chapters_no_finding():
    deps = _Deps(_project())
    deps.chapter_repo.list_chapters = AsyncMock(return_value=([], 0))
    deps.world_repo.list = AsyncMock(return_value=([], 0))

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "world.archive_gap") == []


async def test_rw2_has_world_settings_no_finding():
    deps = _Deps(_project())
    deps.chapter_repo.list_chapters = AsyncMock(return_value=([_chapter(CH_1, "第一章")], 1))
    deps.world_repo.list = AsyncMock(
        return_value=([_setting(uuid.uuid4(), "青云城", content="都城")], 1)
    )

    report = await deps.service().run_audit(PID)

    assert _findings_by_rule(report, "world.archive_gap") == []


# ── R-F1 事件锚点 ─────────────────────────────────────────────────
