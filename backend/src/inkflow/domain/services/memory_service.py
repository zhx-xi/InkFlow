"""F28 记忆编排服务 — 事件捕获 / 偏好管理 / 统计查询（spec §5.1/§5.3/§5.6/§5.7）.

MemoryService 是偏好学习闭环的编排核心（调 repo 不碰 ORM，ADR-F 约束①同构）:
- record_draft_edit / record_draft_rejected / record_draft_confirmed: 用户行为
  事件捕获（memory_learning=false 时零行为——不落事件不提取不审计）;
- list_preferences / remove_preference: 偏好透明管理（删除即停止注入，无缓存）;
- get_preferences_for_injection: F6 PreferenceSource 注入读口（实时查库）;
- stats: 修改率统计（对照 F27 基线，spec §5.7）.
- remove_summaries: 删除项目级语义总结（幂等 + Q2=B 越闸，spec §3.3）.

依赖全部鸭子类型注入（preference_repo / event_repo / project_repo /
audit_service / learner），不感知 ORM/框架——domain/ 零框架 import 门禁
天然满足（ADR-002/015）。
依据: specs/f28-memory-learning/spec.md §5.1-§5.7/§9。
"""

from __future__ import annotations

import uuid

from inkflow.domain.models.memory_event import MemoryEvent, MemoryEventType
from inkflow.domain.models.preference import PreferenceCategory, ProjectPreference
from inkflow.domain.models.project import Project
from inkflow.domain.models.semantic_summary import SemanticSummary, SummaryScope
from inkflow.domain.models.user_preference import UserPreference
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.services import preference_learner
from inkflow.domain.services.memory_supersede_mixin import MemorySupersedeMixin
from inkflow.domain.services.preference_learner import (
    PreferenceCandidate,
    UserPreferenceCandidate,
)


def _score_pref(pref: object, active_watermark_now: float, half_life: float) -> float:
    """时间衰减动态分：score = count × 0.5^(Δt_active / half_life)."""
    # 鸭子类型：pref 按契约提供 active_watermark_at_last_access / count（测试用 SimpleNamespace）
    delta = active_watermark_now - float(getattr(pref, "active_watermark_at_last_access", 0.0))
    decay: float = 0.5 ** (delta / half_life)
    return int(getattr(pref, "count", 1)) * decay


def _dump_summary(summary: SemanticSummary | None) -> dict | None:
    """语义总结 → 可序列化字典（手动取字段——测试鸭子对象无 model_dump）."""
    if summary is None:
        return None
    return {
        "content": summary.content,
        "anchor_hash": summary.anchor_hash,
        "anchor_count": summary.anchor_count,
        "model": summary.model,
        "updated_at": summary.updated_at,
    }


class PreferenceNotFoundError(Exception):
    """偏好不存在（API 映射 404）。"""

    def __init__(self, message: str = "偏好不存在") -> None:
        super().__init__(message)


