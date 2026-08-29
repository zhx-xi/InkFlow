"""F15 一致性审计服务报告模型单元测试 — 无 I/O，纯 Pydantic 验证.

测试范围：AuditDimension / AuditSeverity 枚举、AuditFinding（字段类型、
可空边界、稳定 id 格式）、DimensionSummary / AuditSummary（计数与
consistent 语义）、AuditReport（JSON 序列化 + ConsistencyReport 嵌套）。

依据: specs/f15-consistency-audit/spec.md §2 数据模型（§2.1-§2.5）+
specs/f12-timeline/spec.md §2.4（ConsistencyReport 引用不重定义）。
"""

import uuid
from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from inkflow.domain.models.audit import (
    AuditDimension,
    AuditFinding,
    AuditReport,
    AuditSeverity,
    AuditSummary,
    DimensionSummary,
)
from inkflow.domain.models.timeline import ConsistencyReport

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
EID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001")
EID2 = uuid.UUID("4a5b6c7d-0000-4000-8000-000000000001")
RID = uuid.UUID("11111111-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
RULE_ID = "character.relation_ref"


def make_finding(**overrides: Any) -> AuditFinding:
    """构造一条最小合法审计发现，可覆盖任意字段（spec §2.2 示例形态）."""
    base = {
        "id": f"{RULE_ID}:{EID}",
        "rule_id": RULE_ID,
        "dimension": AuditDimension.CHARACTER,
        "severity": AuditSeverity.ERROR,
        "message": "关系 林晚→?? 的 to 端指向不存在的角色（悬空引用，请删除该关系或修正引用）",
        "entity_type": "relation",
        "entity_id": EID,
        "entity_name": "林晚→??",
        "ref_type": "character",
        "ref_id": RID,
        "data": {},
    }
    base.update(overrides)
    return AuditFinding(**base)


def make_summary(**overrides: Any) -> AuditSummary:
    """构造一条最小合法审计汇总（默认全零、一致）."""
    base = {"consistent": True, "total": 0}
    base.update(overrides)
    return AuditSummary(**base)


def make_consistency_report() -> ConsistencyReport:
    """构造 F12 ConsistencyReport（时间线维度嵌套原始报告，§2.4）."""
    return ConsistencyReport(
        project_id=PID,
        checked=6,
        skipped=0,
        consistent=False,
    )


def make_report(**overrides: Any) -> AuditReport:
    """构造一份最小合法审计报告（默认空 findings、无时间线嵌套）."""
    base = {
        "project_id": PID,
        "generated_at": TS,
        "summary": make_summary(),
    }
    base.update(overrides)
    return AuditReport(**base)


class TestAuditDimensionEnum:
    """AuditDimension 枚举（§2.1：4 档案维度 + 跨维度联动）."""

    def test_dimension_has_exactly_five_members(self):
        """枚举成员数恰为 5（character/timeline/world/foreshadowing/cross）."""
        assert len(AuditDimension) == 5

    @pytest.mark.parametrize(
        ("member", "expected"),
        [
            ("CHARACTER", "character"),
            ("TIMELINE", "timeline"),
            ("WORLD", "world"),
            ("FORESHADOWING", "foreshadowing"),
            ("CROSS", "cross"),
        ],
    )
    def test_dimension_members_and_values(self, member, expected):
        """各成员的值与 spec §2.1 定义一致."""
        assert getattr(AuditDimension, member).value == expected

    def test_dimension_is_str_enum(self):
        """AuditDimension 是 StrEnum：成员值即字符串，可直接作 JSON 值."""
        assert isinstance(AuditDimension.CHARACTER.value, str)
        assert AuditDimension("character") is AuditDimension.CHARACTER

    def test_dimension_invalid_value_raises(self):
        """未知维度值应抛出 ValueError."""
        with pytest.raises(ValueError):
            AuditDimension("other")


class TestAuditSeverityEnum:
    """AuditSeverity 枚举（§2.1：error/warning/info 三级）."""

    def test_severity_has_exactly_three_members(self):
        """枚举成员数恰为 3（error/warning/info）."""
        assert len(AuditSeverity) == 3

    @pytest.mark.parametrize(
        ("member", "expected"),
        [
            ("ERROR", "error"),
            ("WARNING", "warning"),
            ("INFO", "info"),
        ],
    )
    def test_severity_members_and_values(self, member, expected):
        """各成员的值与 spec §2.1 定义一致."""
        assert getattr(AuditSeverity, member).value == expected

    def test_severity_invalid_value_raises(self):
        """未知严重级别值应抛出 ValueError."""
        with pytest.raises(ValueError):
            AuditSeverity("fatal")


class TestAuditFindingModel:
    """AuditFinding 单条审计发现（§2.2）."""

    def test_finding_all_fields_roundtrip(self):
        """全部字段构造后原样保留，类型正确（id/rule_id/dimension/severity/
        message/entity_type/entity_id/entity_name/ref_type/ref_id/data）."""
        finding = make_finding(
            id="timeline.dual_consistency:9b1c2d3e-0000-4000-8000-000000000001:4a5b6c7d-0000-4000-8000-000000000001",
            rule_id="timeline.dual_consistency",
            dimension=AuditDimension.TIMELINE,
            severity=AuditSeverity.ERROR,
            message="未声明的倒叙: 叙事顺序中「林晚入宫」(时间 5.0) 之后是「外门往事」(时间 3.0)",
            entity_type="event",
            entity_id=EID,
            entity_name="林晚入宫",
            ref_type="event",
            ref_id=EID2,
            data={"conflict_type": "order_conflict"},
        )
        assert finding.id.startswith("timeline.dual_consistency:")
        assert finding.rule_id == "timeline.dual_consistency"
        assert finding.dimension is AuditDimension.TIMELINE
        assert finding.severity is AuditSeverity.ERROR
        assert finding.message == (
            "未声明的倒叙: 叙事顺序中「林晚入宫」(时间 5.0) " "之后是「外门往事」(时间 3.0)"
        )
        assert finding.entity_type == "event"
        assert finding.entity_id == EID
        assert isinstance(finding.entity_id, uuid.UUID)
        assert finding.entity_name == "林晚入宫"
        assert finding.ref_type == "event"
        assert finding.ref_id == EID2
        assert isinstance(finding.ref_id, uuid.UUID)
        assert finding.data == {"conflict_type": "order_conflict"}

    def test_finding_stable_id_format(self):
        """id 是稳定键 f'{rule_id}:{entity_key}'（§2.2，快照断言/去重锚点）.

        时间线冲突对的 entity_key = '{prev_id}:{next_id}'；run 缺口 = source_key。
        """
        rule_id = "timeline.dual_consistency"
        entity_key = f"{EID}:{EID2}"  # 时间线冲突对 prev:next
        finding = make_finding(id=f"{rule_id}:{entity_key}", rule_id=rule_id)
        assert finding.id == f"{rule_id}:{entity_key}"
        assert finding.id.split(":", 1)[0] == rule_id
        assert finding.id.split(":", 1)[1] == entity_key

    def test_finding_nullable_fields_defaults(self):
        """可空字段默认值：entity_id/ref_type/ref_id 为 None，entity_name=''，data={}."""
        finding = make_finding(
            id=f"{RULE_ID}:{EID}",
            entity_id=None,
            entity_name="",
            ref_type=None,
            ref_id=None,
            data={},
        )
        assert finding.entity_id is None
        assert finding.entity_name == ""
        assert finding.ref_type is None
        assert finding.ref_id is None
        assert finding.data == {}

    def test_finding_explicit_none_allowed(self):
        """缺省构造（不传可空字段）时 entity_id/ref_type/ref_id 均为 None（run 缺口场景）."""
        finding = AuditFinding(
            id="cross.extraction_gap:chapter-key",
            rule_id="cross.extraction_gap",
            dimension=AuditDimension.CROSS,
            severity=AuditSeverity.INFO,
            message="章节尚未执行过提取",
            entity_type="chapter",
            entity_name="第一章 序",
        )
        assert finding.entity_id is None
        assert finding.ref_type is None
        assert finding.ref_id is None
        assert finding.data == {}
        assert finding.entity_name == "第一章 序"

    def test_finding_data_arbitrary_dict(self):
        """data 接受任意嵌套结构（冲突对快照、run 状态等附加上下文）."""
        finding = make_finding(
            data={
                "conflict_type": "order_conflict",
                "prev": {"id": str(EID), "title": "林晚入宫", "time_value": 5.0},
                "next": {"id": str(EID2), "title": "外门往事", "time_value": 3.0},
                "tags": ["flashback", "修正"],
            }
        )
        assert finding.data["conflict_type"] == "order_conflict"
        assert finding.data["prev"]["time_value"] == 5.0
        assert finding.data["tags"] == ["flashback", "修正"]

    def test_finding_required_fields_missing_raises(self):
        """缺少必填字段（id）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            AuditFinding(
                rule_id=RULE_ID,
                dimension=AuditDimension.CHARACTER,
                severity=AuditSeverity.ERROR,
                message="x",
                entity_type="relation",
            )

    @pytest.mark.parametrize("field", ["entity_id", "ref_id"])
    def test_finding_invalid_uuid_raises(self, field):
        """entity_id/ref_id 传非法 UUID 字符串应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            make_finding(**{field: "not-a-uuid"})

    def test_finding_uuid_string_parsed(self):
        """entity_id/ref_id 传 UUID 字符串被解析为 uuid.UUID 对象."""
        finding = make_finding(entity_id=str(EID), ref_id=str(RID))
        assert finding.entity_id == EID
        assert finding.ref_id == RID
        assert isinstance(finding.entity_id, uuid.UUID)
        assert isinstance(finding.ref_id, uuid.UUID)

    def test_finding_enum_strings_coerced(self):
        """dimension/severity 接受字符串值并转为枚举（API/CLI JSON 输入路径）."""
        finding = make_finding(dimension="character", severity="error")
        assert finding.dimension is AuditDimension.CHARACTER
        assert finding.severity is AuditSeverity.ERROR

    def test_finding_invalid_dimension_raises(self):
        """dimension 传未知字符串应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            make_finding(dimension="other")


class TestDimensionSummary:
    """DimensionSummary 单维度发现计数（§2.3）."""

    def test_dimension_summary_zero_defaults(self):
        """缺省构造时 error/warning/info 均为 0."""
        summary = DimensionSummary()
        assert summary.error == 0
        assert summary.warning == 0
        assert summary.info == 0

    def test_dimension_summary_explicit_counts(self):
        """显式传入的计数原样保留."""
        summary = DimensionSummary(error=2, warning=1, info=3)
        assert summary.error == 2
        assert summary.warning == 1
        assert summary.info == 3


class TestAuditSummary:
    """AuditSummary 审计汇总（§2.3：consistent/total/by_dimension/counts）."""

    def test_summary_defaults_empty_dicts(self):
        """by_dimension/counts 缺省为空 dict（零发现报告形态）."""
        summary = make_summary()
        assert summary.consistent is True
        assert summary.total == 0
        assert summary.by_dimension == {}
        assert summary.counts == {}

    def test_summary_requires_consistent_and_total(self):
        """缺少必填字段（consistent/total）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            AuditSummary(total=0)  # 缺 consistent
        with pytest.raises(ValidationError):
            AuditSummary(consistent=True)  # 缺 total

    def test_summary_by_dimension_enum_key(self):
        """by_dimension 以 AuditDimension 为键，值为 DimensionSummary."""
        summary = make_summary(
            by_dimension={
                AuditDimension.CHARACTER: DimensionSummary(error=1, warning=1, info=0),
                AuditDimension.TIMELINE: DimensionSummary(error=1),
            }
        )
        assert summary.by_dimension[AuditDimension.CHARACTER].error == 1
        assert summary.by_dimension[AuditDimension.CHARACTER].warning == 1
        assert summary.by_dimension[AuditDimension.TIMELINE].error == 1
        assert summary.by_dimension[AuditDimension.TIMELINE].info == 0

    def test_summary_by_dimension_str_key_coerced(self):
        """by_dimension 的字符串键/嵌套 dict 值自动转为枚举与 DimensionSummary."""
        summary = make_summary(
            by_dimension={
                "timeline": {"warning": 2, "info": 1},
                "cross": {},
            }
        )
        assert summary.by_dimension[AuditDimension.TIMELINE].warning == 2
        assert summary.by_dimension[AuditDimension.TIMELINE].info == 1
        assert summary.by_dimension[AuditDimension.CROSS] == DimensionSummary()

    def test_summary_counts_all_eight_keys(self):
        """counts 承载 8 项档案规模观测（§2.3 字段表）."""
        counts = {
            "characters": 3,
            "relations": 2,
            "groups": 1,
            "world_settings": 4,
            "events": 6,
            "foreshadowings": 2,
            "chapters": 3,
            "extraction_runs": 5,
        }
        summary = make_summary(counts=counts)
        assert summary.counts == counts
        assert summary.counts["extraction_runs"] == 5

    def test_summary_consistent_true_without_errors(self):
        """无 error 级 findings（仅 warning/info）时 consistent=True（§2.3/§6.2）."""
        summary = make_summary(
            consistent=True,
            total=3,
            by_dimension={AuditDimension.WORLD: DimensionSummary(warning=1, info=2)},
        )
        assert summary.consistent is True
        assert summary.total == 3

    def test_summary_consistent_false_when_errors_present(self):
        """存在 error 级 findings 时 consistent=False（consistent 仅由 error 决定）."""
        summary = make_summary(
            consistent=False,
            total=3,
            by_dimension={
                AuditDimension.CHARACTER: DimensionSummary(error=2, warning=1),
                AuditDimension.TIMELINE: DimensionSummary(error=1),
            },
        )
        assert summary.consistent is False
        assert summary.total == 3


class TestAuditReport:
    """AuditReport 审计报告（§2.3：project_id/generated_at/summary/findings/timeline_check）."""

    def test_report_defaults(self):
        """findings 缺省为空列表，timeline_check 缺省为 None（无事件/委托失败语义）."""
        report = make_report()
        assert report.project_id == PID
        assert report.generated_at == TS
        assert report.summary == make_summary()
        assert report.findings == []
        assert report.timeline_check is None

    def test_report_requires_fields(self):
        """缺少必填字段（project_id/generated_at/summary）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            AuditReport(generated_at=TS, summary=make_summary())  # 缺 project_id
        with pytest.raises(ValidationError):
            AuditReport(project_id=PID, generated_at=TS)  # 缺 summary
        with pytest.raises(ValidationError):
            AuditReport(project_id=PID, summary=make_summary())  # 缺 generated_at

    def test_report_findings_nested(self):
        """findings 列表承载 AuditFinding 实例并原样保留."""
        finding = make_finding()
        report = make_report(findings=[finding])
        assert report.findings == [finding]
        assert isinstance(report.findings[0], AuditFinding)

    def test_report_json_serialization_with_timeline_check(self):
        """model_dump(mode='json')：UUID→str、datetime→ISO8601、枚举→str、
        嵌套 ConsistencyReport 一并序列化（§2.5：直接进 API/CLI 信封）."""
        finding = make_finding()
        report = make_report(
            findings=[finding],
            timeline_check=make_consistency_report(),
        )
        dumped = report.model_dump(mode="json")
        assert dumped["project_id"] == str(PID)
        assert dumped["generated_at"] == "2026-08-01T10:00:00"
        assert dumped["summary"]["consistent"] is True
        assert dumped["summary"]["total"] == 0
        assert dumped["findings"][0]["id"] == finding.id
        assert dumped["findings"][0]["dimension"] == "character"
        assert dumped["findings"][0]["severity"] == "error"
        assert dumped["findings"][0]["entity_id"] == str(EID)
        assert dumped["findings"][0]["ref_id"] == str(RID)
        assert dumped["findings"][0]["data"] == {}
        assert dumped["timeline_check"]["project_id"] == str(PID)
        assert dumped["timeline_check"]["checked"] == 6
        assert dumped["timeline_check"]["skipped"] == 0
        assert dumped["timeline_check"]["consistent"] is False
        assert dumped["timeline_check"]["conflicts"] == []

    def test_report_json_roundtrip(self):
        """model_dump_json → model_validate_json 保真（快照断言基线）."""
        report = make_report(
            findings=[make_finding()],
            timeline_check=make_consistency_report(),
        )
        restored = AuditReport.model_validate_json(report.model_dump_json())
        assert restored == report

    def test_report_timeline_check_none_serialized_null(self):
        """timeline_check=None 时 JSON 序列化为 null（无事件/委托失败语义）."""
        report = make_report(timeline_check=None)
        assert report.timeline_check is None
        dumped = report.model_dump(mode="json")
        assert dumped["timeline_check"] is None

    def test_report_nested_consistency_report_preserved(self):
        """timeline_check 原样嵌套 F12 ConsistencyReport（引用不重定义，§2.4）."""
        cr = make_consistency_report()
        report = make_report(timeline_check=cr)
        assert report.timeline_check == cr
        assert isinstance(report.timeline_check, ConsistencyReport)

    def test_report_invalid_timeline_check_raises(self):
        """timeline_check 传非 ConsistencyReport 值应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            make_report(timeline_check="not-a-report")
