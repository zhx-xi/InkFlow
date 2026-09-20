"""#1318 RED 契约 — F15 确定性审计规则 `chapter.title_echo`（标题回声残留）。

来源: issue #1318 ④「审计零标题检查」

现状（实证）
------------
- `AuditCheckType` 6 项无格式项；4 条 LLM 检查 prompt 无一提标题；
  `FormatValidator` 的 R3 是空实现（`_format_validator.py:26`「跳过——当前不做强制校验」）
- F15 的 9 条确定性规则（R-C1/R-C2/R-T1/R-W1/R-W2/R-F1/R-F2/R-X1/R-X2）
  **无一条**检查章节正文格式 → 收口剥离漏判时**无人发现**

落点（已定论，见 issue 评论「方案裁定 D3」）
--------------------------------------------
加进 `audit_service.py` 的 F15 **内联规则族**：
- `rule_id` 先例 `:286/:316/:372/:417/:435/:482/:503/:567/:590`
- `entity_type="chapter"` 先例 `:620`
- 经 `chapter_audit_service._static_findings`（`:674-705`）映射为
  `static_consistency` → **无需新增 check_type**，前端审计弹层与 F34 spec §2.1 零改动

契约
----
A1 命中：章节正文首行为标题回声（`strip_first_line_title_echo` 判据）→
     产 `rule_id="chapter.title_echo"` 的 finding，`entity_type="chapter"`、
     级别 **WARNING**（格式瑕疵，非数据一致性 error —— 不影响 `consistent`）
A2 不误报：首行为合法正文段落 → **零** finding（对齐 C2 的误删面为零）
A3 已剥离的正文 → 零 finding（幂等：修过的章不再报）
A4 维度归属：`AuditDimension.CROSS`（镜像 R-X2 的 chapter 归档规则，`entity_type="chapter"`）
A5 章节过滤：f15 finding 经 `_static_findings` 映射为本章 `static_consistency`

基线: main @ ffd825b2
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.audit import AuditDimension, AuditSeverity
from inkflow.domain.models.chapter import Chapter
from inkflow.domain.models.project import Project
from inkflow.domain.models.timeline import ConsistencyReport, TimelineView
from inkflow.domain.services.audit_service import AuditService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CH_1 = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)

FW = "\u3000"

RULE_ID = "chapter.title_echo"

# 真实样本（rc4 逐字）
TITLE_CH3 = "第3章 旧宅旧事一桩"
ECHO_CH3 = f"{FW}{FW}三章{FW}旧宅旧事一桩"


def _project() -> Project:
    return Project(id=PID, name="测试项目", created_at=TS, updated_at=TS)


def _chapter(cid: uuid.UUID, title: str, content: str) -> Chapter:
    return Chapter(id=cid, project_id=PID, title=title, content=content)


def _empty_report() -> ConsistencyReport:
    """构造全一致的时间线检查报告（本文件不关心时间线维度）。"""
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


async def _empty_view(project_id: uuid.UUID) -> TimelineView:
    """构造空双线视图（无事件 → 不产时间线 findings）。"""
    return TimelineView(project_id=PID, total=0, event_timeline=[], narrative_order=[])


class _Deps:
    """F15 依赖集合（镜像 test_audit_service_refs.py 的 _Deps，仅取本文件所需）。"""

    def __init__(self, chapters: list[Chapter]) -> None:
        self.project_repo = MagicMock()
        self.project_repo.get = AsyncMock(return_value=_project())
        self.character_repo = MagicMock()
        self.character_repo.list = AsyncMock(return_value=([], 0))
        self.character_repo.list_relations = AsyncMock(return_value=[])
        self.character_repo.list_groups = AsyncMock(return_value=[])
        self.world_repo = MagicMock()
        self.world_repo.list = AsyncMock(return_value=([], 0))
        self.timeline_service = MagicMock()
        self.timeline_service.get_timeline_view = AsyncMock(side_effect=_empty_view)
        self.timeline_service.check_consistency = AsyncMock(return_value=_empty_report())
        self.foreshadowing_repo = MagicMock()
        self.foreshadowing_repo.list = AsyncMock(return_value=([], 0))
        self.chapter_repo = MagicMock()
        self.chapter_repo.list_chapters = AsyncMock(return_value=(chapters, len(chapters)))
        self.run_repo = MagicMock()
        self.run_repo.list = AsyncMock(return_value=([], 0))
        self.audit_repo = MagicMock()

    def service(self) -> AuditService:
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


def _title_echo_findings(report) -> list:
    return [f for f in report.findings if f.rule_id == RULE_ID]


class TestA1TitleEchoDetected:
    """A1: 首行标题回声 → 产 finding（收口漏判的可观测性兜底）。"""

    @pytest.mark.asyncio
    async def test_indented_echo_produces_warning(self) -> None:
        """🔴 主用例：rc4 形态（丢「第」+ 缩进）→ chapter.title_echo WARNING。"""
        deps = _Deps([_chapter(CH_1, TITLE_CH3, f"{ECHO_CH3}\n\n第二段正文。")])

        report = await deps.service().run_audit(PID)

        findings = _title_echo_findings(report)
        assert len(findings) == 1, f"未产出 chapter.title_echo finding: {report.findings!r}"
        finding = findings[0]
        assert finding.severity is AuditSeverity.WARNING
        assert finding.entity_type == "chapter"
        assert finding.entity_id == CH_1
        assert finding.dimension is AuditDimension.CROSS
        assert TITLE_CH3 in finding.message

    @pytest.mark.asyncio
    async def test_inner_space_echo_produces_warning(self) -> None:
        """ch8 形态（章名内部多空格）同样命中。"""
        title = "第8章 接任理账柴米艰难"
        deps = _Deps([_chapter(CH_1, title, f"{FW}{FW}第8章 接任理账 柴米艰难\n\n正文。")])

        report = await deps.service().run_audit(PID)

        assert len(_title_echo_findings(report)) == 1


class TestA2NoFalsePositive:
    """A2: 合法正文首行 → 零 finding（与判据的误删面同源）。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("name", "content"),
        [
            ("章名后接正文", f"{FW}第三章 旧宅旧事一桩，是他童年的全部记忆。\n\n正文。"),
            ("章名不等", f"{FW}第8章 接任理账 全书的第一处转折\n\n正文。"),
            ("散文章回", f"{FW}十七八章回小说里，常有这样的桥段。\n\n正文。"),
            ("顶格等价行（通用归一路径管）", f"{TITLE_CH3}\n\n正文。"),
            ("普通正文", f"{FW}晨光透过窗棂。\n\n正文。"),
        ],
    )
    async def test_legal_prose_no_finding(self, name: str, content: str) -> None:
        deps = _Deps([_chapter(CH_1, TITLE_CH3, content)])

        report = await deps.service().run_audit(PID)

        assert _title_echo_findings(report) == [], f"[{name}] 误报了标题回声"

    @pytest.mark.asyncio
    async def test_empty_content_no_finding(self) -> None:
        deps = _Deps([_chapter(CH_1, TITLE_CH3, "")])

        report = await deps.service().run_audit(PID)

        assert _title_echo_findings(report) == []


class TestA3AlreadyStrippedNoFinding:
    """A3: 已剥离的正文 → 零 finding（幂等，修过不再报）。"""

    @pytest.mark.asyncio
    async def test_stripped_chapter_clean(self) -> None:
        from inkflow.domain.models.chapter import strip_first_line_title_echo

        stripped = strip_first_line_title_echo(f"{ECHO_CH3}\n\n第二段正文。", TITLE_CH3)
        deps = _Deps([_chapter(CH_1, TITLE_CH3, stripped)])

        report = await deps.service().run_audit(PID)

        assert _title_echo_findings(report) == []


class TestA4WarningKeepsConsistent:
    """A4: WARNING 级不影响 `summary.consistent`（格式瑕疵非数据一致性 error）。"""

    @pytest.mark.asyncio
    async def test_consistent_true_despite_title_echo(self) -> None:
        deps = _Deps([_chapter(CH_1, TITLE_CH3, f"{ECHO_CH3}\n\n正文。")])

        report = await deps.service().run_audit(PID)

        assert _title_echo_findings(report), "前置条件：应产出标题回声 finding"
        assert report.summary.consistent is True
        assert report.summary.by_dimension[AuditDimension.CROSS].warning >= 1
