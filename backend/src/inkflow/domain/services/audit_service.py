"""F15 一致性审计服务 — 跨 4 档案的确定性规则引擎（spec §5）.

AuditService 是 F15 的编排核心: 构造注入 F1/F2/F9/F10/F12/F13/F14 各仓储
Protocol 与 F12 TimelineService，run_audit 按 spec §5.1 步骤 ①-⑤ 执行:

① 项目校验（ProjectRepositoryProtocol.get → None → ProjectNotFoundError 404）
② 单次全量读取（分页循环 list(limit=100) 拉取角色/世界条目/伏笔/章节/runs，
   list_relations/list_groups 全量，TimelineService.get_timeline_view 全量事件）
③ 8 条确定性规则（§5.2 注册表，按维度顺序执行，纯内存）:
   - R-C1 关系引用完整性 / R-C2 分组引用完整性（character）
   - R-T1 委托 F12 check_consistency 双线一致性（timeline，转换不重写算法）
   - R-W1 条目内容健康度 / R-W2 档案缺口（world）
   - R-F1 event_id 锚点存在性 / R-F2 status-resolved_at 状态机一致性（foreshadowing）
   - R-X1 事件 source_chapter_id 章节校验 / R-X2 提取 run 缺口（cross）
④ 汇总（AuditSummary: by_dimension 计数 + counts 档案规模，consistent 仅由
   error 级 findings 决定，§6.2）
⑤ findings 稳定排序（dimension 序 → severity 序 → entity_name → id，§6.3）
   → 返回 AuditReport（timeline_check 嵌套 F12 原始报告，§5.3）

引用完整性分级（#211 真删语义）: F9/F12 删除已统一为真删，无软删集合；
引用目标不在活动集合即悬空 → error；无「软删 → warning」档。F2 章节为
硬删除（无软删概念），R-X1 只有 error 档（§5.5 注）。

只依赖 domain/ports/ 与 domain/services/（Protocol 与领域服务），不依赖任何
infrastructure 实现——domain/ 零框架 import 门禁天然满足（ADR-002/015）。

依据: specs/f15-audit-service/spec.md §5/§6/§7/§8.1。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from inkflow.domain.models.audit import (
    AuditDimension,
    AuditFinding,
    AuditReport,
    AuditSeverity,
    AuditSummary,
    DimensionSummary,
)
from inkflow.domain.models.chapter import Chapter
from inkflow.domain.models.character import Character, CharacterGroup, CharacterRelation
from inkflow.domain.models.extraction import ExtractionRun, ExtractionStatus
from inkflow.domain.models.foreshadowing import Foreshadowing, ForeshadowingStatus
from inkflow.domain.models.project import Project
from inkflow.domain.models.timeline import ConsistencyReport, TimelineConflict, TimelineEvent
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.audit_errors import ProjectNotFoundError
from inkflow.domain.ports.audit_repository import AuditRepositoryProtocol
from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol
from inkflow.domain.ports.character_repository import CharacterRepositoryProtocol
from inkflow.domain.ports.extraction_run_repository import ExtractionRunRepositoryProtocol
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services.timeline_service import TimelineService

_PAGE_SIZE = 100
"""分页循环页大小（spec §5.1 要点 5: list(limit=100) 循环拉取全量）。"""

_RUN_ERROR_MAX_CHARS = 500
"""R-X2 run.error 截断上限（spec §7: error 截断 ≤ 500 字符入 data）。"""

# 维度枚举序（spec §6.1: character → timeline → world → foreshadowing → cross）。
_DIMENSION_ORDER: dict[AuditDimension, int] = {
    AuditDimension.CHARACTER: 0,
    AuditDimension.TIMELINE: 1,
    AuditDimension.WORLD: 2,
    AuditDimension.FORESHADOWING: 3,
    AuditDimension.CROSS: 4,
}

# 严重级别序（spec §6.3: error → warning → info）。
_SEVERITY_ORDER: dict[AuditSeverity, int] = {
    AuditSeverity.ERROR: 0,
    AuditSeverity.WARNING: 1,
    AuditSeverity.INFO: 2,
}


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1/F14 `_to_int_id` 模式）。

    Args:
        value: 领域 UUID 或已有 int 主键.

    Returns:
        仓储层 int 主键（UUID 取其 int 表示）.
    """
    if isinstance(value, uuid.UUID):
        return value.int
    return value


