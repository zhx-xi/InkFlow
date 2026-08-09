"""F34 章节审计服务编排单元测试 — Mock 各仓储 + Mock F15 AuditService + Fake LLM + Mock
AuditLogRepositoryProtocol.

覆盖 spec §9.2 关键场景（编号对应）与 §5.1 编排步骤 ①-⑧ / §5.3 降级策略 /
§5.5 静态委托过滤 / §6 检查项规则（word_count 判定边界 + 排序键 + severity_summary）
/ §7 边界与错误处理 / §8.1 构造注入:
- 1 漂移命中: Fake LLM 返回人设冲突 → ERROR finding + ref_entity 正确 + error 排序在前
- 2 LLM 降级: Fake LLM 抛异常 → 报告 degraded=True + 无 LLM 类 findings +
  字数确定性检查照常 + audit_log_repo.add 收到 degraded=True（E5）
- 3 记录落库（Q1=C）: audit 后 audit_log_repo.add 一条 AuditLog（pending +
  severity_summary 格式 + summary + degraded + created_at 与报告一致）
- 4 重复审计: 每次 audit 追加一条记录（E8，两条记录）
- 5 静态委托过滤: F15 报告 5 findings 仅 2 条与本章相关 → 报告 2 条
  static_consistency + suggestion "[rule_id] " 前缀 + severity 保持原级别；
  include_static=False → 委托不被调用
- 6 空档案: 无角色 → character_drift 跳过；无世界观 → setting_drift 跳过；
  两者皆空 → LLM 0 次调用（E2/E3）
- 7 空章节（E4）: content="" → 仅 word_count finding（0 字）+ LLM 0 次 +
  静态委托仍执行（include_static=True）
- 8 字数边界（M2）: 79% → INFO 低于目标 / 80% 无 finding / 120% 无 finding /
  121% → INFO 超出目标 / 0 字 → INFO 低于目标
- 9 排序: (severity 序 error<warning<info, check_type, ref_entity_name)（§6）
- 10-12 错误: 项目不存在 → ProjectNotFoundError / 章节不存在 → ChapterNotFoundError /
  章节跨项目 → ChapterNotFoundError（消息含「不属于该项目」）（E1）
- 13 非法 JSON: 重试 1 次成功（chat 调用 2 次）/ 两次失败 → 降级（E6）
- 14 降级报告可展示: degraded 标记 + 确定性 finding 在（不断言降级说明
  finding 是否存在——实现可选，只钉 degraded 与确定性检查）

设计假设（RED 阶段按 spec 口径记录，实现须满足）:
- 构造签名: ChapterAuditService(*, project_repo, chapter_repo, character_repo,
  world_repo, audit_service, llm_client, audit_log_repo) 全关键字（spec §8.2）
- 方法契约: async audit(project_id, chapter_id, *, include_static=True) ->
  ChapterAuditReport；async confirm(project_id, chapter_id, *, action, note="") ->
  AuditLog；async list_logs(project_id, *, offset=0, limit=20) ->
  tuple[list[AuditLog], int]（confirm/list_logs 本文件不覆盖，归
  test_audit_service_confirm.py / API 层）
- 错误类归属: ProjectNotFoundError 复用 F9 character_errors（404 语义）；
  ChapterNotFoundError 复用 F14 extraction_errors（404 语义；跨项目抛
  ChapterNotFoundError("章节不属于该项目")）；NoPendingAuditError 为 F34
  新建 chapter_audit_errors（422「该章无待确认审计」，confirm 路径——
  本文件补测 confirm 防御分支时 import）

补测覆盖（覆盖率 miss 归因，2026-08）:
- list_logs（L322-325）: 项目不存在 → ProjectNotFoundError；正常返回仓储
  (页, total) 且 offset/limit/int 主键透传
- _load_all 多页（L355）: 满页 50 条后继续拉 offset=50 第二页
- _to_int_id int 分支（L90）: 已是 int 主键原样返回
- confirm 防御分支（L299）: latest_pending 非空但仓储 confirm 返回 None →
  NoPendingAuditError
- LLM 重试循环中第二次 chat 抛异常（L415-416）: 首次非法 JSON → 重试时
  模型异常 → 该检查降级（degraded=True）
- LLM JSON 解析契约: {"findings": [{check_type, severity, message, suggestion,
  ref_entity_id, ref_entity_name, context}]}；severity 值 error/warning/info；
  解析失败重试 1 次（F9 提取管线先例），仍失败 → 该检查降级（§5.2/§5.3）
- 静态委托过滤谓词（定死）: f.entity_type == "chapter" and f.entity_id ==
  chapter_id 或 f.ref_type == "chapter" and f.ref_id == chapter_id；映射
  severity 保持原级别；suggestion 前缀 f"[{rule_id}] "（rule_id 追溯，§5.5）
- severity_summary 格式: "{n_error} error, {n_warning} warnings, {n_info} info"（§6）
- 排序键: (severity 序 error<warning<info, check_type, ref_entity_name)（§6）
- 分页: character/world 仓储 list(project_id, *, offset, limit) -> (list, total)
  元组；分页循环页大小 _PAGE_SIZE=50、章节截断上限 _MAX_CHAPTER_CHARS=8000
  （spec §5.4）——本文件按 spec 值声明常量（模块未实现不能 import），
  测试只覆盖单页返回（F15 _load_all 先例）
- Fake LLM 调用顺序: 人设漂移先于设定漂移（spec §5.1 ④⑤），两次独立 chat 调用；
  测试不断言 chat 的 model/temperature 参数（实现细节），只断言行为结果
- word_count 判定（§6）: word_count < target*0.8 → INFO 低于目标；
  word_count > target*1.2 → INFO 超出目标；边界值（80%/120%）无 finding
- 测试用 async def 裸函数（无 @pytest.mark.asyncio）：pyproject asyncio_mode=auto
  （F15/F16 既有测试先例）

依据: specs/f34-chapter-audit/spec.md §2/§5/§6/§7/§9。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.audit import (
    AuditDimension,
    AuditFinding,
    AuditReport,
    AuditSummary,
)
from inkflow.domain.models.audit import (
    AuditSeverity as F15AuditSeverity,
)
from inkflow.domain.models.chapter import Chapter, ChapterStatus
from inkflow.domain.models.chapter_audit import (  # noqa: F401  # RED: 模块未实现，收集期预期 ModuleNotFoundError
    AuditCheckType,
    AuditLog,
    AuditSeverity,
    ChapterAuditFinding,
    ChapterAuditReport,
)
from inkflow.domain.models.character import Character
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.chapter_audit_errors import NoPendingAuditError
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ChapterNotFoundError
from inkflow.domain.ports.llm_client import ChatMessage, ChatResponse
from inkflow.domain.services.chapter_audit_service import (  # RED: 模块未实现
    ChapterAuditService,
    _to_int_id,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
OTHER_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000099")
CID = uuid.UUID("7a4f2c91-0000-4000-8000-000000000001")
CHAR_ID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000002")
SETTING_ID = uuid.UUID("5c6d7e8f-0000-4000-8000-000000000003")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)

# spec §5.1/§5.4 常量（模块未实现不能 import，按 spec 值声明，实现须一致）
_PAGE_SIZE = 50  # 档案分页循环页大小
_MAX_CHAPTER_CHARS = 8000  # 章节全文截断上限

_MISSING = object()  # _svc 哨兵：区分「未提供（用默认）」与「显式 None（不存在）」


# ── 实体构造 helpers ──────────────────────────────────────────────


def _project(*, word_count_target: int = 3000) -> Project:
    """构造测试项目（PID 所属；config.default_words = 章节目标字数）。"""
    return Project(
        id=PID,
        name="测试项目",
        config=ProjectConfig(default_words=word_count_target),
        created_at=TS,
        updated_at=TS,
    )


def _chapter(
    cid: uuid.UUID,
    *,
    project_id: uuid.UUID = PID,
    title: str = "第 1 章 开端",
    content: str = "林晚推开窗。李青焰站在门外，怒斥道：“够了！”",
    word_count: int = 2400,
) -> Chapter:
    """构造测试章节实体（默认属于 PID，word_count=2400=目标的 80% 边界无 finding）。"""
    return Chapter(
        id=cid,
        project_id=project_id,
        title=title,
        content=content,
        status=ChapterStatus.REVIEW,
        word_count=word_count,
        created_at=TS,
        updated_at=TS,
    )


def _character(
    name: str = "李青焰",
    *,
    personality: str = "温厚沉稳",
    background: str = "药王谷弟子",
    goals: str = "寻回失传丹方",
) -> Character:
    """构造测试角色实体。"""
    return Character(
        id=CHAR_ID,
        project_id=PID,
        name=name,
        personality=personality,
        background=background,
        goals=goals,
        created_at=TS,
        updated_at=TS,
    )


def _setting(name: str = "灵气", content: str = "灵气枯竭三百年，修士以灵石为食") -> WorldSetting:
    """构造测试世界观条目实体。"""
    return WorldSetting(
        id=SETTING_ID,
        project_id=PID,
        name=name,
        content=content,
        created_at=TS,
        updated_at=TS,
    )


def _f15_finding(
    rule_id: str,
    *,
    severity: F15AuditSeverity = F15AuditSeverity.ERROR,
    entity_type: str = "character",
    entity_id: uuid.UUID | None = None,
    entity_name: str = "",
    ref_type: str | None = None,
    ref_id: uuid.UUID | None = None,
) -> AuditFinding:
    """构造 F15 AuditFinding（静态委托 mock 返回值）。"""
    return AuditFinding(
        id=f"{rule_id}:{entity_id or 'x'}",
        rule_id=rule_id,
        dimension=AuditDimension.CHARACTER,
        severity=severity,
        message="F15 静态发现（测试夹具）",
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        ref_type=ref_type,
        ref_id=ref_id,
    )


def _audit_report(findings: list[AuditFinding] | None = None) -> AuditReport:
    """构造 F15 AuditReport（静态委托默认返回值：无 findings）。"""
    findings = findings or []
    return AuditReport(
        project_id=PID,
        generated_at=TS,
        summary=AuditSummary(
            consistent=all(f.severity != F15AuditSeverity.ERROR for f in findings),
            total=len(findings),
        ),
        findings=findings,
    )


def _drift_payload(
    *,
    check_type: str = "character_drift",
    severity: str = "error",
    message: str = "本章「李青焰」怒斥同伴，但角色档案性格为「温厚沉稳」",
    suggestion: str = "可改为隐忍不发",
    ref_entity_id: uuid.UUID = CHAR_ID,
    ref_entity_name: str = "李青焰",
    context: str = "“够了！”",
) -> str:
    """构造 Fake LLM 漂移 findings JSON 字符串（§5.2 解析契约）。"""
    return json.dumps(
        {
            "findings": [
                {
                    "check_type": check_type,
                    "severity": severity,
                    "message": message,
                    "suggestion": suggestion,
                    "ref_entity_id": str(ref_entity_id),
                    "ref_entity_name": ref_entity_name,
                    "context": context,
                }
            ]
        },
        ensure_ascii=False,
    )


class FakeLLM:
    """可配置 Fake LLM — 按调用顺序弹出响应，用尽后返回空 findings；fail=True 每次抛异常。

    chat 调用顺序契约: 人设漂移先于设定漂移（spec §5.1 ④⑤）。
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        *,
        fail: bool = False,
        error: Exception | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self.fail = fail
        self.error = error if error is not None else RuntimeError("llm down")
        self.calls: list[list[ChatMessage]] = []

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: object,
    ) -> ChatResponse:
        """记录调用并按配置返回；fail=True 时抛异常（模拟 LLM 宕机）。"""
        self.calls.append(messages)
        if self.fail:
            raise self.error
        content = self._responses.pop(0) if self._responses else '{"findings": []}'
        return ChatResponse(content=content, model="fake")

    @property
    def call_count(self) -> int:
        """已发起的 chat 调用次数。"""
        return len(self.calls)


