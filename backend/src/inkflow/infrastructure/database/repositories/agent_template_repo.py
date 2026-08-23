"""SQLite 模板仓储 — 实现 AgentTemplateRepositoryProtocol 全部方法.

转换函数（_orm_to_domain / _domain_to_orm）按项目惯例放在本仓储层
（参照 provider_config_repo.py / foreshadowing_repo.py）。

语义（spec §9.2/§9.3）:
- name 唯一（UNIQUE 约束）: 重复插入同名 → IntegrityError 冒泡，
  服务层先经 get_by_name 检查给出友好 422 文案
- roles 列存 ``{key: RoleTemplate.model_dump()}``（dict，JSON 列）；
  读回 ``{key: RoleTemplate.model_validate(v)}``
- list 按 name 升序
- update 按 id 全量更新（updated_at 刷新为 now(UTC)，created_at 保留）；
  不存在 → ValueError（镜像 F13 仓储惯例）；is_default=True 时先清空其他
  行降级 False（单例）
- delete 不存在 → False
- set_default 便捷方法：目标行 is_default=True + 其他行降级 False；
  不存在 → None
- list_projects_by_template：projects 表 config JSON 的 template_id 精确
  等于 str(template_id)，排除软删项目，按 name 升序返回领域 Project 列表
  （Python 过滤实现，契约只定返回值）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/agent_template_repository.py 一致）。
"""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.agent_template import AgentTemplate, RoleTemplate
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.infrastructure.database.models.agent_template import AgentTemplateORM
from inkflow.infrastructure.database.models.project import ProjectORM


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _orm_to_domain(orm: AgentTemplateORM) -> AgentTemplate:
    """模板 ORM 行 → 领域实体（roles dict → RoleTemplate 转换）."""
    return AgentTemplate(
        id=orm.id,
        name=orm.name,
        description=orm.description,
        main_model=orm.main_model,
        default_temperature=orm.default_temperature,
        roles={k: RoleTemplate.model_validate(v) for k, v in (orm.roles or {}).items()},
        default_words=orm.default_words,
        is_default=orm.is_default,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _domain_to_orm(domain: AgentTemplate) -> AgentTemplateORM:
    """模板领域实体 → ORM 行（id 由 DB 自增分配，时间戳由 ORM default 填充）."""
    return AgentTemplateORM(
        name=domain.name,
        description=domain.description,
        main_model=domain.main_model,
        default_temperature=domain.default_temperature,
        roles={k: v.model_dump() for k, v in domain.roles.items()},
        default_words=domain.default_words,
        is_default=domain.is_default,
    )


def _project_orm_to_domain(orm: ProjectORM) -> Project:
    """项目 ORM 行 → 领域实体（int 主键 → UUID 可逆转换，同 project_repo）."""
    return Project(
        id=uuid.UUID(int=orm.id) if isinstance(orm.id, int) else orm.id,
        name=orm.name,
        tags=orm.tags or [],
        language=orm.language,
        target_words=orm.target_words,
        config=ProjectConfig(**orm.config) if orm.config else ProjectConfig(),
        is_deleted=orm.is_deleted,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class SQLiteAgentTemplateRepository:
    """SQLite 模板仓储 — 实现 AgentTemplateRepositoryProtocol."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, at: AgentTemplate) -> AgentTemplate:
        """插入新模板（id 由 DB 自增分配，时间戳由 ORM default 填充）."""
        orm = _domain_to_orm(at)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, template_id: int) -> AgentTemplate | None:
        """按主键查询模板."""
        stmt = select(AgentTemplateORM).where(AgentTemplateORM.id == template_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def get_by_name(self, name: str) -> AgentTemplate | None:
        """按名称精确查询模板（同名唯一检查用）."""
        stmt = select(AgentTemplateORM).where(AgentTemplateORM.name == name)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def list(self) -> builtins.list[AgentTemplate]:
        """列出全部模板，按 name 升序."""
        stmt = select(AgentTemplateORM).order_by(AgentTemplateORM.name.asc())
        result = await self._session.execute(stmt)
        return [_orm_to_domain(o) for o in result.scalars().all()]

    async def update(self, at: AgentTemplate) -> AgentTemplate:
        """按 id 全量更新模板字段（updated_at 刷新，created_at 保留）.

        不存在 → ValueError（镜像 F13 仓储惯例，router 层转 404）。
        is_default 单例：at.is_default=True 时先清空其他行 is_default=False。
        """
        orm = await self._session.get(AgentTemplateORM, at.id)
        if orm is None:
            raise ValueError(f"Agent template not found: {at.id}")
        if at.is_default:
            await self._session.execute(
                sa_update(AgentTemplateORM)
                .where(AgentTemplateORM.id != at.id)
                .values(is_default=False)
            )
        orm.name = at.name
        orm.description = at.description
        orm.main_model = at.main_model
        orm.default_temperature = at.default_temperature
        orm.roles = {k: v.model_dump() for k, v in at.roles.items()}
        orm.default_words = at.default_words
        orm.is_default = at.is_default
        orm.updated_at = _utcnow()
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def delete(self, template_id: int) -> bool:
        """物理删除模板；不存在返回 False."""
        orm = await self._session.get(AgentTemplateORM, template_id)
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True

    async def set_default(self, template_id: int) -> AgentTemplate | None:
        """将指定模板设为默认（单例）；不存在返回 None."""
        orm = await self._session.get(AgentTemplateORM, template_id)
        if orm is None:
            return None
        await self._session.execute(
            sa_update(AgentTemplateORM)
            .where(AgentTemplateORM.id != template_id)
            .values(is_default=False)
        )
        orm.is_default = True
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def list_projects_by_template(self, template_id: int) -> builtins.list[Project]:
        """列出引用指定模板的项目（config JSON template_id 精确匹配，排除软删，按 name 升序）.

        实现方式：Python 过滤（契约只定返回值；精确相等 str 匹配）。
        """
        stmt = select(ProjectORM).where(~ProjectORM.is_deleted).order_by(ProjectORM.name.asc())
        result = await self._session.execute(stmt)
        target = str(template_id)
        projects = []
        for orm in result.scalars().all():
            config = orm.config or {}
            if config.get("template_id") == target:
                projects.append(_project_orm_to_domain(orm))
        return projects
