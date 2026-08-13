"""管线执行记录存储 — SQLite 异步仓储."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.infrastructure.database.models.agent import AgentExecutionORM


class ExecutionStore:
    """AgentExecutionORM 的异步仓储，负责执行记录的 CRUD。

    所有方法均使用 async/await，绑定调用方提供的 AsyncSession。
    """

    def __init__(self, db_session: AsyncSession):
        self._session = db_session

    async def create_execution(
        self,
        pipeline: str,
        project_id: str,
        chapter_id: str | None = None,
    ) -> AgentExecutionORM:
        """创建 pending 状态的执行记录。"""
        execution = AgentExecutionORM(
            pipeline=pipeline,
            project_id=project_id,
            chapter_id=chapter_id,
        )
        self._session.add(execution)
        await self._session.commit()
        await self._session.refresh(execution)
        return execution

    async def get_execution(self, execution_id: str) -> AgentExecutionORM | None:
        """根据 execution_id 查询。"""
        result = await self._session.execute(
            select(AgentExecutionORM).where(AgentExecutionORM.id == execution_id)
        )
        return result.scalar_one_or_none()

    async def update_stages(
        self,
        execution_id: str,
        stages: list[dict],
        status: str,
        final_output: str = "",
        error: str = "",
        total_duration_ms: int = 0,
    ) -> None:
        """更新 stages 快照和整体状态。"""
        execution = await self.get_execution(execution_id)
        if execution is None:
            return
        execution.stages = stages
        execution.status = status
        execution.final_output = final_output
        execution.error = error
        execution.total_duration_ms = total_duration_ms
        await self._session.commit()

    async def update_status(
        self,
        execution_id: str,
        status: str,
        hitl_payload: dict | None = None,
    ) -> None:
        """更新执行记录状态（HITL：waiting_hitl）。"""
        execution = await self.get_execution(execution_id)
        if execution is None:
            return
        execution.status = status
        if hitl_payload is not None:
            execution.hitl_payload = hitl_payload
        await self._session.commit()

    async def get_hitl_payload(self, execution_id: str) -> dict | None:
        """读取 HITL interrupt payload 快照。"""
        execution = await self.get_execution(execution_id)
        if execution is None:
            return None
        return execution.hitl_payload

    async def list_executions(
        self,
        project_id: str,
        limit: int = 20,
    ) -> tuple[list[AgentExecutionORM], int]:
        """按 project_id 分页查询（按 created_at 降序）。"""
        total = await self._session.scalar(
            select(func.count())
            .select_from(AgentExecutionORM)
            .where(AgentExecutionORM.project_id == project_id)
        )
        result = await self._session.execute(
            select(AgentExecutionORM)
            .where(AgentExecutionORM.project_id == project_id)
            .order_by(AgentExecutionORM.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0