# ── 依赖装配 ──────────────────────────────────────────────────────


def _svc(
    *,
    project: Project | object | None = _MISSING,
    chapter: Chapter | object | None = _MISSING,
    characters: list[Character] | object = _MISSING,
    worlds: list[WorldSetting] | object = _MISSING,
    audit_findings: list[AuditFinding] | None = None,
    llm: FakeLLM | None = None,
) -> tuple[ChapterAuditService, dict]:
    """装配 ChapterAuditService（全部 Mock + Fake LLM），返回 (service, mocks)。

    project/chapter/characters/worlds 传 None 表示「不存在/为空」；不传用默认
    （project=default_words 3000、chapter 属于 PID、1 角色 + 1 设定）。
    audit_findings: F15 静态委托返回值 findings（None → 空报告）。
    """
    if project is _MISSING:
        project = _project()
    if chapter is _MISSING:
        chapter = _chapter(CID)
    if characters is _MISSING:
        characters = [_character()]
    if worlds is _MISSING:
        worlds = [_setting()]
    llm = llm if llm is not None else FakeLLM()

    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=project)
    chapter_repo = MagicMock()
    chapter_repo.get_chapter = AsyncMock(return_value=chapter)
    character_repo = MagicMock()
    character_repo.list = AsyncMock(return_value=(characters, len(characters)))
    world_repo = MagicMock()
    world_repo.list = AsyncMock(return_value=(worlds, len(worlds)))
    audit_service = MagicMock()
    audit_service.run_audit = AsyncMock(return_value=_audit_report(audit_findings))
    audit_log_repo = MagicMock()
    audit_log_repo.add = AsyncMock(side_effect=lambda log: log)

    service = ChapterAuditService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        character_repo=character_repo,
        world_repo=world_repo,
        audit_service=audit_service,
        llm_client=llm,
        audit_log_repo=audit_log_repo,
    )
    mocks = {
        "project_repo": project_repo,
        "chapter_repo": chapter_repo,
        "character_repo": character_repo,
        "world_repo": world_repo,
        "audit_service": audit_service,
        "llm": llm,
        "audit_log_repo": audit_log_repo,
    }
    return service, mocks