def _finding_sort_key(finding: AuditFinding) -> tuple[int, int, str]:
    """findings 稳定排序键（spec §6.3: dimension 序 → severity 序 → id）.

    同维度同级别内按 finding.id（稳定键）升序——完全确定性，快照断言友好；
    时间线冲突对 id 含两端 UUID，天然保持数据源（conflicts/flashbacks 数组）
    的相对顺序。

    Args:
        finding: 单条审计发现.

    Returns:
        (维度枚举序, 级别序, id) 排序键.
    """
    return (
        _DIMENSION_ORDER[finding.dimension],
        _SEVERITY_ORDER[finding.severity],
        finding.id,
    )


class AuditService:
    """一致性审计服务（spec §5）— 跨 4 档案的确定性规则引擎.

    依赖全部通过构造函数注入（ADR-015/ADR-009，测试注入 Mock）:

    Args:
        project_repo: F1 项目仓储——get 项目校验（§5.1 步骤 ①，404 语义）.
        character_repo: F9 角色仓储——角色/关系/分组档案读取（R-C1/R-C2 + counts）.
        world_repo: F10 世界仓储——世界条目读取（R-W1/R-W2 + counts）.
        timeline_service: F12 时间线服务——get_timeline_view 全量事件 + 委托
            check_consistency 双线一致性（R-T1/R-F1/R-X1 数据源，§5.3）.
        foreshadowing_repo: F13 伏笔仓储——伏笔档案读取（R-F1/R-F2 + counts）.
        chapter_repo: F2 章节仓储——章节读取（R-W2/R-X1/R-X2 + counts）.
        run_repo: F14 run 仓储——extraction_runs 读取（R-X2 + counts）.

    只依赖 domain/ports/ 与 domain/services/（Protocol 与领域服务），
    不依赖任何 infrastructure 实现——domain/ 零框架 import 门禁天然满足
    （ADR-002/015）。
    """

    def __init__(
        self,
        project_repo: ProjectRepositoryProtocol,
        character_repo: CharacterRepositoryProtocol,
        world_repo: WorldRepositoryProtocol,
        timeline_service: TimelineService,
        foreshadowing_repo: ForeshadowingRepositoryProtocol,
        chapter_repo: ChapterRepositoryProtocol,
        run_repo: ExtractionRunRepositoryProtocol,
        audit_repo: AuditRepositoryProtocol | None = None,
    ) -> None:
        self._project_repo = project_repo
        self._character_repo = character_repo
        self._world_repo = world_repo
        self._timeline_service = timeline_service
        self._foreshadowing_repo = foreshadowing_repo
        self._chapter_repo = chapter_repo
        self._run_repo = run_repo

    # ── 服务编排（spec §5.1 步骤 ①-⑤）────────────────────────────

    async def run_audit(self, project_id: uuid.UUID) -> AuditReport:
        """4 维度一致性审计编排（spec §5.1 步骤 ①-⑤）.

        流程: 项目校验 → 单次全量读取（分页循环）→ 8 条规则按维度顺序执行
        （全部纯内存）→ 汇总（counts + by_dimension，consistent 仅由 error
        决定）→ findings 稳定排序 → 返回 AuditReport（timeline_check 嵌套
        F12 原始报告）。只读幂等：同一数据两次审计报告逐字段相等（§6.4）;
        任一仓储读取失败即抛异常透传，不产出部分报告（§5.1 要点 6）。

        Args:
            project_id: 所属项目 UUID.

        Returns:
            AuditReport 审计报告（summary + findings + timeline_check）.

        Raises:
            ProjectNotFoundError: 项目不存在（404 语义）.
            各仓储读取异常 / TimelineService 委托异常: 透传（router 转 500）.
        """
        # ① 项目校验（服务层统一校验一次，404）
        project = await self._project_repo.get(_to_int_id(project_id))
        if project is None:
            raise ProjectNotFoundError()

        # ② 单次全量读取（分页循环取全量，共享同一次快照，§5.1 要点 4/5）
        chars: list[Character] = await self._load_all(self._character_repo.list, project_id)
        rels: list[CharacterRelation] = await self._character_repo.list_relations(
            _to_int_id(project_id)
        )
        groups: list[CharacterGroup] = await self._character_repo.list_groups(
            _to_int_id(project_id)
        )
        worlds: list[WorldSetting] = await self._load_all(self._world_repo.list, project_id)
        view = await self._timeline_service.get_timeline_view(project_id)
        events: list[TimelineEvent] = view.narrative_order if view is not None else []
        fores: list[Foreshadowing] = await self._load_all(self._foreshadowing_repo.list, project_id)
        chapters: list[Chapter] = await self._load_all(self._chapter_repo.list_chapters, project_id)
        runs: list[ExtractionRun] = await self._load_all(self._run_repo.list, project_id)

        # ③ 规则引擎（按维度枚举序执行，全部纯内存，§5.2/§6.1）
        findings: list[AuditFinding] = []
        findings.extend(self._audit_character(chars, rels, groups))
        timeline_check = await self._timeline_service.check_consistency(
            project_id, include_flashbacks=True
        )
        findings.extend(self._audit_timeline(timeline_check))
        findings.extend(self._audit_world(worlds, len(chapters), project))
        findings.extend(self._audit_foreshadowing(fores, events))
        findings.extend(self._audit_cross(events, chapters, runs))

        # ④ 汇总 + ⑤ 排序（§6.2/§6.3）
        counts = {
            "characters": len(chars),
            "relations": len(rels),
            "groups": len(groups),
            "world_settings": len(worlds),
            "events": len(events),
            "foreshadowings": len(fores),
            "chapters": len(chapters),
            "extraction_runs": len(runs),
        }
        summary = self._summarize(findings, counts)
        return AuditReport(
            project_id=project_id,
            generated_at=datetime.now(UTC),
            summary=summary,
            findings=sorted(findings, key=_finding_sort_key),
            timeline_check=timeline_check,
        )

    # ── 全量读取（spec §5.1 要点 5: 分页循环，零跨模块 MODIFY）────

    async def _load_all(
        self,
        repo_list: Callable[..., Awaitable[tuple[list[Any], int]]],
        project_id: uuid.UUID,
    ) -> list[Any]:
        """分页循环拉取全量档案（list(limit=100) 循环直到不足一页）.

        各模块 Protocol 只有分页 list（limit ≤ 100），F15 服务层循环拉取
        （offset += 100 直到返回页不足一页，防死循环）——不给 F9/F10/F13 加
        list_all 方法（§5.1 要点 5，YAGNI）。

        Args:
            repo_list: 各模块仓储的分页 list 方法（首参 project_id int，
                支持 offset/limit 关键字）.
            project_id: 所属项目 UUID.

        Returns:
            全量档案列表（分页合并，读取顺序即各仓储返回顺序）.
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

    # ── 规则引擎（spec §5.2 注册表，按维度分组）────────────────────

    def _audit_character(
        self,
        chars: list[Character],
        rels: list[CharacterRelation],
        groups: list[CharacterGroup],
    ) -> list[AuditFinding]:
        """角色维度规则 — R-C1 关系引用完整性 + R-C2 分组引用完整性（§5.4）.

        #211 真删语义: F9 删除为硬删除，无软删集合；引用目标不在活动集合即
        悬空 → error（无「软删 → warning」档）。
        R-C1: 活动关系的 from/to 端指向不存在的角色（悬空）→ error「不存在」。
        R-C2: 活动角色的 group_id 指向不存在分组（悬空）→ error；
        group_id=None（未分组）跳过。

        Args:
            chars: 活动角色列表（分页循环全量）.
            rels: 活动关系列表（list_relations 全量，真删后无软删关系）.
            groups: 活动分组列表（list_groups 全量）.

        Returns:
            R-C1/R-C2 审计发现列表.
        """
        active = {c.id for c in chars}
        active_groups = {g.id for g in groups}
        names = {c.id: c.name for c in chars}
        findings: list[AuditFinding] = []

        # R-C1 关系引用完整性（§5.4: 对每条关系的两端逐一判定）
        for rel in rels:
            from_name = names.get(rel.from_character_id, "??")
            to_name = names.get(rel.to_character_id, "??")
            rel_label = f"{from_name}→{to_name}"
            for end_id, end_label in (
                (rel.from_character_id, "from"),
                (rel.to_character_id, "to"),
            ):
                if end_id in active:
                    continue
                findings.append(
                    AuditFinding(
                        id=f"character.relation_ref:{rel.id}",
                        rule_id="character.relation_ref",
                        dimension=AuditDimension.CHARACTER,
                        severity=AuditSeverity.ERROR,
                        message=(
                            f"关系 {rel_label} 的 {end_label} 端指向不存在的角色"
                            "（悬空引用，请删除该关系或恢复目标角色）"
                        ),
                        entity_type="relation",
                        entity_id=rel.id,
                        entity_name=rel_label,
                        ref_type="character",
                        ref_id=end_id,
                        data={
                            "relation_type": rel.relation_type,
                            "from_character_id": str(rel.from_character_id),
                            "to_character_id": str(rel.to_character_id),
                        },
                    )
                )

        # R-C2 分组引用完整性（§5.4: 对每条已分组角色的 group_id 判定）
        for char in chars:
            if char.group_id is None:
                continue
            if char.group_id in active_groups:
                continue
            findings.append(
                AuditFinding(
                    id=f"character.group_ref:{char.id}",
                    rule_id="character.group_ref",
                    dimension=AuditDimension.CHARACTER,
                    severity=AuditSeverity.ERROR,
                    message=(
                        f"角色 {char.name} 的分组引用指向不存在的分组"
                        "（悬空引用，请修正分组或删除该角色）"
                    ),
                    entity_type="character",
                    entity_id=char.id,
                    entity_name=char.name,
                    ref_type="group",
                    ref_id=char.group_id,
                )
            )
        return findings

    def _audit_timeline(self, report: ConsistencyReport | None) -> list[AuditFinding]:
        """时间线维度规则 — R-T1 委托 F12 转换（§5.3，不重写算法）.

        将 F12 check_consistency 返回的 ConsistencyReport 转换为统一 findings:
        conflicts[]（order_conflict）→ error；flashbacks[]（flashback/
        flashforward，已声明合法）→ info；checked/skipped 为观测数据进嵌套
        报告不产 finding。finding 定位: entity=prev（叙事靠前者）、ref=next;
        id 稳定键 = `timeline.dual_consistency:{prev_id}:{next_id}`。

        Args:
            report: F12 check_consistency 原始报告（None = 无事件/委托失败，
                不产 finding，timeline_check 嵌套 None）.

        Returns:
            R-T1 转换后的审计发现列表.
        """
        if report is None:
            return []
        findings: list[AuditFinding] = []
        for conflict in report.conflicts:
            findings.append(self._conflict_finding(conflict, AuditSeverity.ERROR))
        for conflict in report.flashbacks:
            findings.append(self._conflict_finding(conflict, AuditSeverity.INFO))
        return findings

    def _conflict_finding(
        self, conflict: TimelineConflict, severity: AuditSeverity
    ) -> AuditFinding:
        """单条时间线冲突/倒叙 → finding（§5.3 转换表）.

        Args:
            conflict: F12 冲突/倒叙记录（含 prev/next 事件引用快照）.
            severity: order_conflict → error；flashback/flashforward → info.

        Returns:
            转换后的审计发现（data 含 conflict_type 与 prev/next 快照）.
        """
        is_conflict = conflict.conflict_type == "order_conflict"
        return AuditFinding(
            id=f"timeline.dual_consistency:{conflict.prev.id}:{conflict.next.id}",
            rule_id="timeline.dual_consistency",
            dimension=AuditDimension.TIMELINE,
            severity=severity,
            message=(
                f"未声明的倒叙: {conflict.message}"
                if is_conflict
                else f"已声明的倒叙: {conflict.message}"
            ),
            entity_type="event",
            entity_id=conflict.prev.id,
            entity_name=conflict.prev.title,
            ref_type="event",
            ref_id=conflict.next.id,
            data={
                "conflict_type": conflict.conflict_type,
                "prev": conflict.prev,
                "next": conflict.next,
            },
        )

    def _audit_world(
        self, worlds: list[WorldSetting], n_chapters: int, project: Project
    ) -> list[AuditFinding]:
        """世界维度规则 — R-W1 条目内容健康度 + R-W2 档案缺口（§5.4）.

        R-W1: 活动条目 content strip 后为空 → info「缺少内容」。
        R-W2: 项目有 ≥ 1 个活动章节且 0 个活动世界条目 → info「尚未建立
        世界观档案」（缺口提示，不涉及一致性）。

        Args:
            worlds: 活动世界条目列表（分页循环全量）.
            n_chapters: 活动章节数.
            project: 已校验的所属项目（R-W2 定位字段用）.

        Returns:
            R-W1/R-W2 审计发现列表.
        """
        findings: list[AuditFinding] = []

        # R-W1 条目内容健康度（§5.4: content 为空/纯空白 → info）
        for setting in worlds:
            if not setting.content.strip():
                findings.append(
                    AuditFinding(
                        id=f"world.entry_content:{setting.id}",
                        rule_id="world.entry_content",
                        dimension=AuditDimension.WORLD,
                        severity=AuditSeverity.INFO,
                        message=(
                            f"条目 {setting.name} 缺少内容描述（仅有名称），"
                            "可运行 inkflow extract run --type setting 提取补充"
                        ),
                        entity_type="world_setting",
                        entity_id=setting.id,
                        entity_name=setting.name,
                    )
                )

        # R-W2 档案缺口（§5.4: 有章节无世界档案 → info）
        if n_chapters >= 1 and not worlds:
            findings.append(
                AuditFinding(
                    id=f"world.archive_gap:{project.id}",
                    rule_id="world.archive_gap",
                    dimension=AuditDimension.WORLD,
                    severity=AuditSeverity.INFO,
                    message=(
                        f"项目已有 {n_chapters} 个章节但尚未建立世界观档案"
                        "（可运行 inkflow extract run --type setting 提取）"
                    ),
                    entity_type="project",
                    entity_id=project.id,
                    entity_name=project.name,
                )
            )
        return findings

    def _audit_foreshadowing(
        self,
        fores: list[Foreshadowing],
        events: list[TimelineEvent],
    ) -> list[AuditFinding]:
        """伏笔维度规则 — R-F1 event_id 锚点存在性 + R-F2 状态机一致性（§5.4）.

        #211 真删语义: F12 事件删除为硬删除，无软删集合；event_id 不在活动
        集合即悬空 → error（无「软删 → warning」档）。
        R-F1: 活动伏笔的 event_id 指向不存在的事件（悬空）→ error「不存在」；
        event_id=None（未挂接）跳过。
        R-F2: status=resolved 且 resolved_at=None → error；status=open 且
        resolved_at 非空 → error（状态与时间戳矛盾）。

        Args:
            fores: 活动伏笔列表（分页循环全量，全部状态）.
            events: 活动事件列表（TimelineService 视图 narrative_order）.

        Returns:
            R-F1/R-F2 审计发现列表.
        """
        active_events = {e.id for e in events}
        findings: list[AuditFinding] = []

        # R-F1 事件锚点（§5.4: 对每条已挂接伏笔的 event_id 判定）
        for f in fores:
            if f.event_id is None:
                continue
            if f.event_id in active_events:
                continue
            findings.append(
                AuditFinding(
                    id=f"foreshadowing.event_anchor:{f.id}",
                    rule_id="foreshadowing.event_anchor",
                    dimension=AuditDimension.FORESHADOWING,
                    severity=AuditSeverity.ERROR,
                    message=(
                        f"伏笔「{f.title}」锚点事件不存在（悬空锚点，"
                        "请修正 event_id 或恢复目标事件）"
                    ),
                    entity_type="foreshadowing",
                    entity_id=f.id,
                    entity_name=f.title,
                    ref_type="event",
                    ref_id=f.event_id,
                )
            )

        # R-F2 状态机一致性（§5.4: status 与 resolved_at 矛盾 → error）
        for f in fores:
            if f.status == ForeshadowingStatus.RESOLVED and f.resolved_at is None:
                findings.append(
                    AuditFinding(
                        id=f"foreshadowing.status_time:{f.id}",
                        rule_id="foreshadowing.status_time",
                        dimension=AuditDimension.FORESHADOWING,
                        severity=AuditSeverity.ERROR,
                        message=(
                            f"伏笔「{f.title}」状态为 resolved 但 resolved_at 为空"
                            "（状态与时间戳矛盾）"
                        ),
                        entity_type="foreshadowing",
                        entity_id=f.id,
                        entity_name=f.title,
                    )
                )
            elif f.status == ForeshadowingStatus.OPEN and f.resolved_at is not None:
                findings.append(
                    AuditFinding(
                        id=f"foreshadowing.status_time:{f.id}",
                        rule_id="foreshadowing.status_time",
                        dimension=AuditDimension.FORESHADOWING,
                        severity=AuditSeverity.ERROR,
                        message=(
                            f"伏笔「{f.title}」状态为 open 但存在 resolved_at"
                            "（状态与时间戳矛盾）"
                        ),
                        entity_type="foreshadowing",
                        entity_id=f.id,
                        entity_name=f.title,
                    )
                )
        return findings

    def _audit_cross(
        self,
        events: list[TimelineEvent],
        chapters: list[Chapter],
        runs: list[ExtractionRun],
    ) -> list[AuditFinding]:
        """跨维度规则 — R-X1 事件来源章节 + R-X2 提取 run 缺口（§5.5）.

        R-X1: 活动事件的 source_chapter_id 指向不存在的章节 → error（F2
        章节为硬删除、F14 FK ON DELETE SET NULL 在章节删除时应置 None——
        残留即异常数据，无软删分支）；None（手工事件）跳过。
        R-X2: run.status=error → warning「提取失败」（error 截断 ≤ 500 字符
        入 data）；活动章节 id 不在任何 run 的 source_key 中（str(id) 比对，
        source_key="manual" 不参与）→ info「从未执行过提取」。

        Args:
            events: 活动事件列表（TimelineService 视图 narrative_order）.
            chapters: 活动章节列表（分页循环全量，仅需 id 与 title）.
            runs: run 记录列表（分页循环全量，全部类型）.

        Returns:
            R-X1/R-X2 审计发现列表.
        """
        chapter_ids = {c.id for c in chapters}
        findings: list[AuditFinding] = []

        # R-X1 事件来源章节（§5.5: 悬空来源 → error，无软删分支）
        for event in events:
            if event.source_chapter_id is None:
                continue
            if event.source_chapter_id in chapter_ids:
                continue
            findings.append(
                AuditFinding(
                    id=f"timeline.source_chapter:{event.id}",
                    rule_id="timeline.source_chapter",
                    dimension=AuditDimension.CROSS,
                    severity=AuditSeverity.ERROR,
                    message=(
                        f"事件「{event.title}」的来源章节不存在（悬空来源；F2 章节"
                        "为硬删除，F14 FK ON DELETE SET NULL 在章节删除时应将"
                        "source_chapter_id 置 None——残留即异常数据）"
                    ),
                    entity_type="event",
                    entity_id=event.id,
                    entity_name=event.title,
                    ref_type="chapter",
                    ref_id=event.source_chapter_id,
                )
            )

        # R-X2 提取 run 缺口（§5.5: error run → warning + 从未提取章节 → info）
        for run in runs:
            if run.status == ExtractionStatus.ERROR:
                error_msg = (run.error or "")[:_RUN_ERROR_MAX_CHARS]
                findings.append(
                    AuditFinding(
                        id=f"extraction.run_gap:{run.source_key}",
                        rule_id="extraction.run_gap",
                        dimension=AuditDimension.CROSS,
                        severity=AuditSeverity.WARNING,
                        message=(
                            f"提取失败: [{run.type}] 源 {run.source_key} — "
                            f"{run.error or '未知错误'}（可重试）"
                        ),
                        entity_type="run",
                        entity_id=None,
                        entity_name=run.source_key,
                        data={
                            "status": run.status,
                            "error": error_msg,
                            "source_key": run.source_key,
                        },
                    )
                )
        covered = {r.source_key for r in runs if r.source_key != "manual"}
        for chapter in chapters:
            if str(chapter.id) not in covered:
                findings.append(
                    AuditFinding(
                        id=f"extraction.run_gap:{chapter.id}",
                        rule_id="extraction.run_gap",
                        dimension=AuditDimension.CROSS,
                        severity=AuditSeverity.INFO,
                        message=(
                            f"章节 {chapter.title} 从未执行过提取"
                            "（可运行 inkflow extract run 提取沉淀档案）"
                        ),
                        entity_type="chapter",
                        entity_id=chapter.id,
                        entity_name=chapter.title,
                    )
                )
        return findings

    # ── 汇总（spec §2.3/§6.2）─────────────────────────────────────

    def _summarize(self, findings: list[AuditFinding], counts: dict[str, int]) -> AuditSummary:
        """汇总审计结果 — by_dimension 计数 + counts 档案规模.

        consistent 仅由 error 级 findings 决定（§6.2）: 任一 error →
        consistent=False；warning/info 是提示不是错误，不影响。5 维度计数
        键全量初始化（含零值维度，保证 by_dimension 键齐全）。

        Args:
            findings: 全部规则产出的审计发现列表.
            counts: 档案规模观测（8 键: characters/relations/groups/
                world_settings/events/foreshadowings/chapters/extraction_runs）.

        Returns:
            AuditSummary 审计汇总.
        """
        by_dimension = {dim: DimensionSummary() for dim in AuditDimension}
        for finding in findings:
            summary = by_dimension[finding.dimension]
            if finding.severity is AuditSeverity.ERROR:
                summary.error += 1
            elif finding.severity is AuditSeverity.WARNING:
                summary.warning += 1
            else:
                summary.info += 1
        consistent = not any(f.severity is AuditSeverity.ERROR for f in findings)
        return AuditSummary(
            consistent=consistent,
            total=len(findings),
            by_dimension=by_dimension,
            counts=counts,
        )