class MemoryService(MemorySupersedeMixin):
    """记忆编排服务（spec §5）— 事件捕获/偏好 CRUD/统计查询.

    Args:
        preference_repo: 偏好仓储（鸭子类型，需 list_by_project/get/create/
            update/delete/count_by_project）.
        event_repo: 事件仓储（鸭子类型，需 create/list_edited_by_project/
            list_by_project）.
        project_repo: 项目仓储（鸭子类型，需 get——读 memory_learning 开关，
            int 背书，F6 先例）.
        audit_service: F34 AuditLogService（记录偏好学习/删除动作，可空）.
        learner: 提取算法模块或等价对象（缺省 = preference_learner 模块本身，
           需 aggregate_candidates/confidence_for）.
        user_preference_repo: 用户级偏好仓储（鸭子类型，M1 用户级链，可空）.
        summary_repo: 语义总结仓储（鸭子类型，M2 get/upsert/delete_by_project，可空）.
        summarizer: 语义总结管线（鸭子类型，M2 summarize → (summary, dropped)，可空）.
        llm_default_model: LLM 默认模型名（M2 summarizer 传入，#415 唯一默认源，可空）.
        supersede_determiner: 偏好取代判定器（鸭子类型，F49 ② determine →
            (superseded_values, dropped)，可空；None = 未装配不判定，向后兼容）.
    """

    def __init__(
        self,
        *,
        preference_repo: object,
        event_repo: object,
        project_repo: object,
        audit_service: object | None = None,
        learner: object | None = None,
        user_preference_repo: object | None = None,
        summary_repo: object | None = None,
        summarizer: object | None = None,
        llm_default_model: str | None = None,
        supersede_determiner: object | None = None,
    ) -> None:
        self._preference_repo = preference_repo
        self._event_repo = event_repo
        self._project_repo = project_repo
        self._audit_service = audit_service
        self._learner = learner if learner is not None else preference_learner
        self._user_preference_repo = user_preference_repo
        self._summary_repo = summary_repo
        self._summarizer = summarizer
        self._llm_default_model = llm_default_model
        self._supersede_determiner = supersede_determiner
        self.last_learned: bool = False  # F28: 本次 record_draft_edit 是否触发新偏好落库

    async def is_learning_enabled(
        self, project_id: uuid.UUID, override: bool | None = None
    ) -> bool:
        """开关判定（spec §5.5 读取优先级: 请求显式 > extra 键 > 默认 False）.

        Args:
            project_id: 所属项目 UUID.
            override: 请求/CLI 显式覆盖（F13 同构）.

        Returns:
            True 表示开启记忆学习（开启才捕获事件/提取/注入）; 项目缺失 → False.
        """
        if override is not None:
            return override
        if project_id.int > 2**63 - 1:
            return False
        project: Project | None = await self._project_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：project_repo 按契约提供 get（int 背书，F6 先例）
            project_id.int
        )
        if project is None:
            return False
        return bool(project.config.extra.get("memory_learning", False))

    async def record_draft_edit(
        self,
        *,
        draft_id: str,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None = None,
        before: str,
        after: str,
        agent_run_id: str | None = None,
    ) -> MemoryEvent | None:
        """记录一次用户手动编辑草稿（spec §5.1 捕获点）.

        流程（memory_learning=true 时）:
        1) 事件落库（DRAFT_EDITED，字段展开形态，diff_chars 由 repo 层算）;
        2) 提取: 全量 edited 事件 → learner.aggregate_candidates;
        3) 落偏好: 候选 value 命中既有偏好 → update（count/confidence 重算、
           source_events 追加）；未命中且 count≥2 → create + 审计
           preference_learned；未命中且 count<2 → 跳过（阈值）;
        4) 返回落库事件.

        Args:
            draft_id: 关联草稿 id.
            project_id: 所属项目 UUID.
            chapter_id: 目标章节 UUID（可空）.
            before: 修改前草稿正文.
            after: 修改后草稿正文.
            agent_run_id: 来源 agent run id（可空）.

        Returns:
            落库的 MemoryEvent；memory_learning=false → None（零行为）.
        """
        self.last_learned = False  # F28: 每次调用重置，命中「未命中且 count>=2 → create」时置 True
        if not await self.is_learning_enabled(project_id):
            return None
        event: MemoryEvent = await self._event_repo.create(  # type: ignore[attr-defined]  # 鸭子类型：event_repo 按契约提供 create
            project_id=project_id,
            draft_id=draft_id,
            chapter_id=chapter_id,
            agent_run_id=agent_run_id,
            event_type=MemoryEventType.DRAFT_EDITED,
            before_content=before,
            after_content=after,
        )
        events: list[MemoryEvent] = await self._event_repo.list_edited_by_project(  # type: ignore[attr-defined]  # 鸭子类型：event_repo 按契约提供 list_edited_by_project
            project_id
        )
        candidates: list[PreferenceCandidate] = self._learner.aggregate_candidates(  # type: ignore[attr-defined]  # 鸭子类型：learner 按契约提供 aggregate_candidates
            events
        )
        if candidates:
            result: tuple[list[ProjectPreference], int]
            result = await self._preference_repo.list_by_project(  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约提供 list_by_project
                project_id
            )
            existing_items, _total = result
            existing_by_value = {p.value: p for p in existing_items}
            for candidate in candidates:
                existing = existing_by_value.get(candidate.value)
                if existing is not None:
                    await self._preference_repo.update(  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约提供 update
                        preference_id=existing.id,
                        count=candidate.count,
                        confidence=candidate.confidence,
                        source_events=[*existing.source_events, event.id],
                    )
                elif candidate.count >= 2:
                    await self._supersede_project_candidate(
                        candidate=candidate,
                        existing_items=existing_items,
                        existing_by_value=existing_by_value,
                        project_id=project_id,
                        event=event,
                    )
        # ── M1 用户级聚合链（spec §5.1）──
        if self._user_preference_repo is not None:
            all_edited: list[MemoryEvent] = await self._event_repo.list_all_edited()  # type: ignore[attr-defined]  # 鸭子类型：event_repo 按契约提供 list_all_edited（M1 新增）
            user_candidates: list[UserPreferenceCandidate] = (
                self._learner.aggregate_user_candidates(  # type: ignore[attr-defined]  # 鸭子类型：learner 按契约提供 aggregate_user_candidates
                    all_edited
                )
            )
            if user_candidates:
                user_result: tuple[list[UserPreference], int]
                user_result = await self._user_preference_repo.list_all()  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 list_all
                existing_user_items, _total = user_result
                existing_user_by_value = {p.value: p for p in existing_user_items}
                for uc in user_candidates:
                    existing_user = existing_user_by_value.get(uc.value)
                    if existing_user is not None:
                        await self._user_preference_repo.update(  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 update
                            existing_user.id,
                            count=uc.count,
                            confidence=uc.confidence,
                            project_count=uc.project_count,
                            source_projects=uc.source_projects,
                            source_events=uc.source_events,
                        )
                    elif uc.count >= 2 and uc.project_count >= 2:
                        await self._supersede_user_candidate(
                            uc=uc,
                            existing_user_items=existing_user_items,
                            existing_user_by_value=existing_user_by_value,
                            project_id=project_id,
                        )
        return event

    async def record_draft_rejected(
        self,
        *,
        draft_id: str,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None = None,
    ) -> MemoryEvent | None:
        """记录一次用户拒绝草稿（重新生成信号，spec §5.1 捕获点）.

        rejected 不参与偏好提取（spec §5.2），只贡献修改率统计（spec §5.7）;
        memory_learning=false → None（零行为）.

        Args:
            draft_id: 关联草稿 id.
            project_id: 所属项目 UUID.
            chapter_id: 目标章节 UUID（可空）.

        Returns:
            落库的 MemoryEvent；memory_learning=false → None.
        """
        if not await self.is_learning_enabled(project_id):
            return None
        event: MemoryEvent = await self._event_repo.create(  # type: ignore[attr-defined]  # 鸭子类型：event_repo 按契约提供 create
            project_id=project_id,
            draft_id=draft_id,
            chapter_id=chapter_id,
            event_type=MemoryEventType.DRAFT_REJECTED,
        )
        return event

    async def record_draft_confirmed(
        self,
        *,
        draft_id: str,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None = None,
    ) -> MemoryEvent | None:
        """记录一次用户直接确认草稿（未编辑，0 修改信号，spec §5.1 捕获点）.

        confirmed 不参与偏好提取（spec §5.2），只贡献修改率统计（spec §5.7）;
        memory_learning=false → None（零行为）.

        Args:
            draft_id: 关联草稿 id.
            project_id: 所属项目 UUID.
            chapter_id: 目标章节 UUID（可空）.

        Returns:
            落库的 MemoryEvent；memory_learning=false → None.
        """
        if not await self.is_learning_enabled(project_id):
            return None
        event: MemoryEvent = await self._event_repo.create(  # type: ignore[attr-defined]  # 鸭子类型：event_repo 按契约提供 create
            project_id=project_id,
            draft_id=draft_id,
            chapter_id=chapter_id,
            event_type=MemoryEventType.DRAFT_CONFIRMED,
        )
        return event

    async def list_preferences(
        self,
        project_id: uuid.UUID,
        category: PreferenceCategory | None = None,
    ) -> tuple[list[ProjectPreference], int]:
        """偏好列表（透传 preference_repo.list_by_project，spec §3.1）.

        Args:
            project_id: 所属项目 UUID.
            category: 分类过滤（不传 = 全部）.

        Returns:
            (items, total) 元组.
        """
        result: tuple[list[ProjectPreference], int]
        result = await self._preference_repo.list_by_project(  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约提供 list_by_project
            project_id, category=category
        )
        return result

    async def remove_preference(self, preference_id: str) -> ProjectPreference:
        """删除偏好（删除后立即停止注入——实时查库无缓存，spec §5.3）.

        Args:
            preference_id: 偏好 UUID 字符串.

        Returns:
            被删除的偏好（调用方用于回显）.

        Raises:
            PreferenceNotFoundError: 偏好不存在（404）.
        """
        preference: ProjectPreference | None = await self._preference_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约提供 get
            preference_id
        )
        if preference is None:
            raise PreferenceNotFoundError()
        await self._preference_repo.delete(preference_id)  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约提供 delete
        if self._audit_service is not None:
            await self._audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                project_id=preference.project_id,
                severity_summary="preference_removed",
                degraded=True,
                actor="memory",
            )
        return preference

    async def get_preferences_for_injection(self, project_id: uuid.UUID) -> list[ProjectPreference]:
        """已学偏好注入读口（F6 PreferenceSource 调用，spec §5.4/§5.3 F49）.
        memory_learning=false → []（零注入）；decay 关闭 → count desc（回归零影响）；
        decay 开启 → score desc + 过滤 score<0.05 + 注入即刷新水位（用即保鲜）；
        两个分支都排除 superseded_by != "" 的被取代偏好（F49 ②，contract §3.1）.
        """
        if not await self.is_learning_enabled(project_id):
            return []
        result: tuple[list[ProjectPreference], int]
        result = await self._preference_repo.list_by_project(  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约提供 list_by_project
            project_id
        )
        items, _total = result
        if project_id.int > 2**63 - 1:
            return []
        project: Project | None = await self._project_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：project_repo 按契约提供 get（int 背书，F6 先例）
            project_id.int
        )
        if project is None:
            return []
        config = project.config.extra
        if not config.get("memory_decay_enabled", False):
            # legacy：count desc（回归零影响，不读 active_watermark/不刷新）；
            # F49 ②: 注入排除被取代偏好（contract §3.1）
            return [
                p
                for p in sorted(items, key=lambda p: p.count, reverse=True)
                if getattr(p, "superseded_by", "") == ""
            ]
        half_life: float = float(config.get("memory_decay_half_life", 30))
        watermark_now: float = float(getattr(project, "active_watermark", 0.0))
        scored: list[tuple[ProjectPreference, float]] = []
        for pref in items:
            if getattr(pref, "superseded_by", "") != "":
                continue
            score = _score_pref(pref, watermark_now, half_life)
            if score >= 0.05:
                scored.append((pref, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        for pref, _score in scored:
            await self._bump_access_watermark(pref, watermark_now)
        return [pref for pref, _score in scored]

    async def _bump_access_watermark(self, pref: object, active_watermark_now: float) -> None:
        """写回偏好活跃水位（用即保鲜）：更新 pref 水位字段并经 repo 持久化."""
        pref.active_watermark_at_last_access = active_watermark_now  # type: ignore[attr-defined]  # 鸭子类型：pref 按契约提供可写水位字段
        await self._preference_repo.update(  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约提供 update
            pref.id,  # type: ignore[attr-defined]  # 鸭子类型：pref 按契约提供 id
            count=pref.count,  # type: ignore[attr-defined]  # 鸭子类型：pref 按契约提供 count
            confidence=pref.confidence,  # type: ignore[attr-defined]  # 鸭子类型：pref 按契约提供 confidence
            source_events=pref.source_events,  # type: ignore[attr-defined]  # 鸭子类型：pref 按契约提供 source_events
            active_watermark_at_last_access=active_watermark_now,
        )

    async def list_user_preferences(
        self,
        category: PreferenceCategory | None = None,
    ) -> tuple[list[UserPreference], int]:
        """用户级偏好列表 + 惰性重算（Q1=B，spec §7）.

        查全部用户级偏好（user_preference_repo.list_all(category=...)）；逐条
        检查 source_projects 中项目是否仍存在（project_repo.get(pid.int)）；
        已删项目 → source_projects 移除、project_count 减 1、update 写回；
        project_count < 2 → delete 该偏好（不返回）；返回过滤后的 (items,
        total)——total = 过滤/删除后的条数（= len(items)），user-list 不显示
        幽灵项目来源。

        Args:
            category: 分类过滤（不传 = 全部）.

        Returns:
            (items, total) 元组（total = len(items)）.
        """
        if self._user_preference_repo is None:
            return [], 0
        result: tuple[list[UserPreference], int]
        result = await self._user_preference_repo.list_all(  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 list_all
            category=category
        )
        items, _total = result
        kept: list[UserPreference] = []
        for pref in items:
            ghost: list[str] = []
            for pid_str in pref.source_projects:
                try:
                    pid = uuid.UUID(pid_str)
                except ValueError:
                    continue
                project = await self._project_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：project_repo 按契约提供 get（int 背书，F6 先例）
                    pid.int
                )
                if project is None:
                    ghost.append(pid_str)
            if not ghost:
                kept.append(pref)
                continue
            new_projects = [p for p in pref.source_projects if p not in ghost]
            new_project_count = pref.project_count - len(ghost)
            if new_project_count < 2:
                await self._user_preference_repo.delete(pref.id)  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 delete
                continue
            # update 返回刷新后的偏好；返回 None（鸭子 mock/契约宽松形态）时回退到
            # 本地重算对象，保证 user-list 不显示幽灵项目来源（Q1=B 契约语义）.
            pref.project_count = new_project_count
            pref.source_projects = new_projects
            updated = await self._user_preference_repo.update(  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 update
                pref.id,
                count=pref.count,
                confidence=pref.confidence,
                project_count=new_project_count,
                source_projects=new_projects,
                source_events=pref.source_events,
            )
            kept.append(updated if updated is not None else pref)
        return kept, len(kept)

    async def remove_user_preference(self, preference_id: str) -> UserPreference:
        """删除用户级偏好（删除后所有项目立即停止注入，spec §3.1）.

        Args:
            preference_id: 用户级偏好 UUID 字符串.

        Returns:
            被删除的用户级偏好（调用方用于回显）.

        Raises:
            PreferenceNotFoundError: 偏好不存在（404）.
        """
        if self._user_preference_repo is None:
            raise PreferenceNotFoundError()
        preference: UserPreference | None = await self._user_preference_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 get
            preference_id
        )
        if preference is None:
            raise PreferenceNotFoundError()
        await self._user_preference_repo.delete(preference_id)  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 delete
        if self._audit_service is not None:
            await self._audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                project_id=None,  # 用户级偏好跨项目无 project_id；F34 record 签名必填 → None
                severity_summary="user_preference_removed",
                degraded=True,
                actor="memory",
            )
        return preference

    async def create_preference(
        self,
        *,
        project_id: uuid.UUID,
        category: PreferenceCategory,
        pattern: str,
        value: str,
        confidence: float | None = None,
        count: int | None = None,
    ) -> ProjectPreference:
        """手动创建项目偏好（#521）：用户显式录入 → confidence/count 缺省 1.0/1.

        透传 repo.create（source_events=[]），返回落库偏好.
        """
        created: ProjectPreference = await self._preference_repo.create(  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约提供 create
            project_id=project_id,
            category=category,
            pattern=pattern,
            value=value,
            confidence=confidence if confidence is not None else 1.0,
            count=count if count is not None else 1,
            source_events=[],
        )
        return created

    async def create_user_preference(
        self,
        *,
        category: PreferenceCategory,
        pattern: str,
        value: str,
        confidence: float | None = None,
        count: int | None = None,
    ) -> UserPreference:
        """手动创建用户级偏好（#521）：缺省 confidence=1.0、count=1、project_count=1.

        透传 repo.create（source_projects/source_events=[]），返回落库偏好.
        """
        if self._user_preference_repo is None:
            raise PreferenceNotFoundError()
        created: UserPreference = await self._user_preference_repo.create(  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 create
            category=category,
            pattern=pattern,
            value=value,
            confidence=confidence if confidence is not None else 1.0,
            count=count if count is not None else 1,
            project_count=1,
            source_projects=[],
            source_events=[],
        )
        return created

    async def update_preference(
        self,
        preference_id: str,
        *,
        category: PreferenceCategory | None = None,
        pattern: str | None = None,
        value: str | None = None,
    ) -> ProjectPreference:
        """编辑项目偏好字段（#521）：get 缺失 → PreferenceNotFoundError.

        None 不覆盖由 repo 端处理；透传既有统计字段 + 编辑字段.
        """
        pref: ProjectPreference | None = await self._preference_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约提供 get
            preference_id
        )
        if pref is None:
            raise PreferenceNotFoundError()
        updated: ProjectPreference = await self._preference_repo.update(  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约提供 update
            preference_id,
            count=pref.count,
            confidence=pref.confidence,
            source_events=pref.source_events,
            category=category,
            pattern=pattern,
            value=value,
        )
        return updated

    async def update_user_preference(
        self,
        preference_id: str,
        *,
        category: PreferenceCategory | None = None,
        pattern: str | None = None,
        value: str | None = None,
    ) -> UserPreference:
        """编辑用户级偏好字段（#521）：repo 未装配/get 缺失 → PreferenceNotFoundError.

        None 不覆盖由 repo 端处理；透传既有统计字段 + 编辑字段.
        """
        if self._user_preference_repo is None:
            raise PreferenceNotFoundError()
        pref: UserPreference | None = await self._user_preference_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 get
            preference_id
        )
        if pref is None:
            raise PreferenceNotFoundError()
        updated: UserPreference = await self._user_preference_repo.update(  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 update
            preference_id,
            count=pref.count,
            confidence=pref.confidence,
            project_count=pref.project_count,
            source_projects=pref.source_projects,
            source_events=pref.source_events,
            category=category,
            pattern=pattern,
            value=value,
        )
        return updated

    async def get_user_preferences_for_injection(
        self, project_id: uuid.UUID
    ) -> list[UserPreference]:
        """用户级偏好注入读口（F6 PreferenceSource 调用，spec §5.6 M1/§5.3 F49）.
        memory_learning=false → []（零行为）；decay 关闭 → count desc（回归零影响）；
        decay 开启 → score desc + 过滤 score<0.05 + 注入即刷新水位（用户级同构）；
        全部分支都排除 superseded_by != "" 的被取代偏好（F49 ②，contract §3.1）.
        """
        if not await self.is_learning_enabled(project_id):
            return []
        items, _total = await self.list_user_preferences()
        if self._user_preference_repo is None:
            return [
                p
                for p in sorted(items, key=lambda p: p.count, reverse=True)
                if getattr(p, "superseded_by", "") == ""
            ]
        project: Project | None = await self._project_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：project_repo 按契约提供 get（int 背书，F6 先例）
            project_id.int
        )
        if project is None:
            return [
                p
                for p in sorted(items, key=lambda p: p.count, reverse=True)
                if getattr(p, "superseded_by", "") == ""
            ]
        config = project.config.extra
        if not config.get("memory_decay_enabled", False):
            return [
                p
                for p in sorted(items, key=lambda p: p.count, reverse=True)
                if getattr(p, "superseded_by", "") == ""
            ]
        half_life: float = float(config.get("memory_decay_half_life", 30))
        watermark_now: float = float(getattr(project, "active_watermark", 0.0))
        scored: list[tuple[UserPreference, float]] = []
        for pref in items:
            if getattr(pref, "superseded_by", "") != "":
                continue
            score = _score_pref(pref, watermark_now, half_life)
            if score >= 0.05:
                scored.append((pref, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        for pref, _score in scored:
            await self._bump_user_access_watermark(pref, watermark_now)
        return [pref for pref, _score in scored]

    async def _bump_user_access_watermark(self, pref: object, active_watermark_now: float) -> None:
        """写回用户级偏好活跃水位（用即保鲜）：更新 pref 水位字段并经 repo 持久化."""
        pref.active_watermark_at_last_access = active_watermark_now  # type: ignore[attr-defined]  # 鸭子类型：pref 按契约提供可写水位字段
        await self._user_preference_repo.update(  # type: ignore[union-attr]  # 鸭子类型：user_preference_repo 按契约提供 update（object|None 未收窄）
            pref.id,  # type: ignore[attr-defined]  # 鸭子类型：pref 按契约提供 id
            count=pref.count,  # type: ignore[attr-defined]  # 鸭子类型：pref 按契约提供 count
            confidence=pref.confidence,  # type: ignore[attr-defined]  # 鸭子类型：pref 按契约提供 confidence
            project_count=pref.project_count,  # type: ignore[attr-defined]  # 鸭子类型：pref 按契约提供 project_count
            source_projects=pref.source_projects,  # type: ignore[attr-defined]  # 鸭子类型：pref 按契约提供 source_projects
            source_events=pref.source_events,  # type: ignore[attr-defined]  # 鸭子类型：pref 按契约提供 source_events
            active_watermark_at_last_access=active_watermark_now,
        )

    async def stats(self, project_id: uuid.UUID) -> dict:
        """修改率统计（spec §5.7 口径，测试锁定数学）.

        - chapters = confirmed + rejected 事件数（agentic 章节总数口径）;
        - direct_confirms = confirmed 数; modify_rate = (chapters - confirmed)
          / chapters（chapters=0 → 0.0）;
        - avg_diff_chars = Σ|diff_chars| / edited 数（无 edited → 0）;
        - regenerate_rate = rejected / chapters（无章节 → 0.0）;
        - learned_preferences = 库中偏好总数; baseline_ref 引用 F27 基线文档.

        Args:
            project_id: 所属项目 UUID.

        Returns:
            统计字典（project_id / agentic / learned_preferences / baseline_ref）.
        """
        events, _total = await self._event_repo.list_by_project(  # type: ignore[attr-defined]  # 鸭子类型：event_repo 按契约返回 (list, total) 元组
            project_id
        )
        edited = [e for e in events if e.event_type == MemoryEventType.DRAFT_EDITED]
        confirmed = [e for e in events if e.event_type == MemoryEventType.DRAFT_CONFIRMED]
        rejected = [e for e in events if e.event_type == MemoryEventType.DRAFT_REJECTED]
        chapters = len(confirmed) + len(rejected)
        modify_rate = (chapters - len(confirmed)) / chapters if chapters else 0.0
        avg_diff_chars = int(sum(abs(e.diff_chars) for e in edited) / len(edited)) if edited else 0
        regenerate_rate = len(rejected) / chapters if chapters else 0.0
        learned_preferences = await self._preference_repo.count_by_project(  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约提供 count_by_project
            project_id
        )
        result = {
            "project_id": str(project_id),
            "agentic": {
                "chapters": chapters,
                "direct_confirms": len(confirmed),
                "avg_diff_chars": avg_diff_chars,
                "modify_rate": modify_rate,
                "regenerate_rate": regenerate_rate,
            },
            "learned_preferences": learned_preferences,
            "baseline_ref": "docs/agent-baseline-2026-08-10.md",
        }
        if self._user_preference_repo is not None:
            user_items, _user_total = await self._user_preference_repo.list_all()  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 list_all
            project_set: set[str] = set()
            for up in user_items:
                project_set.update(up.source_projects)
            result["user_preferences"] = {"count": len(user_items), "projects": len(project_set)}
        return result

    async def get_summaries(self, project_id: uuid.UUID) -> dict:
        """查询已落库的语义总结（项目级 + 用户级，spec §3.2/§5.4）.

        零行为（spec §7 边界表）: 项目缺失 → delete_by_project 清理 + 空结构;
        memory_learning=false / summary_repo 未注入 → 空结构（不查 summary_repo）;
        用户级 = 全局记录（scope=user, project_id=None，spec §5.3 全局单一性）.
        """
        if project_id.int > 2**63 - 1:
            return {"project_id": str(project_id), "project": None, "user": None}
        project: Project | None = await self._project_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：project_repo 按契约提供 get（int 背书，F6 先例）
            project_id.int
        )
        if project is None:
            if self._summary_repo is not None:
                await self._summary_repo.delete_by_project(project_id)  # type: ignore[attr-defined]  # 鸭子类型：summary_repo 按契约提供 delete_by_project
            return {"project_id": str(project_id), "project": None, "user": None}
        if not project.config.extra.get("memory_learning"):
            return {"project_id": str(project_id), "project": None, "user": None}
        if self._summary_repo is None:
            return {"project_id": str(project_id), "project": None, "user": None}
        project_summary: SemanticSummary | None
        project_summary = await self._summary_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：summary_repo 按契约提供 get
            scope=SummaryScope.PROJECT, project_id=project_id
        )
        user_summary: SemanticSummary | None
        user_summary = await self._summary_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：summary_repo 按契约提供 get
            scope=SummaryScope.USER, project_id=None
        )
        return {
            "project_id": str(project_id),
            "project": _dump_summary(project_summary),
            "user": _dump_summary(user_summary),
        }

    async def summarize(self, project_id: uuid.UUID, *, force: bool = False) -> dict:
        """触发/复用语义总结（spec §3.2/§5.3/§5.4 幂等 + §5.7 审计）.

        流程: 项目缺失 → delete_by_project 清理 + summarized=False 空结构;
        memory_learning=false 或 summary_repo/summarizer 未注入 → 空结构;
        每层（项目级先、用户级后）: 锚点哈希相同且非 force → 复用；否则
        summarizer.summarize → dropped 审计 failed / summary 非 None → upsert +
        审计 generated（degraded=True, actor="memory"）; 用户级锚点 = 全局
        user_preferences（project_id=None，与调用项目无关，spec §5.3）.

        Returns: {"project_id", "summarized", "project"|None, "user"|None}.
        """
        if project_id.int > 2**63 - 1:
            return {"project_id": str(project_id), "summarized": False,
                    "project": None, "user": None}
        project: Project | None = await self._project_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：project_repo 按契约提供 get（int 背书，F6 先例）
            project_id.int
        )
        if project is None:
            if self._summary_repo is not None:
                await self._summary_repo.delete_by_project(project_id)  # type: ignore[attr-defined]  # 鸭子类型：summary_repo 按契约提供 delete_by_project
            return {
                "project_id": str(project_id),
                "summarized": False,
                "project": None,
                "user": None,
            }
        if not project.config.extra.get("memory_learning"):
            return {
                "project_id": str(project_id),
                "summarized": False,
                "project": None,
                "user": None,
            }
        if self._summary_repo is None or self._summarizer is None:
            return {
                "project_id": str(project_id),
                "summarized": False,
                "project": None,
                "user": None,
            }

        # ── 项目级层（spec §5.4 幂等: hash 相同且非 force → 复用不调 LLM）──
        anchors, _total = await self._preference_repo.list_by_project(  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约返回 (list, total) 元组
            project_id
        )
        cur_hash = self._learner.anchor_hash(anchors)  # type: ignore[attr-defined]  # 鸭子类型：learner 按契约提供 anchor_hash
        existing: SemanticSummary | None = await self._summary_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：summary_repo 按契约提供 get
            scope=SummaryScope.PROJECT, project_id=project_id
        )
        project_result: SemanticSummary | None
        project_llm_called = False
        if existing is not None and existing.anchor_hash == cur_hash and not force:
            project_result = existing
        else:
            summary: SemanticSummary | None
            summary, dropped = await self._summarizer.summarize(  # type: ignore[attr-defined]  # 鸭子类型：summarizer 按契约提供 summarize
                anchors,
                scope=SummaryScope.PROJECT,
                project_id=project_id,
                anchor_hash=cur_hash,
                model=self._llm_default_model,
            )
            if dropped and self._audit_service is not None:
                await self._audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                    project_id=project_id,
                    severity_summary="semantic_summary_failed",
                    degraded=True,
                    actor="memory",
                    note=f"防幻觉校验丢弃 {dropped} 条",
                )
            if summary is not None:
                await self._summary_repo.upsert(summary)  # type: ignore[attr-defined]  # 鸭子类型：summary_repo 按契约提供 upsert
                if self._audit_service is not None:
                    await self._audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        project_id=project_id,
                        severity_summary="semantic_summary_generated",
                        degraded=True,
                        actor="memory",
                    )
                project_result = summary
                project_llm_called = True
            else:
                project_result = None

        # ── 用户级层（同构；user_preference_repo 未注入时跳过）──
        user_result: SemanticSummary | None = None
        user_llm_called = False
        if self._user_preference_repo is not None:
            user_anchors, _user_total = await self._user_preference_repo.list_all()  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约返回 (list, total) 元组
            user_hash = self._learner.anchor_hash(user_anchors)  # type: ignore[attr-defined]  # 鸭子类型：learner 按契约提供 anchor_hash
            user_existing: SemanticSummary | None = await self._summary_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：summary_repo 按契约提供 get
                scope=SummaryScope.USER, project_id=None
            )
            if user_existing is not None and user_existing.anchor_hash == user_hash and not force:
                user_result = user_existing
            else:
                user_summary: SemanticSummary | None
                user_summary, user_dropped = await self._summarizer.summarize(  # type: ignore[attr-defined]  # 鸭子类型：summarizer 按契约提供 summarize
                    user_anchors,
                    scope=SummaryScope.USER,
                    project_id=None,
                    anchor_hash=user_hash,
                    model=self._llm_default_model,
                )
                if user_dropped and self._audit_service is not None:
                    # 用户级总结跨项目无 project_id → None（M1 remove_user_preference 先例）
                    await self._audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                        project_id=None,
                        severity_summary="semantic_summary_failed",
                        degraded=True,
                        actor="memory",
                        note=f"防幻觉校验丢弃 {user_dropped} 条",
                    )
                if user_summary is not None:
                    await self._summary_repo.upsert(user_summary)  # type: ignore[attr-defined]  # 鸭子类型：summary_repo 按契约提供 upsert
                    if self._audit_service is not None:
                        # 用户级总结跨项目无 project_id → None（M1 remove_user_preference 先例）
                        await self._audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                            project_id=None,
                            severity_summary="semantic_summary_generated",
                            degraded=True,
                            actor="memory",
                        )
                    user_result = user_summary
                    user_llm_called = True
                else:
                    user_result = None

        return {
            "project_id": str(project_id),
            "summarized": project_llm_called or user_llm_called,
            "project": _dump_summary(project_result),
            "user": _dump_summary(user_result),
        }

    async def remove_summaries(self, project_id: uuid.UUID) -> dict:
        """删除项目级语义总结（幂等 + Q2=B 越闸）.

        - 项目缺失 → ProjectNotFoundError;
        - 幂等：summary 不存在（delete_by_project 返回 0）→ 仍返回 deleted:True;
        - memory_learning=false 仍可删（Q2=B，不检查开关）。
        """
        if project_id.int > 2**63 - 1:
            raise ProjectNotFoundError()
        project: Project | None = await self._project_repo.get(  # type: ignore[attr-defined]  # 鸭子类型：project_repo 按契约提供 get（int 背书，F6 先例）
            project_id.int
        )
        if project is None:
            raise ProjectNotFoundError()
        if self._summary_repo is not None:
            await self._summary_repo.delete_by_project(project_id)  # type: ignore[attr-defined]  # 鸭子类型：summary_repo 按契约提供 delete_by_project
        return {"project_id": str(project_id), "deleted": True}
