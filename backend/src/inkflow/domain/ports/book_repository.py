"""书级编排仓储端口 - WritingPlan / PlannerSession 持久化契约.

BookRepositoryProtocol 定义 WritingPlan 与 PlannerSession 的
增/查/改操作；基础设施层（SQLite / mock / memory）实现该 Protocol.
get_writing_plan / get_planner_session 入参接受 uuid.UUID 或 str
（repo 实现负责字符串转换查询）.

依据: specs/f44-long-task-orchestrator/spec.md 搂2.1/搂2.2/搂4.3.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.models.writing_plan import WritingPlan


class BookRepositoryProtocol(Protocol):
    """书级编排仓储端口.

    WritingPlan / PlannerSession 的 CRUD 契约：add 返回持久化后的实体，
    get 未命中返回 None，update 无返回值.
    """

    # ─── WritingPlan ───

    async def add_writing_plan(self, plan: WritingPlan) -> WritingPlan:
        """插入新的书级计划.

        Args:
            plan: 待持久化的 WritingPlan（id 为领域 UUID）.

        Returns:
            持久化后的 WritingPlan.
        """
        ...

    async def get_writing_plan(self, plan_id: uuid.UUID | str) -> WritingPlan | None:
        """按 id 查询书级计划.

        Args:
            plan_id: 计划 UUID（也接受字符串，repo 实现负责转换查询）.

        Returns:
            命中则返回 WritingPlan，否则返回 None.
        """
        ...

    async def update_writing_plan(self, plan: WritingPlan) -> None:
        """更新书级计划（按 id 定位）.

        Args:
            plan: 含待更新字段的完整 WritingPlan 对象.
        """
        ...

    # ─── PlannerSession ───

    async def add_planner_session(self, session: PlannerSession) -> PlannerSession:
        """插入新的访谈会话.

        Args:
            session: 待持久化的 PlannerSession（id 为领域 UUID）.

        Returns:
            持久化后的 PlannerSession.
        """
        ...

    async def get_planner_session(self, session_id: uuid.UUID | str) -> PlannerSession | None:
        """按 id 查询访谈会话.

        Args:
            session_id: 会话 UUID（也接受字符串，repo 实现负责转换查询）.

        Returns:
            命中则返回 PlannerSession，否则返回 None.
        """
        ...

    async def update_planner_session(self, session: PlannerSession) -> None:
        """更新访谈会话（按 id 定位）.

        Args:
            session: 含待更新字段的完整 PlannerSession 对象.
        """
        ...
