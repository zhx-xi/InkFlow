"""F44 书级编排 SQLite 仓储 - WritingPlan / PlannerSession 持久化实现.

转换函数（_orm_to_domain / _domain_to_orm）按项目惯例放在本仓储层
（参照 foreshadowing_repo.py / agent_run_repo.py）.

语义（spec §2.1/§2.2/§8.1，父侧外线 test_book_repository.py docstring）：
- add: 插入领域实体（id 为领域 UUID 字符串化落库），单次 commit，refresh 后
  经 _orm_to_domain 返回持久化实体（时间戳回填）
- get: 按 id（uuid.UUID 或 str）查询，内部 str(plan_id) 归一化为字符串查询
- update: 按 id 定位 ORM 行，全字段覆写回写（含 updated_at），commit；
  查无 → no-op
- 领域 UUID → uuid4 字符串转换在仓储层（project_id/root_outline_id/
  character_ids/writing_plan_id 等列存 str(uuid)）
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.models.writing_plan import WritingPlan
from inkflow.infrastructure.database.models.planner_session import PlannerSessionORM
from inkflow.infrastructure.database.models.writing_plan import WritingPlanORM


def _writing_plan_orm_to_domain(orm: WritingPlanORM) -> WritingPlan:
    """WritingPlan ORM 行 → 领域实体（uuid 字符串 → UUID，JSON 列 → dict/list）."""
    return WritingPlan(
        id=uuid.UUID(orm.id),
        project_id=uuid.UUID(orm.project_id),
        title=orm.title,
        status=orm.status,
        root_outline_id=(
            uuid.UUID(orm.root_outline_id) if orm.root_outline_id is not None else None
        ),
        character_ids=[uuid.UUID(c) for c in (orm.character_ids or [])],
        limits=orm.limits or {},
        progress=orm.progress or {},
        execution_refs=orm.execution_refs or {},
        thread_id=orm.thread_id,
        hitl_payload=orm.hitl_payload,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _planner_session_orm_to_domain(orm: PlannerSessionORM) -> PlannerSession:
    """PlannerSession ORM 行 → 领域实体（uuid 字符串 → UUID，JSON 列 → dict/list）."""
    return PlannerSession(
        id=uuid.UUID(orm.id),
        project_id=uuid.UUID(orm.project_id),
        status=orm.status,
        one_liner=orm.one_liner,
        round=orm.round,
        asked_questions=orm.asked_questions or [],
        answers=orm.answers or {},
        authorized=orm.authorized or [],
        writing_plan_id=(
            uuid.UUID(orm.writing_plan_id) if orm.writing_plan_id is not None else None
        ),
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _domain_to_writing_plan_orm(plan: WritingPlan) -> WritingPlanORM:
    """领域 WritingPlan → ORM 行（UUID → str，dict/list 直接给 LenientJSON 列）."""
    return WritingPlanORM(
        id=str(plan.id),
        project_id=str(plan.project_id),
        title=plan.title,
        status=plan.status,
        root_outline_id=(str(plan.root_outline_id) if plan.root_outline_id is not None else None),
        character_ids=[str(c) for c in plan.character_ids],
        limits=plan.limits,
        progress=plan.progress,
        execution_refs=plan.execution_refs,
        thread_id=plan.thread_id,
        hitl_payload=plan.hitl_payload,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def _domain_to_planner_session_orm(session: PlannerSession) -> PlannerSessionORM:
    """领域 PlannerSession → ORM 行（UUID → str，dict/list 直接给 LenientJSON 列）."""
    return PlannerSessionORM(
        id=str(session.id),
        project_id=str(session.project_id),
        status=session.status,
        one_liner=session.one_liner,
        round=session.round,
        asked_questions=session.asked_questions,
        answers=session.answers,
        authorized=session.authorized,
        writing_plan_id=(
            str(session.writing_plan_id) if session.writing_plan_id is not None else None
        ),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


class SQLiteBookRepository:
    """SQLite 书级编排仓储（session 注入，镜像 agent_run_repo 模式）."""

    def __init__(self, db_session: AsyncSession) -> None:
        """以异步会话构造仓储（注入方式与既有仓储一致）."""
        self._session = db_session

    # ---- WritingPlan ----

    async def add_writing_plan(self, plan: WritingPlan) -> WritingPlan:
        """插入新的书级计划，返回持久化后的 WritingPlan（时间戳回填）."""
        orm = _domain_to_writing_plan_orm(plan)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _writing_plan_orm_to_domain(orm)

    async def get_writing_plan(self, plan_id: uuid.UUID | str) -> WritingPlan | None:
        """按 id 查询书级计划（uuid.UUID 或 str，内部归一化为字符串查询）."""
        stmt = select(WritingPlanORM).where(WritingPlanORM.id == str(plan_id))
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _writing_plan_orm_to_domain(orm) if orm else None

    async def update_writing_plan(self, plan: WritingPlan) -> None:
        """按 id 更新书级计划（全字段覆写，含 updated_at；查无 → no-op）."""
        stmt = select(WritingPlanORM).where(WritingPlanORM.id == str(plan.id))
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return
        orm.status = plan.status
        orm.root_outline_id = (
            str(plan.root_outline_id) if plan.root_outline_id is not None else None
        )
        orm.character_ids = [str(c) for c in plan.character_ids]
        orm.limits = plan.limits
        orm.progress = plan.progress
        orm.execution_refs = plan.execution_refs
        orm.thread_id = plan.thread_id
        orm.hitl_payload = plan.hitl_payload
        orm.updated_at = plan.updated_at
        await self._session.commit()

    # ---- PlannerSession ----

    async def add_planner_session(self, session: PlannerSession) -> PlannerSession:
        """插入新的访谈会话，返回持久化后的 PlannerSession（时间戳回填）."""
        orm = _domain_to_planner_session_orm(session)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _planner_session_orm_to_domain(orm)

    async def get_planner_session(
        self,
        session_id: uuid.UUID | str,
    ) -> PlannerSession | None:
        """按 id 查询访谈会话（uuid.UUID 或 str，内部归一化为字符串查询）."""
        stmt = select(PlannerSessionORM).where(PlannerSessionORM.id == str(session_id))
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _planner_session_orm_to_domain(orm) if orm else None

    async def update_planner_session(self, session: PlannerSession) -> None:
        """按 id 更新访谈会话（全字段覆写，含 updated_at；查无 → no-op）."""
        stmt = select(PlannerSessionORM).where(PlannerSessionORM.id == str(session.id))
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return
        orm.status = session.status
        orm.round = session.round
        orm.asked_questions = session.asked_questions
        orm.answers = session.answers
        orm.authorized = session.authorized
        orm.writing_plan_id = (
            str(session.writing_plan_id) if session.writing_plan_id is not None else None
        )
        orm.updated_at = session.updated_at
        await self._session.commit()
