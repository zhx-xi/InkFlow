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
        *,
        thread_id: str | None = None,
        execution_id: str | None = None,
    ) -> AgentExecutionORM:
        """创建 pending 状态的执行记录。

        F44 阶段 4（#338）：execution_id 给定 → 固定执行记录 id（书级运行 =
        str(plan.id)）；thread_id 给定 → 落 LangGraph checkpoint thread_id
        （书级运行 ↔ 图 checkpoint 一一映射）。既有调用（agent_service 等）
        不传新参数 → 默认 uuid4 / None，行为不变。
        """
        execution = AgentExecutionORM(
            pipeline=pipeline,
            project_id=project_id,
            chapter_id=chapter_id,
            id=execution_id,
            thread_id=thread_id,
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
        relations: list | None = None,
        trace: list | None = None,
        injected_context: dict | None = None,
    ) -> None:
        """更新 stages 快照和整体状态（F47 #379：trace 轨迹快照一并落库）。

        #1349：injected_context 落「本次实际注入」的 id 明细；不传（None）= 该字段
        保持原值不动（既有调用零改动，且不在管线失败路径上误清已写入的明细）。
        """
        execution = await self.get_execution(execution_id)
        if execution is None:
            return
        execution.stages = stages
        execution.status = status
        execution.final_output = final_output
        execution.error = error
        execution.total_duration_ms = total_duration_ms
        execution.relations = relations if relations is not None else []
        execution.trace = trace if trace is not None else []
        if injected_context is not None:
            execution.injected_context = injected_context
        await self._session.commit()

    async def update_injected_context(
        self,
        execution_id: str,
        injected_context: dict,
    ) -> None:
        """#1349：单独落「本次实际注入」明细（注入发生在管线执行**之前**）。

        与 update_stages 分开写：注入在 stage 流开始前就已完成（`_inject_context`
        早于 `pipeline.stream`），单列写入保证「管线中途异常」时明细仍已落库
        —— 回执面不因运行结果而丢失。
        """
        execution = await self.get_execution(execution_id)
        if execution is None:
            return
        execution.injected_context = injected_context
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
        execution: AgentExecutionORM | None = await self.get_execution(execution_id)
        if execution is None:
            return None
        payload: dict | None = execution.hitl_payload
        return payload

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

    async def list_chapter_executions(
        self,
        chapter_id: str,
        limit: int = 20,
    ) -> tuple[list[AgentExecutionORM], int]:
        """#1349：按 chapter_id 查执行记录（created_at 降序，最新在前）。

        章级注入回显的取数口：调用方按序取**第一条已有 injected_context** 的记录
        （最新一次生成的实际注入明细）。
        """
        total = await self._session.scalar(
            select(func.count())
            .select_from(AgentExecutionORM)
            .where(AgentExecutionORM.chapter_id == chapter_id)
        )
        result = await self._session.execute(
            select(AgentExecutionORM)
            .where(AgentExecutionORM.chapter_id == chapter_id)
            .order_by(AgentExecutionORM.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0
