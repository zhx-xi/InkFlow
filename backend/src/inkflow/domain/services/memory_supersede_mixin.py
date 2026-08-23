"""F49 ② 显式覆盖 mixin — 从 MemoryService 拆出的 LLM 判定取代逻辑（控制文件行数）.

2018-08-24 #618：MemoryService 因 record_draft_edit 内联两段（项目级+用户级）
LLM 判定取代逻辑超 900 行护栏，按 fix-010 mixin 抽取先例拆出。行为零变化：
- determine → 标记 superseded_by → create → audit；LLM 判定失败（SupersedeDeterminationError）
  → 审计 semantic_summary_failed + 该候选不 create（宁少勿误，Q3=A）。
- 混入类：self._supersede_determiner / _preference_repo / _user_preference_repo /
  _audit_service / _llm_default_model / last_learned 均由 MemoryService 提供。
"""
from __future__ import annotations

from inkflow.domain.ports.preference_supersede_errors import SupersedeDeterminationError


class MemorySupersedeMixin:
    """LLM 判定取代 mixin（字段/仓储由 MemoryService 注入）."""

    async def _supersede_project_candidate(
        self,
        *,
        candidate: object,
        existing_items: list,
        existing_by_value: dict,
        project_id: object,
        event: object,
    ) -> None:
        """项目级：新候选落库前判定取代（contract §3.2）— 失败则不创建该候选."""
        superseded_values: list[str] = []
        dropped = 0
        if existing_items and self._supersede_determiner is not None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            try:
                determination: tuple[list[str], int]
                determination = await self._supersede_determiner.determine(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                    candidate.value,  # type: ignore[attr-defined]  # 鸭子类型：candidate 按契约提供 value
                    existing_items,
                    model=self._llm_default_model,  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                )
                superseded_values, dropped = determination
            except SupersedeDeterminationError:
                if self._audit_service is not None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                    await self._audit_service.record(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                        project_id=project_id,
                        severity_summary="semantic_summary_failed",
                        degraded=True,
                        actor="memory",
                        note="LLM 判定失败",
                    )
                return  # 该候选不创建（待判定，宁少勿误）
        if dropped > 0 and self._audit_service is not None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            await self._audit_service.record(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                project_id=project_id,
                severity_summary="semantic_summary_failed",
                degraded=True,
                actor="memory",
                note=f"防幻觉校验丢弃 {dropped} 条",
            )
        for value in superseded_values:
            old = existing_by_value.get(value)
            if old is not None:
                await self._preference_repo.update(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                    preference_id=old.id,
                    count=old.count,
                    confidence=old.confidence,
                    source_events=old.source_events,
                    superseded_by=candidate.value,  # type: ignore[attr-defined]  # 鸭子类型：candidate 按契约提供 value
                )
        await self._preference_repo.create(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            project_id=project_id,
            category=candidate.category,  # type: ignore[attr-defined]  # 鸭子类型：candidate 按契约提供 category
            pattern=candidate.pattern,  # type: ignore[attr-defined]  # 鸭子类型：candidate 按契约提供 pattern
            value=candidate.value,  # type: ignore[attr-defined]  # 鸭子类型：candidate 按契约提供 value
            confidence=candidate.confidence,  # type: ignore[attr-defined]  # 鸭子类型：candidate 按契约提供 confidence
            count=candidate.count,  # type: ignore[attr-defined]  # 鸭子类型：candidate 按契约提供 count
            source_events=[event.id],  # type: ignore[attr-defined]  # 鸭子类型：event 按契约提供 id
        )
        self.last_learned = True
        if self._audit_service is not None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            await self._audit_service.record(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                project_id=project_id,
                severity_summary="preference_learned",
                degraded=True,
                actor="memory",
            )

    async def _supersede_user_candidate(
        self,
        *,
        uc: object,
        existing_user_items: list,
        existing_user_by_value: dict,
        project_id: object,
    ) -> None:
        """用户级：新候选落库前判定取代（contract §3.2）— 失败则不创建该候选."""
        user_superseded_values: list[str] = []
        user_dropped = 0
        if existing_user_items and self._supersede_determiner is not None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            try:
                user_determination: tuple[list[str], int]
                user_determination = await self._supersede_determiner.determine(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                    uc.value,  # type: ignore[attr-defined]  # 鸭子类型：uc 按契约提供 value
                    existing_user_items,
                    model=self._llm_default_model,  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                )
                user_superseded_values, user_dropped = user_determination
            except SupersedeDeterminationError:
                if self._audit_service is not None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                    await self._audit_service.record(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                        project_id=project_id,
                        severity_summary="semantic_summary_failed",
                        degraded=True,
                        actor="memory",
                        note="LLM 判定失败",
                    )
                return  # 该候选不创建（待判定，宁少勿误）
        if user_dropped > 0 and self._audit_service is not None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            await self._audit_service.record(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                project_id=project_id,
                severity_summary="semantic_summary_failed",
                degraded=True,
                actor="memory",
                note=f"防幻觉校验丢弃 {user_dropped} 条",
            )
        for value in user_superseded_values:
            old_user = existing_user_by_value.get(value)
            if old_user is not None:
                await self._user_preference_repo.update(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                    preference_id=old_user.id,
                    count=old_user.count,
                    confidence=old_user.confidence,
                    project_count=old_user.project_count,
                    source_projects=old_user.source_projects,
                    source_events=old_user.source_events,
                    superseded_by=uc.value,  # type: ignore[attr-defined]  # 鸭子类型：uc 按契约提供 value
                )
        await self._user_preference_repo.create(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            category=uc.category,  # type: ignore[attr-defined]  # 鸭子类型：uc 按契约提供 category
            pattern=uc.pattern,  # type: ignore[attr-defined]  # 鸭子类型：uc 按契约提供 pattern
            value=uc.value,  # type: ignore[attr-defined]  # 鸭子类型：uc 按契约提供 value
            confidence=uc.confidence,  # type: ignore[attr-defined]  # 鸭子类型：uc 按契约提供 confidence
            count=uc.count,  # type: ignore[attr-defined]  # 鸭子类型：uc 按契约提供 count
            project_count=uc.project_count,  # type: ignore[attr-defined]  # 鸭子类型：uc 按契约提供 project_count
            source_projects=uc.source_projects,  # type: ignore[attr-defined]  # 鸭子类型：uc 按契约提供 source_projects
            source_events=uc.source_events,  # type: ignore[attr-defined]  # 鸭子类型：uc 按契约提供 source_events
        )
        if self._audit_service is not None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            await self._audit_service.record(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
                project_id=project_id,
                severity_summary="user_preference_learned",
                degraded=True,
                actor="memory",
            )
