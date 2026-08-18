"""SQLite Agent 实体仓储 — 实现 AgentRepositoryProtocol 全部方法.

转换函数（_orm_to_domain / _domain_to_orm）按项目惯例放在本仓储层
（参照 agent_template_repo.py / provider_config_repo.py）。

语义（spec §2.1/§5.6）:
- name 唯一（UNIQUE 约束）: 重复插入同名 → IntegrityError 冒泡，
  服务层先经 get_by_name 检查给出友好 422 文案
- tool_ids / skill_ids 列存 list（LenientJSON，fallback=[]）；转换函数
  透传 list
- list / list_agents_by_skill 按 name 升序
- update 按 id 部分更新（exclude_unset 合并，显式 None = 不修改；
  updated_at 刷新为 now(UTC)，created_at 保留）；不存在 → None
  （builtin 只读保护在服务层）
- delete 不存在 → False
- list_agents_by_skill：Python 过滤实现（契约只定返回值；skill_ids 精确
  含 str(skill_id)，同 agent_template_repo.list_projects_by_template 模式）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/agent_repository.py 一致）。
"""

from __future__ import annotations

import builtins
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.agent import Agent, AgentUpdate
from inkflow.infrastructure.database.models.agent_entity import AgentORM


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _orm_to_domain(orm: AgentORM) -> Agent:
    """Agent ORM 行 → 领域实体（tool_ids/skill_ids 透传 list）."""
    return Agent(
        id=orm.id,
        name=orm.name,
        description=orm.description,
        icon=orm.icon,
        system_prompt=orm.system_prompt,
        tool_ids=list(orm.tool_ids or []),
        skill_ids=list(orm.skill_ids or []),
        model_override=orm.model_override,
        temperature_override=orm.temperature_override,
        builtin=orm.builtin,
        role_key=orm.role_key,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _domain_to_orm(domain: Agent) -> AgentORM:
    """Agent 领域实体 → ORM 行（id 由 DB 自增分配，时间戳由 ORM default 填充）."""
    return AgentORM(
        name=domain.name,
        description=domain.description,
        icon=domain.icon,
        system_prompt=domain.system_prompt,
        tool_ids=list(domain.tool_ids),
        skill_ids=list(domain.skill_ids),
        model_override=domain.model_override,
        temperature_override=domain.temperature_override,
        builtin=domain.builtin,
        role_key=domain.role_key,
    )


class SQLiteAgentRepository:
    """SQLite Agent 实体仓储 — 实现 AgentRepositoryProtocol."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, agent: Agent) -> Agent:
        """插入新 Agent（id 由 DB 自增分配，时间戳由 ORM default 填充）."""
        orm = _domain_to_orm(agent)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, agent_id: int) -> Agent | None:
        """按主键查询 Agent."""
        stmt = select(AgentORM).where(AgentORM.id == agent_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def get_by_name(self, name: str) -> Agent | None:
        """按名称精确查询 Agent（同名唯一检查用）."""
        stmt = select(AgentORM).where(AgentORM.name == name)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def list(self) -> builtins.list[Agent]:
        """列出全部 Agent，按 name 升序."""
        stmt = select(AgentORM).order_by(AgentORM.name.asc())
        result = await self._session.execute(stmt)
        return [_orm_to_domain(o) for o in result.scalars().all()]

    async def update(self, agent_id: int | Agent, data: AgentUpdate | None = None) -> Agent | None:
        """按 id 部分更新或按完整实体更新 Agent（exclude_unset 合并；显式 None = 不修改）.

        服务层契约（test_agent_entity_service.py）：update 以完整实体单参调用
        （merged 实体）；Protocol 双参形态（(id, data)）亦兼容——入参放宽为
        int | Agent、data 可选。updated_at 刷新为 now(UTC)，created_at 保留；
        不存在返回 None（builtin 只读保护在服务层，本层内置也走同一 update）。
        """
        if isinstance(agent_id, Agent):
            entity = agent_id
            target_id = entity.id
            changes = entity.model_dump(
                exclude_unset=True, exclude={"id", "created_at", "updated_at"}
            )
        else:
            target_id = agent_id
            changes = data.model_dump(exclude_unset=True) if data is not None else {}
        if target_id is None:
            return None
        orm = await self._session.get(AgentORM, target_id)
        if orm is None:
            return None
        for field, value in changes.items():
            if value is not None:
                setattr(orm, field, value)
        orm.updated_at = _utcnow()
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def delete(self, agent_id: int) -> bool:
        """物理删除 Agent；不存在返回 False."""
        orm = await self._session.get(AgentORM, agent_id)
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True

    async def list_agents_by_skill(self, skill_id: int) -> builtins.list[Agent]:
        """列出引用指定 Skill 的 Agent（skill_ids 精确含 str(skill_id)），按 name 升序.

        实现方式：Python 过滤（契约只定返回值；精确相等 str 匹配，同
        agent_template_repo.list_projects_by_template 模式）。
        """
        stmt = select(AgentORM).order_by(AgentORM.name.asc())
        result = await self._session.execute(stmt)
        target = str(skill_id)
        agents = []
        for orm in result.scalars().all():
            if target in (orm.skill_ids or []):
                agents.append(_orm_to_domain(orm))
        return agents
