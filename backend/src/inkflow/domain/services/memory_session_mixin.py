"""#1098 会话事件源 mixin — 会话结论捕获 + 会话锚点 + 修改率统计口径.

2026-09-11 #1098：MemoryService 因新增「会话完成/失败 → memory 事件」捕获点
（record_session_completed / _session_anchors）与 stats 口径扩展超出 900 行
monster file 护栏，按 memory_supersede_mixin.py（#618 先例）把「会话事件源 +
修改率统计」这一内聚块整体拆出，行为零变化。

- record_session_completed: 会话终态结论落 memory_events（SESSION_COMPLETED），
  不做 difflib 偏好提取（会话结论无 before/after 对，spec §5.7.1）；
- _session_anchors: session_completed.after_content → 会话锚点（summarize 用）；
- stats: 修改率统计口径（chapters = confirmed + rejected + session_completed）。

混入类：self._event_repo / _preference_repo / _user_preference_repo /
is_learning_enabled 均由 MemoryService 提供（鸭子类型，domain/ 零框架 import）。
依据: specs/f28-memory-learning/spec.md §5.7/§5.7.1。
"""

from __future__ import annotations

import uuid

from inkflow.domain.models.memory_event import MemoryEvent, MemoryEventType
from inkflow.domain.services.preference_learner import SessionAnchor


def _session_conclusion_text(title: str, outcome: str) -> str:
    """会话标题 + 结论文本 → 可提取文本（#1098，spec §5.7.1）.

    两者均非空 → f"{title}\\n{outcome}"；单边非空 → 该边；皆空 → 空串
    （调用方跳过，after_content 不得为空串——锚点提取/diff_chars 依赖它）。

    Args:
        title: 会话标题.
        outcome: 结论文本（completed 用 result 摘要；failed 用失败原因）.

    Returns:
        可提取文本（可能为空串）.
    """
    clean_title = title.strip()
    clean_outcome = outcome.strip()
    if clean_title and clean_outcome:
        return f"{clean_title}\n{clean_outcome}"
    return clean_title or clean_outcome


class MemorySessionMixin:
    """会话事件源 + 修改率统计 mixin（字段/仓储/开关判定由 MemoryService 注入）."""

    async def record_session_completed(
        self,
        *,
        session_id: uuid.UUID,
        project_id: uuid.UUID,
        title: str,
        outcome: str = "",
        session_type: str = "",
    ) -> MemoryEvent | None:
        """记录一次会话终态产出（#1098，spec §5.7.1 会话事件源）.

        与 record_draft_edit 的差异: 会话结论不是「前后版本对照」（无
        before/after 对），故**不做** difflib 偏好提取——只落事件；事件本身
        供 stats.agentic.chapters 计数与 summarize 锚点提取使用（补齐
        「只有 agentic 会话、零写作草稿编辑」项目的空数据源）。

        捕获条件: memory_learning=true 且结论文本非空（§5.5 零行为延续）。

        Args:
            session_id: 会话领域 UUID（复用 draft_id 列承载字符串）.
            project_id: 所属项目 UUID.
            title: 会话标题.
            outcome: 结论文本（completed 用 result 摘要；failed 用失败原因）.
            session_type: 会话类型字符串（session_type.value，可空）.

        Returns:
            落库的 MemoryEvent；memory_learning=false 或结论文本为空
            → None（零行为）.
        """
        if not await self.is_learning_enabled(project_id):  # type: ignore[attr-defined]  # 混入类：方法由 Service 提供
            return None
        text = _session_conclusion_text(title, outcome)
        if not text:
            return None  # after_content 不得为空串（锚点提取/diff_chars 依赖）
        event: MemoryEvent = await self._event_repo.create(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            project_id=project_id,
            draft_id=str(session_id),
            chapter_id=None,
            agent_run_id=None,
            event_type=MemoryEventType.SESSION_COMPLETED,
            before_content=None,
            after_content=text,
        )
        return event

    async def _session_anchors(self, project_id: uuid.UUID) -> list[SessionAnchor]:
        """项目会话产出 → 会话锚点（#1098，spec §5.7.1 锚点扩展）.

        取该项目 session_completed 事件，每条事件的 after_content 生成一个
        锚点（供 SemanticSummarizer 的 anchor_values 与 learner.anchor_hash
        使用；SessionAnchor 只读 .value）。

        附加信号契约: 锚点扩展不得改变既有偏好锚点语义/顺序与哈希——event_repo
        未按契约返回 (list, total) 页元组（如未配置返回值的鸭子装配）→ 视为无
        会话锚点，空列表。

        Args:
            project_id: 所属项目 UUID.

        Returns:
            会话锚点列表（事件 created_at desc 顺序，即仓储返回序）.
        """
        page = await self._event_repo.list_by_project(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            project_id
        )
        events = page[0] if isinstance(page, tuple) else page
        if not isinstance(events, list):
            return []
        return [
            SessionAnchor(value=e.after_content)
            for e in events
            if getattr(e, "event_type", None) == MemoryEventType.SESSION_COMPLETED
            and e.after_content
        ]

    async def stats(self, project_id: uuid.UUID) -> dict:
        """修改率统计（spec §5.7 口径，测试锁定数学）.

        - chapters = confirmed + rejected + session_completed 事件数
          （agentic 章节总数口径；§5.7.1 会话产出计入）;
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
        events, _total = await self._event_repo.list_by_project(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            project_id
        )
        edited = [e for e in events if e.event_type == MemoryEventType.DRAFT_EDITED]
        confirmed = [e for e in events if e.event_type == MemoryEventType.DRAFT_CONFIRMED]
        rejected = [e for e in events if e.event_type == MemoryEventType.DRAFT_REJECTED]
        session_events = [e for e in events if e.event_type == MemoryEventType.SESSION_COMPLETED]
        chapters = len(confirmed) + len(rejected) + len(session_events)
        modify_rate = (chapters - len(confirmed)) / chapters if chapters else 0.0
        avg_diff_chars = int(sum(abs(e.diff_chars) for e in edited) / len(edited)) if edited else 0
        regenerate_rate = len(rejected) / chapters if chapters else 0.0
        learned_preferences = await self._preference_repo.count_by_project(  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
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
            "baseline_ref": "design/agent-baseline-2026-08-10.md",
        }
        if self._user_preference_repo is not None:  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            user_items, _user_total = await self._user_preference_repo.list_all()  # type: ignore[attr-defined]  # 混入类：属性由 Service 提供
            project_set: set[str] = set()
            for up in user_items:
                project_set.update(up.source_projects)
            result["user_preferences"] = {"count": len(user_items), "projects": len(project_set)}
        return result
