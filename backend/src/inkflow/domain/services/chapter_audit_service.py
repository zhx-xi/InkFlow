"""F34 章节审计服务编排（spec §5.1/§5.2/§5.3/§5.5/§6/§8.2）.

ChapterAuditService 是 F34 的编排核心，构造注入 F1/F2/F9/F10/F15 仓储与服务
以及 F5 LLMClient（全部 Protocol，ADR-015），audit 按 spec §5.1 步骤 ①-⑧ 执行:

① 项目校验（project_repo.get → None → ProjectNotFoundError 404）
② 章节校验（get_chapter → None → ChapterNotFoundError；跨项目同样 404）
③ 字数检查（确定性，spec §6: <80% → INFO 低于目标 / >120% → INFO 超出目标，
   80%/120% 边界不产 finding；0 字 → 低于目标）
④ 空章节判断（content.strip() == "" → LLM 检查跳过，静态委托照常）
⑤ LLM 输入准备（truncate_chapter 截断 + select_entities 档案选取）
⑥ 人设漂移（build_character_drift_messages → chat(temperature=0.2) →
   parse_drift_output；解析失败重试 1 次；模型异常/两次失败 → 该检查降级）
⑦ 设定漂移（同 ⑥，build_setting_drift_messages）
⑧ 静态一致性委托（include_static=True 时委托 F15 run_audit，过滤本章相关
   findings 并映射为 static_consistency，suggestion 前缀 [rule_id] 追溯）
⑨ 组装报告 + 落 audit_logs 轻量记录（severity_summary 计数 + summary + degraded）

confirm/list_logs 复用同一套前置校验（项目 + 章节），confirm 取最新 pending
记录并委托仓储确认（action → accepted/rejected + note + confirmed_at）。

LLM 失败语义（spec §5.3）: 模型调用异常/解析失败 → 该检查项 findings 为空 +
degraded: true，绝不透传——HTTP 仍 200，确定性检查照常返回。

只依赖 domain/ports/ 与 domain/models/（Protocol 与纯 Pydantic 模型），
不依赖任何 infrastructure 实现——domain/ 零框架 import 门禁天然满足
（ADR-002/015）。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from inkflow.domain.models.audit import AuditFinding, AuditReport
from inkflow.domain.models.chapter_audit import (
    AuditCheckType,
    AuditLog,
    AuditSeverity,
    ChapterAuditFinding,
    ChapterAuditReport,
)
from inkflow.domain.ports.audit_log_repository import AuditLogRepositoryProtocol
from inkflow.domain.ports.chapter_audit_errors import NoPendingAuditError
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.extraction_errors import ChapterNotFoundError
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._audit_context import select_entities, truncate_chapter
from inkflow.domain.services._audit_prompts import (
    build_character_drift_messages,
    build_setting_drift_messages,
    parse_drift_output,
)
from inkflow.domain.services.audit_service import AuditService

_PAGE_SIZE = 50
"""档案分页循环页大小（spec §5.4，F15 `_load_all` 同款模式）。"""

_TEMPERATURE = 0.2
"""结构化输出固定低温（F16 `_style_llm_analyzer` 先例，spec §5.2）。"""

_MAX_PARSE_ATTEMPTS = 2
"""LLM 输出解析尝试上限（首次 + 解析失败重试 1 次，spec §5.3 E6）。"""

_SEVERITY_ORDER: dict[AuditSeverity, int] = {
    AuditSeverity.ERROR: 0,
    AuditSeverity.WARNING: 1,
    AuditSeverity.INFO: 2,
}
"""严重级别排序序（spec §6: error < warning < info）。"""


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1/F14/F15 `_to_int_id` 模式）。

    Args:
        value: 领域 UUID 或已有 int 主键.

    Returns:
        仓储层 int 主键（UUID 取其 int 表示）.
    """
    if isinstance(value, uuid.UUID):
        return value.int
    return value


def _finding_sort_key(finding: ChapterAuditFinding) -> tuple[int, str, str]:
    """findings 稳定排序键（spec §6: severity 序 + check_type + ref_entity_name）.

    Args:
        finding: 单条章节审计发现.

    Returns:
        (严重级别序, check_type 字符串值, ref_entity_name) 排序键.
    """
    return (
        _SEVERITY_ORDER[finding.severity],
        finding.check_type.value,
        finding.ref_entity_name,
    )


