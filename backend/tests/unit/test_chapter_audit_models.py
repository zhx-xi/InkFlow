"""F34 章节审计领域模型单元测试 — 纯 Pydantic 零 I/O（spec §2.1-§2.4）.

覆盖:
- AuditCheckType 枚举（4 值: word_count / character_drift / setting_drift /
  static_consistency，§2.1）
- AuditSeverity 枚举（3 值: info / warning / error，§2.2）
- ChapterAuditFinding（必填 / 默认值 / JSON dump 键断言防空洞 + roundtrip）
- ChapterAuditReport（必填 / status Literal 校验 / 默认值，§2.2）
- AuditLog（轻量记录实体，§2.3）
- AuditTriggerRequest / AuditConfirmRequest（DTO，§2.4）

设计假设（GREEN 实现契约，依据 specs/f34-chapter-audit/spec.md §2）:
1. 模块路径: inkflow.domain.models.chapter_audit（CREATE；RED 阶段不存在 →
   本文件顶部 import 抛 ModuleNotFoundError = 预期收集期失败，pytest 退出码 2）
2. AuditCheckType 为 StrEnum，成员名 WORD_COUNT / CHARACTER_DRIFT /
   SETTING_DRIFT / STATIC_CONSISTENCY，成员值即 §2.1 四检查项字符串
3. AuditSeverity 为 StrEnum，成员名 INFO / WARNING / ERROR，值 info /
   warning / error（F34 自有枚举——与 F15 domain/models/audit.py 的
   AuditSeverity 同名不同模块，本文件一律从 chapter_audit import）
4. ChapterAuditFinding: check_type / severity / message 必填；suggestion=""
   ref_entity_id=None / ref_entity_name="" / context="" 默认（§2.2 逐字）
5. ChapterAuditReport: chapter_id / chapter_title / findings / created_at 必填
   （findings 为 list[ChapterAuditFinding]）；status: Literal["pending",
   "accepted", "rejected"] 默认 "pending"；summary 默认 ""；degraded 默认
   False；confirmed_at 默认 None
6. AuditLog: id / project_id / chapter_id / chapter_title / status /
   severity_summary / created_at 必填；status Literal 三值（pending/
   accepted/rejected）；summary="" / degraded=False / note="" 默认；
   confirmed_at 默认 None（§2.3 逐字）
7. AuditTriggerRequest.include_static 默认 True（显式 False 覆盖）；
   AuditConfirmRequest.action Literal["accept", "reject"]（非法值
   ValidationError）、note 默认 ""
8. model_dump(mode="json") 键断言（Pydantic v2 extra='ignore' 空洞防护:
   字段缺失时构造不报错，roundtrip 用例必须显式断言 dump 键集再 roundtrip）
9. 本文件 make_finding / make_report / make_log 工厂（base dict + overrides
   覆盖）供 test_chapter_audit_llm.py / test_audit_log_repo.py /
   test_audit_service_confirm.py 镜像复用
10. RED 预期: 收集期 1 error（ModuleNotFoundError: No module named
    'inkflow.domain.models.chapter_audit'），无其他失败
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from inkflow.domain.models.chapter_audit import (
    AuditCheckType,
    AuditConfirmRequest,
    AuditLog,
    AuditSeverity,
    AuditTriggerRequest,
    ChapterAuditFinding,
    ChapterAuditReport,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
EID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def make_finding(**overrides: Any) -> ChapterAuditFinding:
    """构造一条最小合法审计发现（spec §2.2 示例形态），可覆盖任意字段。

    默认 check_type=word_count / severity=info；供本文件及
    test_chapter_audit_llm.py 镜像（GREEN 落地后同构复用）。
    """
    base = {
        "check_type": AuditCheckType.WORD_COUNT,
        "severity": AuditSeverity.INFO,
        "message": "本章 2,845 字，低于目标 3,000 字",
        "suggestion": "",
        "ref_entity_id": None,
        "ref_entity_name": "",
        "context": "",
    }
    base.update(overrides)
    return ChapterAuditFinding(**base)


def make_report(**overrides: Any) -> ChapterAuditReport:
    """构造一份最小合法章节审计报告（默认空 findings），可覆盖任意字段。

    供 test_audit_service_confirm.py 等镜像（如需构造确认后报告）。
    """
    base = {
        "chapter_id": CID,
        "chapter_title": "第 3 章 龙的苏醒",
        "status": "pending",
        "findings": [],
        "summary": "",
        "degraded": False,
        "created_at": TS,
        "confirmed_at": None,
    }
    base.update(overrides)
    return ChapterAuditReport(**base)


def make_log(**overrides: Any) -> AuditLog:
    """构造一条最小合法审计记录（spec §2.3 轻量记录），可覆盖任意字段。

    供 test_audit_log_repo.py / test_audit_service_confirm.py 镜像复用。
    """
    base = {
        "id": uuid.UUID(int=1),
        "project_id": PID,
        "chapter_id": CID,
        "chapter_title": "第 3 章 龙的苏醒",
        "status": "pending",
        "severity_summary": "1 error, 2 warnings, 0 info",
        "summary": "",
        "degraded": False,
        "note": "",
        "created_at": TS,
        "confirmed_at": None,
    }
    base.update(overrides)
    return AuditLog(**base)


class TestAuditCheckTypeEnum:
    """AuditCheckType 枚举（§2.1: 4 检查项）。"""

    def test_has_exactly_four_members(self):
        assert len(AuditCheckType) == 4

    @pytest.mark.parametrize(
        ("member", "expected"),
        [
            ("WORD_COUNT", "word_count"),
            ("CHARACTER_DRIFT", "character_drift"),
            ("SETTING_DRIFT", "setting_drift"),
            ("STATIC_CONSISTENCY", "static_consistency"),
        ],
    )
    def test_members_and_values(self, member, expected):
        assert getattr(AuditCheckType, member).value == expected

    def test_is_str_enum(self):
        assert isinstance(AuditCheckType.WORD_COUNT.value, str)
        assert AuditCheckType("word_count") is AuditCheckType.WORD_COUNT

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            AuditCheckType("typo_check")


class TestAuditSeverityEnum:
    """AuditSeverity 枚举（§2.2: info/warning/error 三级）。"""

    def test_has_exactly_three_members(self):
        assert len(AuditSeverity) == 3

    @pytest.mark.parametrize(
        ("member", "expected"),
        [
            ("INFO", "info"),
            ("WARNING", "warning"),
            ("ERROR", "error"),
        ],
    )
    def test_members_and_values(self, member, expected):
        assert getattr(AuditSeverity, member).value == expected

    def test_is_str_enum(self):
        assert isinstance(AuditSeverity.INFO.value, str)
        assert AuditSeverity("error") is AuditSeverity.ERROR

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            AuditSeverity("critical")


class TestChapterAuditFinding:
    """ChapterAuditFinding（§2.2: 必填 + 默认值 + JSON roundtrip）。"""

    def test_required_only_construction_and_defaults(self):
        finding = make_finding()
        assert finding.check_type is AuditCheckType.WORD_COUNT
        assert finding.severity is AuditSeverity.INFO
        assert finding.message == "本章 2,845 字，低于目标 3,000 字"
        assert finding.suggestion == ""
        assert finding.ref_entity_id is None
        assert finding.ref_entity_name == ""
        assert finding.context == ""

    def test_missing_message_raises(self):
        with pytest.raises(ValidationError):
            ChapterAuditFinding(
                check_type=AuditCheckType.WORD_COUNT,
                severity=AuditSeverity.INFO,
            )

    def test_missing_check_type_raises(self):
        with pytest.raises(ValidationError):
            ChapterAuditFinding(
                severity=AuditSeverity.INFO,
                message="缺检查项类型",
            )

    def test_full_construction_with_ref_entity(self):
        finding = make_finding(
            check_type=AuditCheckType.CHARACTER_DRIFT,
            severity=AuditSeverity.WARNING,
            message="本章「李青焰」怒斥同伴，但角色档案性格为「温厚沉稳」",
            suggestion="可改为隐忍不发，或先铺垫情绪积累",
            ref_entity_id=EID,
            ref_entity_name="李青焰",
            context="“够了！”李青焰猛地拍案而起，怒视众人……",
        )
        assert finding.check_type is AuditCheckType.CHARACTER_DRIFT
        assert finding.severity is AuditSeverity.WARNING
        assert finding.ref_entity_id == EID
        assert finding.ref_entity_name == "李青焰"
        assert finding.context.startswith("“够了！”")

    def test_ref_entity_id_explicit_none(self):
        finding = make_finding(ref_entity_id=None)
        assert finding.ref_entity_id is None

    def test_json_dump_keys_and_roundtrip(self):
        """dump 键集显式断言（防 Pydantic extra='ignore' 空洞）后再 roundtrip。"""
        finding = make_finding(
            check_type=AuditCheckType.CHARACTER_DRIFT,
            severity=AuditSeverity.WARNING,
            message="角色行为可能与人设冲突",
            suggestion="可改为隐忍不发",
            ref_entity_id=EID,
            ref_entity_name="李青焰",
            context="李青焰猛地拍案而起",
        )
        dumped = finding.model_dump(mode="json")
        assert set(dumped.keys()) == {
            "check_type",
            "severity",
            "message",
            "suggestion",
            "ref_entity_id",
            "ref_entity_name",
            "context",
        }
        assert dumped["check_type"] == "character_drift"
        assert dumped["severity"] == "warning"
        assert dumped["message"] == "角色行为可能与人设冲突"
        assert dumped["suggestion"] == "可改为隐忍不发"
        assert dumped["ref_entity_id"] == str(EID)
        assert dumped["ref_entity_name"] == "李青焰"
        assert dumped["context"] == "李青焰猛地拍案而起"
        restored = ChapterAuditFinding.model_validate(dumped)
        assert restored == finding

    def test_json_dump_defaults_roundtrip(self):
        finding = make_finding()
        dumped = finding.model_dump(mode="json")
        assert dumped["suggestion"] == ""
        assert dumped["ref_entity_id"] is None
        assert dumped["ref_entity_name"] == ""
        assert dumped["context"] == ""
        assert ChapterAuditFinding.model_validate(dumped) == finding


class TestChapterAuditReport:
    """ChapterAuditReport（§2.2: 必填 + status Literal + 默认值）。"""

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            ChapterAuditReport(
                chapter_id=CID,
                findings=[],
                created_at=TS,
            )

    def test_status_defaults_to_pending(self):
        report = make_report()
        assert report.status == "pending"

    def test_status_accepts_all_literal_values(self):
        for status in ("accepted", "rejected"):
            assert make_report(status=status).status == status

    def test_status_invalid_value_raises(self):
        with pytest.raises(ValidationError):
            make_report(status="xxx")

    def test_defaults(self):
        report = make_report()
        assert report.summary == ""
        assert report.degraded is False
        assert report.confirmed_at is None

    def test_json_dump_keys_and_roundtrip(self):
        report = make_report(
            findings=[make_finding()],
            summary="本章整体符合设定",
            degraded=True,
            confirmed_at=datetime(2026, 8, 1, 11, 0, 0),
        )
        dumped = report.model_dump(mode="json")
        assert set(dumped.keys()) == {
            "chapter_id",
            "chapter_title",
            "status",
            "findings",
            "summary",
            "degraded",
            "created_at",
            "confirmed_at",
        }
        assert dumped["chapter_id"] == str(CID)
        assert dumped["chapter_title"] == "第 3 章 龙的苏醒"
        assert dumped["status"] == "pending"
        assert dumped["summary"] == "本章整体符合设定"
        assert dumped["degraded"] is True
        assert dumped["confirmed_at"] == "2026-08-01T11:00:00"
        assert len(dumped["findings"]) == 1
        assert ChapterAuditReport.model_validate(dumped) == report


class TestAuditLog:
    """AuditLog（§2.3: 轻量记录实体）。"""

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            AuditLog(
                id=uuid.UUID(int=1),
                project_id=PID,
                chapter_id=CID,
                chapter_title="第 3 章 龙的苏醒",
                status="pending",
                created_at=TS,
            )

    def test_status_literal_values(self):
        for status in ("pending", "accepted", "rejected"):
            assert make_log(status=status).status == status

    def test_status_invalid_value_raises(self):
        with pytest.raises(ValidationError):
            make_log(status="confirmed")

    def test_defaults(self):
        log = make_log()
        assert log.summary == ""
        assert log.degraded is False
        assert log.note == ""
        assert log.confirmed_at is None

    def test_json_dump_keys_and_roundtrip(self):
        log = make_log(
            status="rejected",
            severity_summary="1 error, 2 warnings, 0 info",
            summary="角色行为有出入",
            degraded=True,
            note="人设需再打磨",
            confirmed_at=datetime(2026, 8, 1, 11, 0, 0),
        )
        dumped = log.model_dump(mode="json")
        assert set(dumped.keys()) == {
            "id",
            "project_id",
            "chapter_id",
            "chapter_title",
            "status",
            "severity_summary",
            "summary",
            "degraded",
            "note",
            "created_at",
            "confirmed_at",
        }
        assert dumped["status"] == "rejected"
        assert dumped["severity_summary"] == "1 error, 2 warnings, 0 info"
        assert dumped["note"] == "人设需再打磨"
        assert dumped["confirmed_at"] == "2026-08-01T11:00:00"
        assert AuditLog.model_validate(dumped) == log


class TestAuditTriggerRequest:
    """AuditTriggerRequest（§2.4: include_static 默认 True）。"""

    def test_include_static_defaults_true(self):
        assert AuditTriggerRequest().include_static is True

    def test_include_static_explicit_false(self):
        assert AuditTriggerRequest(include_static=False).include_static is False


class TestAuditConfirmRequest:
    """AuditConfirmRequest（§2.4: action Literal + note 默认）。"""

    def test_action_accept_and_reject(self):
        assert AuditConfirmRequest(action="accept").action == "accept"
        assert AuditConfirmRequest(action="reject").action == "reject"

    def test_action_invalid_raises(self):
        with pytest.raises(ValidationError):
            AuditConfirmRequest(action="xxx")

    def test_note_defaults_empty(self):
        assert AuditConfirmRequest(action="accept").note == ""
