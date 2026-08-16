"""SQLite Skill 仓储 — 实现 SkillRepositoryProtocol 全部方法.

转换函数（_orm_to_domain / _domain_to_orm）按项目惯例放在本仓储层
（参照 agent_template_repo.py / provider_config_repo.py）。

语义（spec §2.2）:
- name 唯一（UNIQUE 约束）: 重复插入同名 → IntegrityError 冒泡，
  服务层先经 get_by_name 检查给出友好 422 文案
- content 存完整 SKILL.md 原样；source 存 "builtin" | "user_upload"
- list 按 name 升序
- update 按 id 部分更新（exclude_unset 合并，显式 None = 不修改；
  updated_at 刷新为 now(UTC)，created_at 保留）；不存在 → None
  （builtin 只读保护在服务层）
- delete 不存在 → False

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/skill_repository.py 一致）。
"""

from __future__ import annotations

import builtins
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.skill import Skill, SkillUpdate
from inkflow.infrastructure.database.models.skill import SkillORM


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _orm_to_domain(orm: SkillORM) -> Skill:
    """Skill ORM 行 → 领域实体."""
    return Skill(
        id=orm.id,
        name=orm.name,
        description=orm.description,
        content=orm.content,
        source=orm.source,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _domain_to_orm(domain: Skill) -> SkillORM:
    """Skill 领域实体 → ORM 行（id 由 DB 自增分配，时间戳由 ORM default 填充）."""
    return SkillORM(
        name=domain.name,
        description=domain.description,
        content=domain.content,
        source=domain.source,
    )


class SQLiteSkillRepository:
    """SQLite Skill 仓储 — 实现 SkillRepositoryProtocol."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, skill: Skill) -> Skill:
        """插入新 Skill（id 由 DB 自增分配，时间戳由 ORM default 填充）."""
        orm = _domain_to_orm(skill)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, skill_id: int) -> Skill | None:
        """按主键查询 Skill."""
        stmt = select(SkillORM).where(SkillORM.id == skill_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def get_by_name(self, name: str) -> Skill | None:
        """按名称精确查询 Skill（同名唯一检查用）."""
        stmt = select(SkillORM).where(SkillORM.name == name)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def list(self) -> builtins.list[Skill]:
        """列出全部 Skill，按 name 升序."""
        stmt = select(SkillORM).order_by(SkillORM.name.asc())
        result = await self._session.execute(stmt)
        return [_orm_to_domain(o) for o in result.scalars().all()]

    async def update(self, skill_id: int | Skill, data: SkillUpdate | None = None) -> Skill | None:
        """按 id 部分更新或按完整实体更新 Skill（exclude_unset 合并；显式 None = 不修改）.

        服务层契约（test_skill_service.py）：update 以完整实体单参调用
        （merged 实体）；Protocol 双参形态（(id, data)）亦兼容——入参放宽为
        int | Skill、data 可选。updated_at 刷新为 now(UTC)，created_at 保留；
        不存在返回 None（builtin 只读保护在服务层，本层内置也走同一 update）。
        """
        if isinstance(skill_id, Skill):
            entity = skill_id
            target_id = entity.id
            changes = entity.model_dump(
                exclude_unset=True, exclude={"id", "created_at", "updated_at"}
            )
        else:
            target_id = skill_id
            changes = data.model_dump(exclude_unset=True) if data is not None else {}
        if target_id is None:
            return None
        orm = await self._session.get(SkillORM, target_id)
        if orm is None:
            return None
        for field, value in changes.items():
            if value is not None:
                setattr(orm, field, value)
        orm.updated_at = _utcnow()
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def delete(self, skill_id: int) -> bool:
        """物理删除 Skill；不存在返回 False."""
        orm = await self._session.get(SkillORM, skill_id)
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True
