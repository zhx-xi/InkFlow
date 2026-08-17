"""F28 记忆编排服务 — 事件捕获 / 偏好管理 / 统计查询（spec §5.1/§5.3/§5.6/§5.7）.

MemoryService 是偏好学习闭环的编排核心（调 repo 不碰 ORM，ADR-F 约束①同构）:
- record_draft_edit / record_draft_rejected / record_draft_confirmed: 用户行为
  事件捕获（memory_learning=false 时零行为——不落事件不提取不审计）;
- list_preferences / remove_preference: 偏好透明管理（删除即停止注入，无缓存）;
- get_preferences_for_injection: F6 PreferenceSource 注入读口（实时查库）;
- stats: 修改率统计（对照 F27 基线，spec §5.7）.

依赖全部鸭子类型注入（preference_repo / event_repo / project_repo /
audit_service / learner），不感知 ORM/框架——domain/ 零框架 import 门禁
天然满足（ADR-002/015）。
依据: specs/f28-agent-memory/spec.md §5.1-§5.7/§9。
"""

from __future__ import annotations

import uuid

from inkflow.domain.models.memory_event import MemoryEvent, MemoryEventType
from inkflow.domain.models.preference import PreferenceCategory, ProjectPreference
from inkflow.domain.models.project import Project
from inkflow.domain.models.user_preference import UserPreference
from inkflow.domain.services import preference_learner
from inkflow.domain.services.preference_learner import (
    PreferenceCandidate,
    UserPreferenceCandidate,
)


class PreferenceNotFoundError(Exception):
    """偏好不存在（API 映射 404）。"""

    def __init__(self, message: str = "偏好不存在") -> None:
        super().__init__(message)


class MemoryService:
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
    ) -> None:
        self._preference_repo = preference_repo
        self._event_repo = event_repo
        self._project_repo = project_repo
        self._audit_service = audit_service
        self._learner = learner if learner is not None else preference_learner
        self._user_preference_repo = user_preference_repo
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
                    await self._preference_repo.create(  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约提供 create
                        project_id=project_id,
                        category=candidate.category,
                        pattern=candidate.pattern,
                        value=candidate.value,
                        confidence=candidate.confidence,
                        count=candidate.count,
                        source_events=[event.id],
                    )
                    self.last_learned = True  # F28: 新偏好落库 → 本次编辑触发学习
                    if self._audit_service is not None:
                        await self._audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                            project_id=project_id,
                            severity_summary="preference_learned",
                            degraded=True,
                            actor="memory",
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
                        await self._user_preference_repo.create(  # type: ignore[attr-defined]  # 鸭子类型：user_preference_repo 按契约提供 create
                            category=uc.category,
                            pattern=uc.pattern,
                            value=uc.value,
                            confidence=uc.confidence,
                            count=uc.count,
                            project_count=uc.project_count,
                            source_projects=uc.source_projects,
                            source_events=uc.source_events,
                        )
                        if self._audit_service is not None:
                            await self._audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
                                project_id=project_id,
                                severity_summary="user_preference_learned",
                                degraded=True,
                                actor="memory",
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
        """已学偏好注入读口（F6 PreferenceSource 调用，spec §5.4）.

        memory_learning=false → []（零注入）; true → 实时查库（无缓存），
        按 count desc 排序返回——删除偏好后下次生成立即生效（验收判据③）.

        Args:
            project_id: 所属项目 UUID.

        Returns:
            按支撑强度（count desc）排序的偏好列表.
        """
        if not await self.is_learning_enabled(project_id):
            return []
        result: tuple[list[ProjectPreference], int]
        result = await self._preference_repo.list_by_project(  # type: ignore[attr-defined]  # 鸭子类型：preference_repo 按契约提供 list_by_project
            project_id
        )
        items, _total = result
        return sorted(items, key=lambda p: p.count, reverse=True)

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

    async def get_user_preferences_for_injection(
        self, project_id: uuid.UUID
    ) -> list[UserPreference]:
        """用户级偏好注入读口（F6 PreferenceSource 调用，spec §5.6 M1）.

        memory_learning=false → []（零行为）；true → 惰性重算后返回 items
        （count desc 排序）。

        Args:
            project_id: 所属项目 UUID（开关判定用）.

        Returns:
            按支撑强度（count desc）排序的用户级偏好列表.
        """
        if not await self.is_learning_enabled(project_id):
            return []
        items, _total = await self.list_user_preferences()
        return sorted(items, key=lambda p: p.count, reverse=True)

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
