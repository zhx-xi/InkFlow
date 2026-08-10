"""SQLite Agent Run 仓储 — F27 Agentic 写作运行的持久化（决策轨迹 + 状态机）.

转换函数（_orm_to_domain）按项目惯例放在本仓储层（参照
foreshadowing_repo.py / agent_template_repo.py）。

语义（spec §2/§5.7，父侧契约 test_agent_run_repo.py docstring）:
- create: 创建 running 状态 run（id/created_at/updated_at 由 ORM default
  生成后读回），单次 commit
- get: 按 run id（uuid4 字符串）查询
- list: 按 project_id 过滤，created_at desc（最新在前）+ limit 分页，
  返回 (页内容, 该项目全量 total)
- update_result: run 结束后一次性写回（status/steps/final_content/
  draft_id/model/token_usage_total/terminated_by）；steps 为决策轨迹
  JSON 快照全量（Q4 拍板 A），单次 commit；不存在 → None
- 领域 UUID ↔ uuid4 字符串转换在仓储层（project_id/chapter_id 列存
  str(uuid)，与 AgentExecutionORM 先例一致）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与既有仓储惯例一致）。
"""

from __future__ import annotations

import builtins
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.agent_run import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
)
from inkflow.infrastructure.database.models.agent_run import AgentRunORM


def _orm_to_domain(orm: AgentRunORM) -> AgentRun:
    """AgentRun ORM 行 → 领域实体（uuid 字符串 → UUID；steps JSON → 领域对象）."""
    return AgentRun(
        id=orm.id,
        project_id=uuid.UUID(orm.project_id),
        chapter_id=uuid.UUID(orm.chapter_id) if orm.chapter_id is not None else None,
        mode=orm.mode,
        status=AgentRunStatus(orm.status),
        steps=[AgentStep.model_validate(s) for s in (orm.steps or [])],
        final_content=orm.final_content,
        draft_id=orm.draft_id,
        model=orm.model,
        token_usage_total=orm.token_usage_total,
        terminated_by=orm.terminated_by,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class SQLiteAgentRunRepository:
    """SQLite Agent Run 仓储（session 注入，镜像 F34 audit_log_repo 模式）."""

    def __init__(self, db_session: AsyncSession) -> None:
        """以异步会话构造仓储（注入方式与既有仓储一致）."""
        self._session = db_session

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None,
        mode: str = "agentic",
    ) -> AgentRun:
        """创建 running 状态的 run 记录，返回领域 AgentRun（id/created_at 回填）.

        Args:
            project_id: 所属项目 UUID.
            chapter_id: 目标章节 UUID（None = 未绑定）.
            mode: 运行模式（默认 agentic）.

        Returns:
            已落库的 AgentRun（id 为 uuid4 字符串，created_at/updated_at 为
            ORM default 生成的 UTC 时间）.
        """
        orm = AgentRunORM(
            project_id=str(project_id),
            chapter_id=str(chapter_id) if chapter_id is not None else None,
            mode=mode,
        )
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, run_id: str) -> AgentRun | None:
        """按 run id 查询（uuid4 字符串）；缺失 → None."""
        stmt = select(AgentRunORM).where(AgentRunORM.id == run_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def list(
        self,
        project_id: uuid.UUID,
        limit: int = 20,
    ) -> tuple[builtins.list[AgentRun], int]:
        """按项目分页查询 run 记录，created_at desc（最新在前）.

        Args:
            project_id: 所属项目 UUID.
            limit: 每页条数（默认 20）.

        Returns:
            (页内 AgentRun 列表, 该项目 run 总数).
        """
        base = select(AgentRunORM).where(AgentRunORM.project_id == str(project_id))
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self._session.execute(count_stmt)).scalar_one()
        base = base.order_by(AgentRunORM.created_at.desc()).limit(limit)
        result = await self._session.execute(base)
        return [_orm_to_domain(o) for o in result.scalars().all()], total

    async def update_result(
        self,
        run_id: str,
        *,
        status: AgentRunStatus,
        steps: builtins.list[AgentStep],
        final_content: str,
        draft_id: str | None,
        model: str,
        token_usage_total: int,
        terminated_by: str,
    ) -> AgentRun | None:
        """run 结束后一次性写回（steps JSON 快照全量，决策轨迹持久化）.

        Args:
            run_id: run id（uuid4 字符串）.
            status: 终态（completed/failed/terminated_by_guardrail）.
            steps: 决策轨迹全量快照（model_dump(mode="json") 序列化落库）.
            final_content: 最终正文产物.
            draft_id: 兜底保存的草稿 id（无则 None）.
            model: 本次运行使用的模型标识.
            token_usage_total: 累计 token 消耗.
            terminated_by: 终止原因（"llm"/"max_steps"/"repeat_tool"/
                "empty_content"/"token_budget"）.

        Returns:
            更新后的 AgentRun；run_id 不存在 → None.
        """
        stmt = select(AgentRunORM).where(AgentRunORM.id == run_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        orm.status = status.value
        orm.steps = [s.model_dump(mode="json") for s in steps]
        orm.final_content = final_content
        orm.draft_id = draft_id
        orm.model = model
        orm.token_usage_total = token_usage_total
        orm.terminated_by = terminated_by
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)
