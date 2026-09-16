"""#1174/#1177 审计桥（_audit_bridge）函数级覆盖：F34 findings 映射路径.

为何单列：契约测试 `test_book_agentic_audit_contract.py` 用 **无 findings** 的
鸭子报告驱动 F34 注入路径（断言的是「服务被调用」），未触达 findings→契约字段
的映射分支 → 4 个函数在 coverage-function gate 中计入 new_uncalled：

  - `report_to_audit_dict` 内的 `_drift_messages`（人设/设定漂移消息提取）
  - `score_from_findings`（严重级别扣分）
  - `_dump_finding`（findings 单项 JSON 化）
  - `read_draft_body`（无正文时回读草稿的输入面）

本文件用**真实形态**驱动：F34 报告是带 `findings` 的对象，findings 项带
`check_type` / `severity` / `ref_entity_name` / `message`（镜像
`ChapterAuditFinding`）。断言聚焦映射语义（而非「函数被调到」）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from inkflow.domain.models.chapter_audit import AuditCheckType
from inkflow.infrastructure.agent._audit_bridge import (
    read_draft_body,
    report_to_audit_dict,
    score_from_findings,
)

pytestmark = pytest.mark.asyncio


def _finding(check_type: AuditCheckType, severity: str, message: str, name: str = "") -> object:
    """构造 F34 finding 鸭子对象（镜像 ChapterAuditFinding 字段面）。"""
    return SimpleNamespace(
        check_type=check_type,
        severity=SimpleNamespace(value=severity),
        ref_entity_name=name,
        message=message,
    )


class TestScoreFromFindings:
    async def test_severity_penalties_sum(self) -> None:
        """error 扣 20 / warning 扣 8 / info 扣 2 累加；无 findings → 100."""
        findings = [
            _finding(AuditCheckType.CHARACTER_DRIFT, "error", "人设漂移"),
            _finding(AuditCheckType.SETTING_DRIFT, "warning", "设定漂移"),
            _finding(AuditCheckType.WORD_COUNT, "info", "字数偏低"),
        ]
        assert score_from_findings(findings) == 100 - 20 - 8 - 2

    async def test_score_floor_is_zero(self) -> None:
        """扣分超 100 → 下限 0（不产生负分）。"""
        findings = [_finding(AuditCheckType.STATIC_CONSISTENCY, "error", "硬伤")] * 10
        assert score_from_findings(findings) == 0

    async def test_unknown_severity_not_penalised(self) -> None:
        """未识别级别 → 不扣分（防御分支）。"""
        findings = [SimpleNamespace(severity="catastrophic")]
        assert score_from_findings(findings) == 100


class TestReportToAuditDictWithFindings:
    async def test_drift_messages_prefixed_by_entity_name(self) -> None:
        """有档案条目名 → 「名：消息」；无 → 原消息（_drift_messages 两分支）。"""
        report = SimpleNamespace(
            findings=[
                _finding(AuditCheckType.CHARACTER_DRIFT, "error", "性格前后不一", "宁晚"),
                _finding(AuditCheckType.CHARACTER_DRIFT, "warning", "口头禅丢失"),
                _finding(AuditCheckType.SETTING_DRIFT, "error", "药臼裂纹缺失", "青铜药臼"),
                _finding(AuditCheckType.WORD_COUNT, "info", "字数偏低"),
            ],
            degraded=False,
            chapter_id="ch-1",
        )

        result = report_to_audit_dict(report)

        assert result["character_drift"] == ["宁晚：性格前后不一", "口头禅丢失"]
        assert result["setting_drift"] == ["青铜药臼：药臼裂纹缺失"]
        # issues 取全部 findings 的 message（不区分检查项）
        assert result["issues"] == ["性格前后不一", "口头禅丢失", "药臼裂纹缺失", "字数偏低"]
        # score 由 findings 派生：error+warning+error+info = 20+8+20+2
        assert result["score"] == 100 - 50
        assert result["degraded"] is False
        assert result["chapter_id"] == "ch-1"

    async def test_findings_dumped_to_json_list(self) -> None:
        """findings 逐项经 _dump_finding：Pydantic 模型走 model_dump，鸭子对象退化。"""

        class _ModelFinding:
            def model_dump(self, *, mode: str) -> dict:
                assert mode == "json"
                return {"message": "模型化 finding"}

        report = SimpleNamespace(
            findings=[
                _ModelFinding(),
                SimpleNamespace(message="鸭子 finding"),  # 无 model_dump → 退化
            ]
        )

        result = report_to_audit_dict(report)

        assert result["findings"] == [
            {"message": "模型化 finding"},
            {"message": "鸭子 finding"},
        ]

    async def test_empty_findings_falls_back_to_flat_report(self) -> None:
        """无 findings → 平铺报告兜底（缺失 score → 100）。"""
        result = report_to_audit_dict(SimpleNamespace(issues=["仅问题"], character_drift=["漂移"]))

        assert result["issues"] == ["仅问题"]
        assert result["character_drift"] == ["漂移"]
        assert result["setting_drift"] == []
        assert result["score"] == 100
        assert result["findings"] == []


class TestReadDraftBody:
    async def test_returns_content_when_found(self) -> None:
        class _Drafts:
            async def find_pending(self, project_id, *, source_outline_id):
                assert source_outline_id == "ol-1"
                return SimpleNamespace(content="本章正文")

        body = await read_draft_body(_Drafts(), object(), {"outline_id": "ol-1"})
        assert body == "本章正文"

    async def test_unwired_and_missing_and_error_yield_empty(self) -> None:
        """未装配 / 未命中 / 抛异常 → 空串（绝不炸编排）。"""
        assert await read_draft_body(None, object(), {"outline_id": "ol-1"}) == ""

        class _Miss:
            async def find_pending(self, project_id, *, source_outline_id):
                return None

        assert await read_draft_body(_Miss(), object(), {"outline_id": "ol-1"}) == ""

        class _Boom:
            async def find_pending(self, project_id, *, source_outline_id):
                raise RuntimeError("repository exploded")

        assert await read_draft_body(_Boom(), object(), {"outline_id": "ol-1"}) == ""