def _added_log(mocks: dict) -> AuditLog:
    """提取 audit_log_repo.add 最近一次调用的 AuditLog 参数（位置或关键字传参均可）。"""
    call = mocks["audit_log_repo"].add.await_args
    if call.args:
        return call.args[0]
    return call.kwargs["log"]


# ── 1 漂移命中 ────────────────────────────────────────────────────


class TestChapterAuditServiceAudit:
    """ChapterAuditService.audit 编排测试 — 漂移命中 / 降级 / 落库 / 委托过滤 / 边界 / 错误。"""

    async def test_drift_hit_maps_error_finding_with_ref_entity(self) -> None:
        """Fake LLM 人设漂移命中 → ERROR finding + ref_entity 正确 + error 排序在前（§9.2-1）。"""
        llm = FakeLLM(responses=[_drift_payload()])
        service, _ = _svc(llm=llm, worlds=())  # 无世界观 → 仅人设检查 1 次 chat
        report = await service.audit(PID, CID)

        assert report.chapter_id == CID
        assert report.chapter_title == "第 1 章 开端"
        assert report.status == "pending"
        assert report.degraded is False
        drift = [f for f in report.findings if f.check_type == AuditCheckType.CHARACTER_DRIFT]
        assert len(drift) == 1
        f = drift[0]
        assert f.severity == AuditSeverity.ERROR
        assert f.ref_entity_id == CHAR_ID
        assert f.ref_entity_name == "李青焰"
        assert f.context == "“够了！”"
        assert f.suggestion == "可改为隐忍不发"
        assert "李青焰" in f.message
        assert "温厚沉稳" in f.message
        # error 排序在前（本报告仅 1 条 finding，首位即 error）
        assert report.findings[0].severity == AuditSeverity.ERROR
        assert report.findings[0].check_type == AuditCheckType.CHARACTER_DRIFT

    # ── 2 LLM 降级 ──────────────────────────────────────────────────

    async def test_llm_failure_degrades_report_keeps_deterministic(self) -> None:
        """Fake LLM 抛异常 → degraded=True + 无 LLM findings + 字数检查仍在 + 记录
        degraded（§9.2-2/E5）。"""
        llm = FakeLLM(fail=True)
        service, mocks = _svc(llm=llm, chapter=_chapter(CID, word_count=2370))  # 79% → INFO finding
        report = await service.audit(PID, CID)

        assert report.degraded is True
        assert [
            f
            for f in report.findings
            if f.check_type in (AuditCheckType.CHARACTER_DRIFT, AuditCheckType.SETTING_DRIFT)
        ] == []
        wc = [f for f in report.findings if f.check_type == AuditCheckType.WORD_COUNT]
        assert len(wc) == 1
        assert wc[0].severity == AuditSeverity.INFO
        # 人设 + 设定两次 chat 均失败（两档案都非空）
        assert llm.call_count == 2
        # audit_logs 记录 degraded=True（可追溯审计质量）
        assert _added_log(mocks).degraded is True

    # ── 3 记录落库（Q1=C）───────────────────────────────────────────

    async def test_audit_persists_lightweight_log(self) -> None:
        """audit 后落一条 AuditLog（pending + severity_summary + summary + degraded + created_at）
        （§9.2-3）。"""
        llm = FakeLLM(responses=[_drift_payload()])
        service, mocks = _svc(llm=llm, worlds=())  # 报告 = 1 error（人设漂移）
        report = await service.audit(PID, CID)

        mocks["audit_log_repo"].add.assert_awaited_once()
        log = _added_log(mocks)
        assert isinstance(log, AuditLog)
        assert log.project_id == PID
        assert log.chapter_id == CID
        assert log.chapter_title == "第 1 章 开端"  # 标题快照
        assert log.status == "pending"
        assert log.severity_summary == "1 error, 0 warnings, 0 info"  # §6 格式
        assert log.summary == report.summary
        assert log.degraded is False
        assert log.note == ""
        assert log.created_at == report.created_at
        assert log.confirmed_at is None

    # ── 4 重复审计 ──────────────────────────────────────────────────

    async def test_repeated_audit_appends_new_log_each_time(self) -> None:
        """同一章审计两次 → 每次追加一条记录（共 2 条，历史保留；E8）。"""
        service, mocks = _svc(worlds=())
        await service.audit(PID, CID)
        await service.audit(PID, CID)

        assert mocks["audit_log_repo"].add.await_count == 2
        assert len(mocks["audit_log_repo"].add.await_args_list) == 2

    # ── 5 静态委托过滤（F15）────────────────────────────────────────

    async def test_static_delegation_filters_chapter_findings(self) -> None:
        """F15 5 findings 仅 2 条与本章相关 → 报告 2 条 static_consistency（§9.2-5/M9）。"""
        f15 = [
            # 保留 1: entity_type == "chapter" and entity_id == chapter_id
            _f15_finding(
                "chapter.anchor",
                severity=F15AuditSeverity.ERROR,
                entity_type="chapter",
                entity_id=CID,
                entity_name="第 1 章 开端",
            ),
            # 保留 2: ref_type == "chapter" and ref_id == chapter_id（时间线事件挂本章）
            _f15_finding(
                "timeline.dual_consistency",
                severity=F15AuditSeverity.WARNING,
                entity_type="event",
                entity_id=uuid.UUID("88888888-8888-4888-8888-888888888888"),
                entity_name="林晚入宫",
                ref_type="chapter",
                ref_id=CID,
            ),
            # 过滤 3: 角色维度（与本章无关）
            _f15_finding(
                "character.relation_ref",
                entity_type="character",
                entity_id=CHAR_ID,
                entity_name="李青焰",
            ),
            # 过滤 4: ref 目标为角色
            _f15_finding(
                "character.group_ref",
                severity=F15AuditSeverity.WARNING,
                entity_type="character",
                entity_id=CHAR_ID,
                ref_type="character",
                ref_id=CHAR_ID,
            ),
            # 过滤 5: 世界观维度
            _f15_finding(
                "world.entry_health",
                severity=F15AuditSeverity.INFO,
                entity_type="world_setting",
                entity_id=SETTING_ID,
            ),
        ]
        service, mocks = _svc(
            audit_findings=f15, characters=(), worlds=()
        )  # LLM 无输入 + 字数无 finding
        report = await service.audit(PID, CID)

        static = [f for f in report.findings if f.check_type == AuditCheckType.STATIC_CONSISTENCY]
        assert len(static) == 2
        assert len(report.findings) == 2  # 与本章无关的静态 findings 不展示（§5.5）
        # severity 保持 F15 原级别
        by_rule = {f.suggestion.split("]")[0][1:]: f for f in static}
        assert by_rule["chapter.anchor"].severity == AuditSeverity.ERROR
        assert by_rule["timeline.dual_consistency"].severity == AuditSeverity.WARNING
        # suggestion 前缀 f"[{rule_id}] "（rule_id 追溯，§5.5）
        for f in static:
            assert f.suggestion.startswith("[")
            assert "]" in f.suggestion
        assert any(f.suggestion.startswith("[chapter.anchor] ") for f in static)
        assert any(f.suggestion.startswith("[timeline.dual_consistency] ") for f in static)
        # 委托被调用（include_static=True 默认）
        mocks["audit_service"].run_audit.assert_awaited_once()

    async def test_static_delegation_skipped_when_include_static_false(self) -> None:
        """include_static=False → 委托 audit_service.run_audit 不被调用，报告无
        static_consistency。"""
        service, mocks = _svc()
        report = await service.audit(PID, CID, include_static=False)

        mocks["audit_service"].run_audit.assert_not_awaited()
        assert all(f.check_type != AuditCheckType.STATIC_CONSISTENCY for f in report.findings)

    # ── 6 空档案跳过 ────────────────────────────────────────────────

    async def test_empty_characters_skips_character_drift(self) -> None:
        """无角色档案 → character_drift 跳过；设定漂移照常（chat 仅 1 次=设定；E2）。"""
        llm = FakeLLM()
        service, _ = _svc(llm=llm, characters=())
        report = await service.audit(PID, CID)

        assert [f for f in report.findings if f.check_type == AuditCheckType.CHARACTER_DRIFT] == []
        assert llm.call_count == 1  # 仅设定漂移一次 chat

    async def test_empty_worlds_skips_setting_drift(self) -> None:
        """无世界观条目 → setting_drift 跳过；人设漂移照常（chat 仅 1 次；E3）。"""
        llm = FakeLLM()
        service, _ = _svc(llm=llm, worlds=())
        report = await service.audit(PID, CID)

        assert [f for f in report.findings if f.check_type == AuditCheckType.SETTING_DRIFT] == []
        assert llm.call_count == 1  # 仅人设漂移一次 chat

    async def test_both_empty_skips_all_llm_checks(self) -> None:
        """角色与世界观皆空 → LLM 0 次调用（没档案可比对，不报错；E2+E3）。"""
        llm = FakeLLM()
        service, _ = _svc(llm=llm, characters=(), worlds=())
        report = await service.audit(PID, CID)

        assert llm.call_count == 0
        assert [
            f
            for f in report.findings
            if f.check_type in (AuditCheckType.CHARACTER_DRIFT, AuditCheckType.SETTING_DRIFT)
        ] == []

    # ── 7 空章节（E4）───────────────────────────────────────────────

    async def test_empty_chapter_only_word_count_finding(self) -> None:
        """章节无内容 → 仅字数 finding（0 字 INFO）+ LLM 0 次 + 静态委托仍执行（E4）。"""
        llm = FakeLLM()
        service, mocks = _svc(llm=llm, chapter=_chapter(CID, content="", word_count=0))
        report = await service.audit(PID, CID)

        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.check_type == AuditCheckType.WORD_COUNT
        assert f.severity == AuditSeverity.INFO
        assert "低于目标" in f.message
        assert llm.call_count == 0
        mocks["audit_service"].run_audit.assert_awaited_once()  # 静态委托不因空章节跳过

    # ── 8 字数边界（M2）─────────────────────────────────────────────

    @pytest.mark.parametrize(
        ("word_count", "expect_finding", "keyword"),
        [
            (2370, True, "低于目标"),  # 79% → INFO 低于目标
            (2400, False, ""),  # 80% 边界 → 无 finding
            (3600, False, ""),  # 120% 边界 → 无 finding
            (3630, True, "超出目标"),  # 121% → INFO 超出目标
            (0, True, "低于目标"),  # 0 字 → INFO 低于目标
        ],
    )
    async def test_word_count_boundaries(
        self, word_count: int, expect_finding: bool, keyword: str
    ) -> None:
        """字数判定边界（target=3000: 79%/80%/120%/121%/0）（§6/M2）。"""
        service, _ = _svc(chapter=_chapter(CID, word_count=word_count), characters=(), worlds=())
        report = await service.audit(PID, CID)

        wc = [f for f in report.findings if f.check_type == AuditCheckType.WORD_COUNT]
        if expect_finding:
            assert len(wc) == 1
            assert wc[0].severity == AuditSeverity.INFO
            assert keyword in wc[0].message
        else:
            assert wc == []

    # ── 9 排序 ──────────────────────────────────────────────────────

    async def test_findings_sorted_by_severity_then_check_type(self) -> None:
        """混合 error/warning/info → severity 序在前；同级别按 check_type 字符串（§6）。"""
        llm = FakeLLM(
            responses=[
                _drift_payload(),  # 人设漂移 error
                _drift_payload(  # 设定漂移 warning
                    check_type="setting_drift",
                    severity="warning",
                    message="本章灵气充沛，但世界观条目为「灵气枯竭三百年」",
                    ref_entity_id=SETTING_ID,
                    ref_entity_name="灵气",
                ),
            ]
        )
        f15 = [
            _f15_finding(
                "chapter.anchor",
                severity=F15AuditSeverity.ERROR,  # 与 character_drift 同 error 级
                entity_type="chapter",
                entity_id=CID,
                entity_name="第 1 章 开端",
            )
        ]
        service, _ = _svc(
            llm=llm,
            audit_findings=f15,
            chapter=_chapter(CID, word_count=2370),  # word_count info
        )
        report = await service.audit(PID, CID)

        assert [f.check_type for f in report.findings] == [
            AuditCheckType.CHARACTER_DRIFT,  # error 组内 "character_drift" < "static_consistency"
            AuditCheckType.STATIC_CONSISTENCY,
            AuditCheckType.SETTING_DRIFT,  # warning
            AuditCheckType.WORD_COUNT,  # info
        ]

    # ── 10-12 错误（E1）─────────────────────────────────────────────

    async def test_project_not_found_raises(self) -> None:
        """项目不存在（project_repo.get → None）→ ProjectNotFoundError（404 语义）。"""
        service, mocks = _svc(project=None)
        with pytest.raises(ProjectNotFoundError) as excinfo:
            await service.audit(PID, CID)
        assert str(excinfo.value) == "项目不存在"
        mocks["chapter_repo"].get_chapter.assert_not_awaited()
        mocks["audit_log_repo"].add.assert_not_awaited()

    async def test_chapter_not_found_raises(self) -> None:
        """章节不存在（get_chapter → None）→ ChapterNotFoundError。"""
        service, mocks = _svc(chapter=None)
        with pytest.raises(ChapterNotFoundError) as excinfo:
            await service.audit(PID, CID)
        assert str(excinfo.value) == "章节不存在"
        mocks["audit_log_repo"].add.assert_not_awaited()

    async def test_chapter_in_other_project_raises(self) -> None:
        """章节属于其他项目 → ChapterNotFoundError（消息含「不属于该项目」）。"""
        service, mocks = _svc(chapter=_chapter(CID, project_id=OTHER_PID))
        with pytest.raises(ChapterNotFoundError) as excinfo:
            await service.audit(PID, CID)
        assert "不属于该项目" in str(excinfo.value)
        mocks["audit_log_repo"].add.assert_not_awaited()

    # ── 13 非法 JSON 重试（E6）──────────────────────────────────────

    async def test_invalid_json_retried_once_then_succeeds(self) -> None:
        """第一次 "not json" → 重试 1 次成功（chat 调用 2 次）；报告不降级（E6）。"""
        llm = FakeLLM(responses=["not json", _drift_payload()])
        service, _ = _svc(llm=llm, worlds=())  # 仅人设检查
        report = await service.audit(PID, CID)

        assert report.degraded is False
        drift = [f for f in report.findings if f.check_type == AuditCheckType.CHARACTER_DRIFT]
        assert len(drift) == 1
        assert llm.call_count == 2  # 首次解析失败 + 重试 1 次

    async def test_invalid_json_twice_degrades(self) -> None:
        """两次均非法 JSON → 该检查降级（degraded=True，无 character_drift findings）。"""
        llm = FakeLLM(responses=["not json", "not json"])
        service, _ = _svc(llm=llm, worlds=())
        report = await service.audit(PID, CID)

        assert report.degraded is True
        assert llm.call_count == 2
        assert [f for f in report.findings if f.check_type == AuditCheckType.CHARACTER_DRIFT] == []

    # ── 14 降级报告可展示 ───────────────────────────────────────────

    async def test_degraded_report_still_displayable(self) -> None:
        """降级时报告仍可展示: degraded 标记 + 确定性 finding 在（不断言降级说明 finding）。"""
        llm = FakeLLM(fail=True)
        service, _ = _svc(llm=llm, chapter=_chapter(CID, word_count=2370))
        report = await service.audit(PID, CID)

        assert report.degraded is True
        assert isinstance(report.summary, str)  # 摘要可空但不缺字段
        assert any(f.check_type == AuditCheckType.WORD_COUNT for f in report.findings)
        assert not any(
            f.check_type in (AuditCheckType.CHARACTER_DRIFT, AuditCheckType.SETTING_DRIFT)
            for f in report.findings
        )