class ChapterAuditService:
    """章节审计服务（spec §5）——LLM 主体 + 确定性兜底编排.

    依赖全部通过构造函数注入（ADR-015/ADR-009，测试注入 Mock）:

    Args:
        project_repo: F1 项目仓储——项目校验（步骤 ①，404 语义）.
        chapter_repo: F2 章节仓储——章节读取与跨项目校验（步骤 ②）.
        character_repo: F9 角色仓储——人设漂移档案读取（分页全量）.
        world_repo: F10 世界观仓储——设定漂移条目读取（分页全量）.
        audit_service: F15 一致性审计服务——静态委托（include_static=True）.
        llm_client: F5 LLM 客户端——人设/设定漂移分析（失败降级不抛出）.
        audit_log_repo: F34 审计日志仓储——轻量记录落库与确认状态机.
    """

    def __init__(
        self,
        *,
        project_repo: ProjectRepositoryProtocol,
        chapter_repo: ChapterRepositoryProtocol,
        character_repo: CharacterRepositoryProtocol,
        world_repo: WorldRepositoryProtocol,
        audit_service: AuditService,
        llm_client: LLMClientProtocol,
        audit_log_repo: AuditLogRepositoryProtocol,
    ) -> None:
        self._project_repo = project_repo
        self._chapter_repo = chapter_repo
        self._character_repo = character_repo
        self._world_repo = world_repo
        self._audit_service = audit_service
        self._llm = llm_client
        self._audit_log_repo = audit_log_repo

    # ──── 服务编排（spec §5.1 步骤 ①-⑨）──────────────────────────────

    async def audit(
        self,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID,
        *,
        include_static: bool = True,
    ) -> ChapterAuditReport:
        """执行单章审计编排（spec §5.1 步骤 ①-⑧）.

        流程: 项目校验 → 章节校验 → 字数检查 → 空章节判断 → LLM 输入准备 →
        人设漂移 → 设定漂移 → 静态一致性委托 → 组装报告 → 落轻量记录.
        只读幂等：同一输入两次审计除 created_at 外逐字段相等；任何仓储读取
        失败即抛出透传，不产出部分报告（F15 先例）.

        Args:
            project_id: 所属项目 UUID.
            chapter_id: 待审计章节 UUID.
            include_static: 是否包含 F15 静态一致性委托（默认 True）.

        Returns:
            ChapterAuditReport（status=pending + findings + degraded 标记）.

        Raises:
            ProjectNotFoundError: 项目不存在（404 语义）.
            ChapterNotFoundError: 章节不存在或属于其他项目（404 语义）.
        """
        # ① 项目校验（服务层统一校验一次，404）
        project = await self._project_repo.get(_to_int_id(project_id))
        if project is None:
            raise ProjectNotFoundError()

        # ② 章节校验（含跨项目，F34 语义 404）
        chapter = await self._chapter_repo.get_chapter(_to_int_id(chapter_id))
        if chapter is None:
            raise ChapterNotFoundError()
        if chapter.project_id != project_id:
            raise ChapterNotFoundError("章节不属于该项目")

        findings: list[ChapterAuditFinding] = []
        degraded = False

        # ③ 字数检查（确定性，spec §6: 80%/120% 边界不产 finding）
        findings.extend(self._word_count_findings(project.config.default_words, chapter.word_count))

        # ④ 空章节判断：无内容 → LLM 检查跳过（chat 不调用），静态委托照常
        if chapter.content.strip():
            # ⑤ LLM 输入准备（截断 + 档案分页全量 + 条目选取）
            chapter_text, truncated = truncate_chapter(chapter.content)
            chars = await self._load_all(self._character_repo.list, project_id)
            worlds = await self._load_all(self._world_repo.list, project_id)

            # ⑥ 人设漂移检查（LLM，空档案跳过）
            if chars:
                selected_chars = select_entities(chars, chapter.content)
                drift, check_degraded = await self._run_drift_check(
                    build_character_drift_messages(chapter_text, selected_chars, truncated)
                )
                findings.extend(drift)
                degraded = degraded or check_degraded

            # ⑦ 设定漂移检查（LLM，空档案跳过）
            if worlds:
                selected_worlds = select_entities(worlds, chapter.content)
                drift, check_degraded = await self._run_drift_check(
                    build_setting_drift_messages(chapter_text, selected_worlds, truncated)
                )
                findings.extend(drift)
                degraded = degraded or check_degraded

        # ⑧ 静态一致性委托（F15，过滤本章相关 findings，rule_id 可追溯）
        if include_static:
            f15_report = await self._audit_service.run_audit(project_id)
            findings.extend(self._static_findings(f15_report, chapter_id))

        # ⑨ 组装报告（findings 稳定排序）→ 落 audit_logs 轻量记录 → 返回
        report = ChapterAuditReport(
            chapter_id=chapter_id,
            chapter_title=chapter.title,
            status="pending",
            findings=sorted(findings, key=_finding_sort_key),
            summary="",
            degraded=degraded,
            created_at=datetime.now(UTC),
            confirmed_at=None,
        )
        await self._audit_log_repo.add(
            AuditLog(
                id=uuid.uuid4(),
                project_id=project_id,
                chapter_id=chapter_id,
                chapter_title=chapter.title,
                status="pending",
                severity_summary=self._severity_summary(report.findings),
                summary=report.summary,
                degraded=degraded,
                created_at=report.created_at,
                confirmed_at=None,
            )
        )
        return report

    async def confirm(
        self,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID,
        *,
        action: str,
        note: str = "",
    ) -> AuditLog:
        """确认章节审计（spec §5.1 ⑨）——只更新 audit_logs 状态，无业务副作用.

        校验顺序（spec §3.3 异常映射）: 项目存在 → 章节存在且属于该项目 →
        该章最新记录为 pending → 委托仓储 confirm 更新并返回.

        Args:
            project_id: 所属项目 UUID.
            chapter_id: 待确认章节 UUID.
            action: 确认动作（accept → accepted / reject → rejected）.
            note: 拒绝原因/备注（可选，写入 audit_logs.note）.

        Returns:
            更新后的 AuditLog（status/confirmed_at/note 已由仓储落库）.

        Raises:
            ProjectNotFoundError: 项目不存在（404 语义）.
            ChapterNotFoundError: 章节不存在或属于其他项目（404 语义）.
            NoPendingAuditError: 该章无待确认审计（422 语义）.
        """
        # ① 项目校验（同 audit 步骤 ①）
        project = await self._project_repo.get(_to_int_id(project_id))
        if project is None:
            raise ProjectNotFoundError()

        # ② 章节校验（含跨项目，同 audit 步骤 ②）
        chapter = await self._chapter_repo.get_chapter(_to_int_id(chapter_id))
        if chapter is None:
            raise ChapterNotFoundError()
        if chapter.project_id != project_id:
            raise ChapterNotFoundError("章节不属于该项目")

        # ③ 最新记录须为 pending（已确认/从未审计 → 422）
        log = await self._audit_log_repo.latest_pending(_to_int_id(chapter_id))
        if log is None:
            raise NoPendingAuditError()

        # ④ 委托仓储确认（领域 UUID → int 主键）
        confirmed = await self._audit_log_repo.confirm(
            log.id.int,
            action=action,
            note=note,
            confirmed_at=datetime.now(UTC),
        )
        if confirmed is None:
            # 理论不可达（latest_pending 刚返回非空）：防御性降级语义
            raise NoPendingAuditError()
        return confirmed

    async def list_logs(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[AuditLog], int]:
        """分页查询项目审计日志（created_at desc 最新在前，可追溯入口）.

        Args:
            project_id: 所属项目 UUID.
            offset: 分页偏移（默认 0）.
            limit: 每页条数（默认 20）.

        Returns:
            (页内 AuditLog 列表, 该项目审计记录总数).

        Raises:
            ProjectNotFoundError: 项目不存在（404 语义）.
        """
        project = await self._project_repo.get(_to_int_id(project_id))
        if project is None:
            raise ProjectNotFoundError()
        return await self._audit_log_repo.list(_to_int_id(project_id), offset=offset, limit=limit)

    # ──── 内部辅助（确定性 + LLM 降级 + 静态映射）─────────────────────

    async def _load_all(
        self,
        repo_list: Callable[..., Awaitable[tuple[list[Any], int]]],
        project_id: uuid.UUID,
    ) -> list[Any]:
        """分页循环拉取全部档案（list(limit=50) 循环直到不足一页）.

        各模块 Protocol 仅有分页 list（limit 默认 50），服务层循环拉取
        （offset += 50 直到返回页不足一页，防止死循环）——不给 F9/F10 增加
        list_all 方法（spec §5.1 要点 5，F15 `_load_all` 同款）.

        Args:
            repo_list: 各模块仓储的分页 list 方法（首参 project_id int，
                支持 offset/limit 关键字）.
            project_id: 所属项目 UUID.

        Returns:
            全部档案列表（分页合并，读取顺序即各仓储返回顺序）.
        """
        items: list[Any] = []
        offset = 0
        while True:
            page, _total = await repo_list(_to_int_id(project_id), offset=offset, limit=_PAGE_SIZE)
            items.extend(page)
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
        return items

    def _word_count_findings(self, target: int, word_count: int) -> list[ChapterAuditFinding]:
        """字数确定性检查（spec §6: 低于 80% / 超出 120% 各产 1 条 INFO）.

        边界: 恰好 80%（target*0.8）与 120%（target*1.2）不产 finding；
        0 字（空章节）→ 低于目标 INFO.

        Args:
            target: 项目章节目标字数（project.config.default_words）.
            word_count: 章节存储字数（F2 存储值，直接使用）.

        Returns:
            字数检查发现列表（边界内为空）.
        """
        if word_count < target * 0.8:
            return [
                ChapterAuditFinding(
                    check_type=AuditCheckType.WORD_COUNT,
                    severity=AuditSeverity.INFO,
                    message=f"本章 {word_count:,} 字，低于目标 {target:,} 字",
                )
            ]
        if word_count > target * 1.2:
            return [
                ChapterAuditFinding(
                    check_type=AuditCheckType.WORD_COUNT,
                    severity=AuditSeverity.INFO,
                    message=f"本章 {word_count:,} 字，超出目标 {target:,} 字",
                )
            ]
        return []

    async def _run_drift_check(
        self, messages: list[ChatMessage]
    ) -> tuple[list[ChapterAuditFinding], bool]:
        """执行单路 LLM 漂移检查（spec §5.2/§5.3）——失败降级绝不抛出.

        策略: 模型调用异常 → 该检查项 findings 为空 + degraded=true（不重试）；
        解析失败 → 重新调用 chat 重试 1 次；仍失败 → 同上降级.

        Args:
            messages: 人设/设定漂移提示词（[system, user]）.

        Returns:
            (该检查项 findings, 是否降级)；findings 由 parse_drift_output
            保证 check_type 合法（无效整批视为 None → 降级）.
        """
        try:
            response = await self._llm.chat(messages, temperature=_TEMPERATURE)
        except Exception:
            # 模型调用异常 → 立即降级，不消耗解析重试（spec §5.3 表格首行）
            return [], True
        parsed = parse_drift_output(response.content)
        if parsed is not None:
            return parsed, False
        for _ in range(_MAX_PARSE_ATTEMPTS - 1):
            try:
                response = await self._llm.chat(messages, temperature=_TEMPERATURE)
            except Exception:
                return [], True
            parsed = parse_drift_output(response.content)
            if parsed is not None:
                return parsed, False
        return [], True

    def _static_findings(
        self, f15_report: AuditReport, chapter_id: uuid.UUID
    ) -> list[ChapterAuditFinding]:
        """过滤并映射 F15 静态审计发现（spec §5.5）.

        仅保留与本章相关的 F15 findings: entity_type == "chapter" 且
        entity_id == chapter_id，或 ref_type == "chapter" 且 ref_id ==
        chapter_id；映射为 static_consistency 类型，severity 保持原级别，
        suggestion 前缀 [rule_id] 追溯来源（§5.5）.

        Args:
            f15_report: F15 run_audit 返回的审计报告.
            chapter_id: 本章 UUID（entity_id/ref_id 直接比较）.

        Returns:
            映射后的 static_consistency 发现列表（与本章无关的不展示）.
        """
        result: list[ChapterAuditFinding] = []
        for finding in f15_report.findings:
            if not self._is_chapter_finding(finding, chapter_id):
                continue
            result.append(
                ChapterAuditFinding(
                    check_type=AuditCheckType.STATIC_CONSISTENCY,
                    severity=AuditSeverity(finding.severity.value),
                    message=finding.message,
                    suggestion=f"[{finding.rule_id}] {finding.message}",
                    ref_entity_id=None,
                    ref_entity_name=finding.entity_name,
                )
            )
        return result

    @staticmethod
    def _is_chapter_finding(finding: AuditFinding, chapter_id: uuid.UUID) -> bool:
        """判定 F15 finding 是否与本章相关（spec §5.5 过滤谓词）.

        Args:
            finding: F15 单条审计发现.
            chapter_id: 本章 UUID.

        Returns:
            True = 与本章相关（主体或引用目标为本章）.
        """
        return (finding.entity_type == "chapter" and finding.entity_id == chapter_id) or (
            finding.ref_type == "chapter" and finding.ref_id == chapter_id
        )

    @staticmethod
    def _severity_summary(findings: list[ChapterAuditFinding]) -> str:
        """生成 severity 计数摘要（spec §6: "{n_error} error, ..." 落库格式）.

        Args:
            findings: 报告 findings 列表.

        Returns:
            计数摘要字符串，如 "1 error, 2 warnings, 0 info".
        """
        n_error = sum(1 for f in findings if f.severity == AuditSeverity.ERROR)
        n_warning = sum(1 for f in findings if f.severity == AuditSeverity.WARNING)
        n_info = sum(1 for f in findings if f.severity == AuditSeverity.INFO)
        return f"{n_error} error, {n_warning} warnings, {n_info} info"
