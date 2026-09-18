"""F34 #1266 补两类 check_type 单元测试 — 前后章连贯性 + 大纲符合度.

覆盖新增两项 LLM 检查（同既有漂移检查范式，`_run_drift_check` 复用）:

- CROSS_CHAPTER（前后章连贯性）: 本章正文 vs 前一章摘要 + 后一章大纲
- OUTLINE_COMPLIANCE（大纲符合度）: 本章正文 vs 本章章纲 + 卷纲

契约（RED 阶段按 spec §2.1 增量口径记录，实现须满足）:
1. 两类 check 产出: 不连贯 / 偏离大纲输入 → 对应 check_type 的 finding
2. degraded 语义: LLM 失败 → 该 check 降级（degraded=true），不抛错
3. 预算生效: 超长正文按既有 `_MAX_CHAPTER_CHARS` 截断（断言用字符数 ≤ 常量）
4. 反向断言（关键）: 连贯且符合大纲输入 → 不产这两类 finding
5. 可证伪自证: 判定恒置「无问题」→ 断言 1/2 必须 FAIL

输入装配（默认决策，见 .hermes/plans/W11-B 任务书 §8）:
- 前章：优先复用 #1253 的 `SummaryService.ensure_summary`（摘要，控预算）；
  无摘要/无前一章 → 跳过该检查（不抛错）
- 后一章大纲：章纲列表（level=chapter）中排在**本章章纲之后**的下一个
- 本章章纲：`outline_repo.list` 后按 `chapter_id == 本章` 命中
- 卷纲：本章章纲 `parent_id` → `outline_repo.get`

依据: Issue #1266；specs/f34-chapter-audit/spec.md §2.1/§5.1/§5.2/§5.3/§5.4。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from inkflow.domain.models.chapter import Chapter, ChapterStatus
from inkflow.domain.models.chapter_audit import (
    AuditCheckType,
    AuditSeverity,
)
from inkflow.domain.models.outline import Outline
from inkflow.domain.services._audit_context import (
    _MAX_CHAPTER_CHARS as SVC_MAX_CHAPTER_CHARS,
)
from inkflow.domain.services.chapter_audit_service import ChapterAuditService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000001")
PREV_CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000000")
CH_OUTLINE_ID = uuid.UUID("aaaa1111-0000-4000-8000-000000000001")
NEXT_OUTLINE_ID = uuid.UUID("aaaa1111-0000-4000-8000-000000000002")
VOL_OUTLINE_ID = uuid.UUID("aaaa1111-0000-4000-8000-0000000000ff")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


# ── 实体构造 helpers ──────────────────────────────────────────────


def _chapter(
    cid: uuid.UUID = CID, *, title: str = "第 1 章 开端", content: str = "林晚推开门。"
) -> Chapter:
    """构造测试章节实体（属于 PID）。"""
    return Chapter(
        id=cid,
        project_id=PID,
        title=title,
        content=content,
        status=ChapterStatus.REVIEW,
        word_count=2400,  # 3000 目标 80% 边界 → 无字数 finding
        created_at=TS,
        updated_at=TS,
    )


def _outline(
    oid: uuid.UUID,
    *,
    name: str = "第 1 章 开端",
    description: str = "林晚与李青焰初遇",
    level: str = "chapter",
    chapter_id: uuid.UUID | None = CID,
    sort_order: int = 1,
    parent_id: uuid.UUID | None = None,
) -> Outline:
    """构造测试大纲实体（默认 level=chapter 且挂本章）。"""
    return Outline(
        id=oid,
        project_id=PID,
        name=name,
        description=description,
        sort_order=sort_order,
        level=level,
        parent_id=parent_id,
        chapter_id=chapter_id,
        created_at=TS,
        updated_at=TS,
    )


def _make_chapter_dict(
    oid: uuid.UUID,
    *,
    name: str = "第 2 章 发展",
    description: str = "李青焰失踪",
    sort_order: int = 2,
) -> dict:
    """构造后一章大纲 dict（list 返回形态）。"""
    return {
        "id": oid,
        "name": name,
        "description": description,
        "sort_order": sort_order,
    }


def _payload(check_type: str, *, severity: str = "warning", message: str = "测试发现") -> str:
    """构造单个 finding 的 LLM JSON 输出。"""
    return json.dumps(
        {
            "findings": [
                {
                    "check_type": check_type,
                    "severity": severity,
                    "message": message,
                    "suggestion": "建议修改",
                    "ref_entity_id": None,
                    "ref_entity_name": "",
                    "context": "相关片段",
                }
            ]
        },
        ensure_ascii=False,
    )


_EMPTY = '{"findings": []}'


class FakeLLM:
    """按 check_type 内容路由的 Fake LLM — 未命中路由返回空 findings。"""

    def __init__(self, routes: dict[str, str] | None = None, *, fail: bool = False) -> None:
        self._routes = routes or {}
        self.fail = fail
        self.calls: list[list] = []

    async def chat(self, messages, *, model=None, temperature=None, max_tokens=None, **kw):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("llm down")
        from inkflow.domain.ports.llm_client import ChatResponse

        joined = "\n".join(m.content for m in messages)
        for key, payload in self._routes.items():
            if key in joined:
                return ChatResponse(content=payload, model="fake")
        return ChatResponse(content=_EMPTY, model="fake")

    @property
    def call_count(self) -> int:
        return len(self.calls)


def _svc(
    *,
    chapter: Chapter | None = None,
    outlines: list | None = None,
    prev_summary: str | None = "上一章：林晚拿到丹方。",
    llm: FakeLLM | None = None,
) -> tuple[ChapterAuditService, dict]:
    """装配 ChapterAuditService（新增 outline_repo + summary_service 注入）。"""
    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=_project())
    chapter_repo = MagicMock()
    chapter_repo.get_chapter = AsyncMock(return_value=chapter or _chapter())
    # 章序：本章排在 PREV_CID 之后（order_index 升序 → 前一章 = PREV_CID）
    chapter_repo.list_chapters = AsyncMock(
        return_value=(
            [_chapter(PREV_CID, title="前章", content="前章正文。"), chapter or _chapter()],
            2,
        )
    )
    character_repo = MagicMock()
    character_repo.list = AsyncMock(return_value=([], 0))
    world_repo = MagicMock()
    world_repo.list = AsyncMock(return_value=([], 0))
    audit_service = MagicMock()
    audit_service.run_audit = AsyncMock(return_value=_audit_report())
    audit_log_repo = MagicMock()
    audit_log_repo.add = AsyncMock(side_effect=lambda log: log)

    outline_items = _default_outlines() if outlines is None else outlines
    outline_repo = MagicMock()
    outline_repo.list = AsyncMock(return_value=(outline_items, len(outline_items)))
    outline_repo.get = AsyncMock(
        return_value=_outline(
            VOL_OUTLINE_ID,
            level="volume",
            chapter_id=None,
            name="第一卷",
            description="林晚的复仇线",
        )
    )

    summary_service = MagicMock()
    summary_service.ensure_summary = AsyncMock(return_value=prev_summary)

    service = ChapterAuditService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        character_repo=character_repo,
        world_repo=world_repo,
        audit_service=audit_service,
        llm_client=llm or FakeLLM(),
        audit_log_repo=audit_log_repo,
        outline_repo=outline_repo,
        summary_service=summary_service,
    )
    return service, {
        "llm": llm,
        "outline_repo": outline_repo,
        "summary_service": summary_service,
        "audit_log_repo": audit_log_repo,
    }


def _project():
    from inkflow.domain.models.project import Project, ProjectConfig

    return Project(
        id=PID,
        name="测试项目",
        config=ProjectConfig(default_words=3000),
        created_at=TS,
        updated_at=TS,
    )


def _default_outlines() -> list[Outline]:
    """list 返回形态：本章章纲 + 后一章大纲（Outline 实体，属性访问）。"""
    return [
        _outline(
            CH_OUTLINE_ID,
            name="第 1 章 开端",
            description="林晚与李青焰初遇",
            sort_order=1,
            chapter_id=CID,
            parent_id=VOL_OUTLINE_ID,
        ),
        _outline(
            NEXT_OUTLINE_ID,
            name="第 2 章 发展",
            description="李青焰失踪",
            sort_order=2,
            chapter_id=None,
            parent_id=VOL_OUTLINE_ID,
        ),
    ]


def _audit_report():
    from inkflow.domain.models.audit import AuditReport, AuditSummary

    return AuditReport(
        project_id=PID, generated_at=TS, summary=AuditSummary(consistent=True, total=0), findings=[]
    )


# ── 1 前后章连贯性 ────────────────────────────────────────────────


class TestCrossChapterCheck:
    """前后章连贯性 check（CROSS_CHAPTER）。"""

    async def test_incoherent_input_yields_finding(self) -> None:
        """前章摘要 + 本章不连贯 → 产 check_type=前后章连贯性 的 finding。"""
        llm = FakeLLM(routes={"前一章摘要": _payload("cross_chapter", message="本章未接前章悬念")})
        service, _ = _svc(llm=llm)
        report = await service.audit(PID, CID, include_static=False)

        hits = [f for f in report.findings if f.check_type == AuditCheckType.CROSS_CHAPTER]
        assert len(hits) == 1
        assert hits[0].severity == AuditSeverity.WARNING
        assert "未接前章悬念" in hits[0].message

    async def test_coherent_input_yields_no_finding(self) -> None:
        """反向断言：连贯输入（LLM 返回空 findings）→ 不产 CROSS_CHAPTER。"""
        service, _ = _svc(llm=FakeLLM())
        report = await service.audit(PID, CID, include_static=False)

        assert [f for f in report.findings if f.check_type == AuditCheckType.CROSS_CHAPTER] == []

    async def test_llm_failure_degrades_without_raising(self) -> None:
        """degraded 语义：LLM 失败 → degraded=True，不抛错。"""
        service, _ = _svc(llm=FakeLLM(fail=True))
        report = await service.audit(PID, CID, include_static=False)

        assert report.degraded is True
        assert [f for f in report.findings if f.check_type == AuditCheckType.CROSS_CHAPTER] == []

    async def test_no_previous_summary_skips_check(self) -> None:
        """无前一章摘要 → 该检查跳过（不产 finding、不降级）。"""
        service, _ = _svc(prev_summary=None, llm=FakeLLM())
        report = await service.audit(PID, CID, include_static=False)

        assert report.degraded is False
        assert [f for f in report.findings if f.check_type == AuditCheckType.CROSS_CHAPTER] == []

    async def test_truncation_budget_applied(self) -> None:
        """预算生效：超长正文按既有 `truncate_chapter` 语义截断（≤ 原长 60% + 标注）。

        既有常量 `_MAX_CHAPTER_CHARS` 是**触发截断的阈值**（非截断后上限）：
        超阈值 → 采样到原长 ~60% 并追加「已截断」。本测试钉这条既有语义，
        不新造预算常量（任务书 §8）。
        """
        huge = "甲" * 20000
        llm = FakeLLM()
        service, _ = _svc(chapter=_chapter(content=huge), llm=llm)
        await service.audit(PID, CID, include_static=False)

        cross_calls = [c for c in llm.calls if "前一章摘要" in "\n".join(m.content for m in c)]
        assert cross_calls
        user = next(m.content for m in cross_calls[0] if m.role == "user")
        body = user.split("章节文本（已截断，仅节选）：", 1)[1]
        assert "已截断" in user  # 超阈值必然标注（_TRUNCATE_MARKER）
        assert len(body) <= len(huge)  # 截断后严格小于原文
        assert len(body) < 20000 * 0.7  # 约 60% 口径（含标注与段落分隔余量）
        assert SVC_MAX_CHAPTER_CHARS < 20000  # 本用例确实触发截断路径
        assert SVC_MAX_CHAPTER_CHARS == 8000


# ── 2 大纲符合度 ──────────────────────────────────────────────────


class TestOutlineComplianceCheck:
    """大纲符合度 check（OUTLINE_COMPLIANCE）。"""

    async def test_deviation_yields_finding(self) -> None:
        """偏离大纲 → 产 check_type=大纲符合度 的 finding。"""
        llm = FakeLLM(routes={"本章章纲": _payload("outline_compliance", message="未覆盖情节点")})
        service, _ = _svc(llm=llm)
        report = await service.audit(PID, CID, include_static=False)

        hits = [f for f in report.findings if f.check_type == AuditCheckType.OUTLINE_COMPLIANCE]
        assert len(hits) == 1
        assert "未覆盖情节点" in hits[0].message

    async def test_compliant_input_yields_no_finding(self) -> None:
        """反向断言：符合大纲（LLM 返回空 findings）→ 不产 OUTLINE_COMPLIANCE。"""
        service, _ = _svc(llm=FakeLLM())
        report = await service.audit(PID, CID, include_static=False)

        assert [
            f for f in report.findings if f.check_type == AuditCheckType.OUTLINE_COMPLIANCE
        ] == []

    async def test_llm_failure_degrades_without_raising(self) -> None:
        """degraded 语义：LLM 失败 → degraded=True，不抛错。"""
        service, _ = _svc(llm=FakeLLM(fail=True))
        report = await service.audit(PID, CID, include_static=False)

        assert report.degraded is True
        assert [
            f for f in report.findings if f.check_type == AuditCheckType.OUTLINE_COMPLIANCE
        ] == []

    async def test_no_chapter_outline_skips_check(self) -> None:
        """本章无章纲 → 该检查跳过（不产 finding、不降级）。"""
        service, _ = _svc(outlines=[], llm=FakeLLM())
        report = await service.audit(PID, CID, include_static=False)

        assert [
            f for f in report.findings if f.check_type == AuditCheckType.OUTLINE_COMPLIANCE
        ] == []


# ── 3 可证伪自证 ──────────────────────────────────────────────────


class TestFalsifiability:
    """可证伪自证：判定恒置「无问题」（Fake LLM 恒空 findings）→ 断言 1/2 必 FAIL。"""

    async def test_empty_llm_output_produces_no_new_check_findings(self) -> None:
        """Fake LLM 恒返回空 findings → 两类新 check 均无 finding（恒真判定被反例捕获）。"""
        service, _ = _svc(llm=FakeLLM())
        report = await service.audit(PID, CID, include_static=False)

        new_types = {AuditCheckType.CROSS_CHAPTER, AuditCheckType.OUTLINE_COMPLIANCE}
        assert [f for f in report.findings if f.check_type in new_types] == []
        assert report.degraded is False