# ── 补测: list_logs / _load_all 多页 / _to_int_id / confirm 防御 / 重试异常 ──


class _RetryFailLLM(FakeLLM):
    """重试路径内模型异常: 首次返回非法 JSON，重试 chat 抛异常（L415-416）。"""

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: object,
    ) -> ChatResponse:
        self.calls.append(messages)
        if len(self.calls) == 1:
            return ChatResponse(content="not json", model="fake")
        raise RuntimeError("llm down on retry")


class TestChapterAuditServiceListLogs:
    """list_logs（可追溯入口: 404 校验 + 分页透传，L322-325）。"""

    async def test_project_not_found_raises(self) -> None:
        """list_logs 项目不存在（project_repo.get → None）→ ProjectNotFoundError。"""
        service, mocks = _svc(project=None)
        mocks["audit_log_repo"].list = AsyncMock()
        with pytest.raises(ProjectNotFoundError):
            await service.list_logs(PID)
        mocks["audit_log_repo"].list.assert_not_awaited()

    async def test_returns_repo_page_and_total(self) -> None:
        """list_logs 正常路径: 返回仓储 (页, total)，offset/limit/int 主键透传。"""
        service, mocks = _svc()
        mocks["audit_log_repo"].list = AsyncMock(return_value=([], 0))
        logs, total = await service.list_logs(PID, offset=0, limit=20)
        assert logs == []
        assert total == 0
        mocks["audit_log_repo"].list.assert_awaited_once_with(PID.int, offset=0, limit=20)


class TestChapterAuditServiceCoverage:
    """覆盖率 miss 分支补测: _load_all 多页 / _to_int_id / confirm 防御 / 重试异常。"""

    async def test_load_all_paginates_multiple_pages(self) -> None:
        """_load_all 分页循环（L355）: 满页 50 条后 offset=50 拉第二页，档案合并进 LLM。"""
        c1 = _character(name="李青焰")
        c2 = _character(name="林晚")
        llm = FakeLLM()
        service, mocks = _svc(llm=llm, characters=(), worlds=())
        mocks["character_repo"].list = AsyncMock(side_effect=[([c1] * 50, 50), ([c2], 1)])
        await service.audit(PID, CID)

        assert mocks["character_repo"].list.await_count == 2
        first, second = mocks["character_repo"].list.await_args_list
        assert first.args == (PID.int,)
        assert first.kwargs == {"offset": 0, "limit": 50}
        assert second.args == (PID.int,)
        assert second.kwargs == {"offset": 50, "limit": 50}
        # 两页档案进入人设漂移消息（user 消息含 c1 档案名）
        assert llm.call_count == 1
        assert "李青焰" in llm.calls[0][1].content

    def test_to_int_id_int_passthrough(self) -> None:
        """_to_int_id int 分支（L90）: 已是 int 主键原样返回。"""
        assert _to_int_id(123) == 123

    async def test_confirm_defensive_none_from_repo_raises(self) -> None:
        """confirm 防御分支（L299）: latest_pending 非空但仓储 confirm 返回 None
        → NoPendingAuditError（理论不可达的防御语义）。"""
        service, mocks = _svc()
        mocks["audit_log_repo"].latest_pending = AsyncMock(
            return_value=AuditLog(
                id=uuid.UUID(int=1),
                project_id=PID,
                chapter_id=CID,
                chapter_title="第 1 章 开端",
                status="pending",
                severity_summary="0 error, 0 warnings, 0 info",
                created_at=TS,
            )
        )
        mocks["audit_log_repo"].confirm = AsyncMock(return_value=None)
        with pytest.raises(NoPendingAuditError):
            await service.confirm(PID, CID, action="accept")

    async def test_invalid_json_then_model_error_degrades(self) -> None:
        """重试循环内模型异常（L415-416）: 首次非法 JSON → 重试 chat 抛异常
        → 该检查降级（chat 2 次 + degraded=True）。"""
        llm = _RetryFailLLM()
        service, _ = _svc(llm=llm, worlds=())
        report = await service.audit(PID, CID)

        assert report.degraded is True
        assert llm.call_count == 2
        assert [f for f in report.findings if f.check_type == AuditCheckType.CHARACTER_DRIFT] == []
