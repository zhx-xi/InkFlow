"""SQLite 角色/分组/关系仓储 — 实现 CharacterRepositoryProtocol 全部 23 个方法.

转换函数（_orm_to_domain / _domain_to_orm / int↔UUID 辅助）按项目惯例
放在本仓储层（参照 project_repo.py / chapter_repo.py）。

级联语义（spec §2.3/§6/§7）:
- 角色软删除 → 其全部关系（双向）级联软删除；角色恢复 → 级联恢复
- 分组软删除/硬删除 → 成员角色 group_id 置 NULL（角色本身保留）
- 角色硬删除 → 关系物理删除（DB FK CASCADE）
- 活动记录 partial unique：同名/同关系键软删后可重建（spec §2.4）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/character_repository.py 一致）。
"""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.character import Character, CharacterGroup, CharacterRelation
from inkflow.infrastructure.database.models.character import (
    CharacterGroupORM,
    CharacterORM,
    CharacterRelationORM,
)


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _int_to_uuid(value: int | uuid.UUID | None) -> uuid.UUID | None:
    """DB int → 领域 UUID（F1 映射: uuid.UUID(int=...)）."""
    if value is None:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(int=value)


def _uuid_to_int(value: uuid.UUID | int) -> int:
    """领域 UUID → DB int（F1 映射: uuid.int）."""
    return value.int if isinstance(value, uuid.UUID) else int(value)


def _char_orm_to_domain(orm: CharacterORM) -> Character:
    """角色 ORM 行 → 领域实体（int PK → UUID）."""
    return Character(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        name=orm.name,
        personality=orm.personality,
        background=orm.background,
        goals=orm.goals,
        group_id=_int_to_uuid(orm.group_id),
        extra=orm.extra or {},
        is_deleted=orm.is_deleted,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _char_domain_to_orm(domain: Character) -> CharacterORM:
    """角色领域实体 → ORM 行（UUID → int；id 由 DB 自增分配，不落库）."""
    return CharacterORM(
        project_id=_uuid_to_int(domain.project_id),
        name=domain.name,
        personality=domain.personality,
        background=domain.background,
        goals=domain.goals,
        group_id=_uuid_to_int(domain.group_id) if domain.group_id is not None else None,
        extra=domain.extra,
        is_deleted=domain.is_deleted,
    )


def _group_orm_to_domain(orm: CharacterGroupORM) -> CharacterGroup:
    """分组 ORM 行 → 领域实体（int PK → UUID）."""
    return CharacterGroup(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        name=orm.name,
        description=orm.description,
        sort_order=orm.sort_order,
        is_deleted=orm.is_deleted,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _group_domain_to_orm(domain: CharacterGroup) -> CharacterGroupORM:
    """分组领域实体 → ORM 行（UUID → int；id 由 DB 自增分配）."""
    return CharacterGroupORM(
        project_id=_uuid_to_int(domain.project_id),
        name=domain.name,
        description=domain.description,
        sort_order=domain.sort_order,
        is_deleted=domain.is_deleted,
    )


def _relation_orm_to_domain(orm: CharacterRelationORM) -> CharacterRelation:
    """关系 ORM 行 → 领域实体（int PK → UUID）."""
    return CharacterRelation(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        from_character_id=uuid.UUID(int=orm.from_character_id),
        to_character_id=uuid.UUID(int=orm.to_character_id),
        relation_type=orm.relation_type,
        description=orm.description,
        is_deleted=orm.is_deleted,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _relation_domain_to_orm(domain: CharacterRelation) -> CharacterRelationORM:
    """关系领域实体 → ORM 行（UUID → int；id 由 DB 自增分配）."""
    return CharacterRelationORM(
        project_id=_uuid_to_int(domain.project_id),
        from_character_id=_uuid_to_int(domain.from_character_id),
        to_character_id=_uuid_to_int(domain.to_character_id),
        relation_type=domain.relation_type,
        description=domain.description,
        is_deleted=domain.is_deleted,
    )


class SQLiteCharacterRepository:
    """SQLite 角色/分组/关系仓储 — 实现 CharacterRepositoryProtocol 接口."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Character ──

    async def add(self, character: Character) -> Character:
        """插入新角色（id 由 DB 自增分配，读回时映射为 UUID）."""
        orm = _char_domain_to_orm(character)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _char_orm_to_domain(orm)

    async def get(self, character_id: int) -> Character | None:
        """按主键查询角色（不含已软删除）."""
        stmt = select(CharacterORM).where(
            CharacterORM.id == character_id,
            ~CharacterORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _char_orm_to_domain(orm) if orm else None

    async def get_by_name(self, project_id: int, name: str) -> Character | None:
        """按项目内角色名查询活动角色（不含已软删除）."""
        stmt = select(CharacterORM).where(
            CharacterORM.project_id == project_id,
            CharacterORM.name == name,
            ~CharacterORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _char_orm_to_domain(orm) if orm else None

    async def list(
        self,
        project_id: int,
        search: str | None = None,
        group_id: int | None = None,
        sort_by: str = "updated_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[Character], int]:
        """分页查询项目内角色列表，支持搜索与分组过滤（不含已软删除）.

        Returns:
            (当前页角色列表, 符合条件的总记录数).
        """
        base = select(CharacterORM).where(
            CharacterORM.project_id == project_id,
            ~CharacterORM.is_deleted,
        )

        # 搜索: name icontains
        if search:
            base = base.where(CharacterORM.name.icontains(search))
        # 分组过滤
        if group_id is not None:
            base = base.where(CharacterORM.group_id == group_id)

        # 总数（分页前）
        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        # 排序 + 分页
        sort_col = getattr(CharacterORM, sort_by, CharacterORM.updated_at)
        base = base.order_by(sort_col.desc() if sort_desc else sort_col.asc())
        base = base.offset(offset).limit(limit)

        result = await self._session.execute(base)
        orms = result.scalars().all()
        return [_char_orm_to_domain(o) for o in orms], total

    async def update(self, character: Character) -> Character:
        """更新角色（按 id 定位，updated_at 自动刷新）."""
        char_id = _uuid_to_int(character.id)
        stmt = (
            sa_update(CharacterORM)
            .where(CharacterORM.id == char_id)
            .values(
                name=character.name,
                personality=character.personality,
                background=character.background,
                goals=character.goals,
                group_id=(
                    _uuid_to_int(character.group_id) if character.group_id is not None else None
                ),
                extra=character.extra,
                updated_at=_utcnow(),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise ValueError(f"Character {char_id} not found")

        stmt2 = select(CharacterORM).where(CharacterORM.id == char_id)
        result2 = await self._session.execute(stmt2)
        orm = result2.scalar_one_or_none()
        if orm is None:
            raise ValueError(f"Character {char_id} not found after update")
        return _char_orm_to_domain(orm)

    async def soft_delete(self, character_id: int) -> bool:
        """软删除角色（is_deleted=True，级联软删其双向关系）.

        Returns:
            True 表示成功删除一条记录，False 表示未找到/已删除.
        """
        stmt = (
            sa_update(CharacterORM)
            .where(CharacterORM.id == character_id, ~CharacterORM.is_deleted)
            .values(is_deleted=True, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        if result.rowcount > 0:  # type: ignore[attr-defined]
            # 级联软删关系；该方法内部 commit，角色 UPDATE 一并提交（单事务）
            await self.soft_delete_relations_of(character_id)
        else:
            await self._session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def restore(self, character_id: int) -> Character | None:
        """恢复已软删除角色（含级联恢复其双向关系）.

        Returns:
            恢复后的 Character；记录不存在或未删除时返回 None（重复操作无毒）.
        """
        stmt = (
            sa_update(CharacterORM)
            .where(CharacterORM.id == character_id, CharacterORM.is_deleted)
            .values(is_deleted=False, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        if result.rowcount > 0:  # type: ignore[attr-defined]
            # 级联恢复关系；该方法内部 commit，角色 UPDATE 一并提交（单事务）
            await self.restore_relations_of(character_id)
        else:
            await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            return None
        return await self.get(character_id)

    async def hard_delete(self, character_id: int) -> bool:
        """物理删除角色（其双向关系由 DB FK CASCADE 物理删除）."""
        stmt = select(CharacterORM).where(CharacterORM.id == character_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True

    # ── CharacterGroup ──

    async def add_group(self, group: CharacterGroup) -> CharacterGroup:
        """插入新分组（id 由 DB 自增分配）."""
        orm = _group_domain_to_orm(group)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _group_orm_to_domain(orm)

    async def get_group(self, group_id: int) -> CharacterGroup | None:
        """按主键查询分组（不含已软删除）."""
        stmt = select(CharacterGroupORM).where(
            CharacterGroupORM.id == group_id,
            ~CharacterGroupORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _group_orm_to_domain(orm) if orm else None

    async def list_groups(self, project_id: int) -> builtins.list[CharacterGroup]:
        """查询项目内全部分组（不含已软删除，按 sort_order 升序）."""
        stmt = (
            select(CharacterGroupORM)
            .where(
                CharacterGroupORM.project_id == project_id,
                ~CharacterGroupORM.is_deleted,
            )
            .order_by(CharacterGroupORM.sort_order.asc(), CharacterGroupORM.id.asc())
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [_group_orm_to_domain(o) for o in orms]

    async def update_group(self, group: CharacterGroup) -> CharacterGroup:
        """更新分组（按 id 定位，updated_at 自动刷新）."""
        group_id = _uuid_to_int(group.id)
        stmt = (
            sa_update(CharacterGroupORM)
            .where(CharacterGroupORM.id == group_id)
            .values(
                name=group.name,
                description=group.description,
                sort_order=group.sort_order,
                updated_at=_utcnow(),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise ValueError(f"CharacterGroup {group_id} not found")

        stmt2 = select(CharacterGroupORM).where(CharacterGroupORM.id == group_id)
        result2 = await self._session.execute(stmt2)
        orm = result2.scalar_one_or_none()
        if orm is None:
            raise ValueError(f"CharacterGroup {group_id} not found after update")
        return _group_orm_to_domain(orm)

    async def soft_delete_group(self, group_id: int) -> bool:
        """软删除分组，成员角色 group_id 置 NULL（角色本身保留）."""
        stmt = (
            sa_update(CharacterGroupORM)
            .where(CharacterGroupORM.id == group_id, ~CharacterGroupORM.is_deleted)
            .values(is_deleted=True, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        if result.rowcount > 0:  # type: ignore[attr-defined]
            await self._session.execute(
                sa_update(CharacterORM)
                .where(CharacterORM.group_id == group_id)
                .values(group_id=None, updated_at=_utcnow())
            )
        await self._session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def hard_delete_group(self, group_id: int) -> bool:
        """物理删除分组，成员角色 group_id 置 NULL（角色本身保留）."""
        stmt = select(CharacterGroupORM).where(CharacterGroupORM.id == group_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        await self._session.execute(
            sa_update(CharacterORM)
            .where(CharacterORM.group_id == group_id)
            .values(group_id=None, updated_at=_utcnow())
        )
        await self._session.delete(orm)
        await self._session.commit()
        return True

    # ── CharacterRelation ──

    async def add_relation(self, relation: CharacterRelation) -> CharacterRelation:
        """插入新关系（id 由 DB 自增分配）."""
        orm = _relation_domain_to_orm(relation)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _relation_orm_to_domain(orm)

    async def get_relation(self, relation_id: int) -> CharacterRelation | None:
        """按主键查询关系（不含已软删除）."""
        stmt = select(CharacterRelationORM).where(
            CharacterRelationORM.id == relation_id,
            ~CharacterRelationORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _relation_orm_to_domain(orm) if orm else None

    async def get_relation_by_key(
        self, from_id: int, to_id: int, relation_type: str
    ) -> CharacterRelation | None:
        """按 (from, to, relation_type) 唯一键查询活动关系."""
        stmt = select(CharacterRelationORM).where(
            CharacterRelationORM.from_character_id == from_id,
            CharacterRelationORM.to_character_id == to_id,
            CharacterRelationORM.relation_type == relation_type,
            ~CharacterRelationORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _relation_orm_to_domain(orm) if orm else None

    async def list_relations(
        self, project_id: int, character_id: int | None = None
    ) -> builtins.list[CharacterRelation]:
        """查询项目内关系列表，可按角色过滤（双向）.

        提供 character_id 时返回该角色作为起点或终点的全部活动关系。
        """
        stmt = select(CharacterRelationORM).where(
            CharacterRelationORM.project_id == project_id,
            ~CharacterRelationORM.is_deleted,
        )
        if character_id is not None:
            stmt = stmt.where(
                or_(
                    CharacterRelationORM.from_character_id == character_id,
                    CharacterRelationORM.to_character_id == character_id,
                )
            )
        stmt = stmt.order_by(CharacterRelationORM.id.asc())
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [_relation_orm_to_domain(o) for o in orms]

    async def update_relation(self, relation: CharacterRelation) -> CharacterRelation:
        """更新关系（按 id 定位，updated_at 自动刷新）."""
        rel_id = _uuid_to_int(relation.id)
        stmt = (
            sa_update(CharacterRelationORM)
            .where(CharacterRelationORM.id == rel_id)
            .values(
                from_character_id=_uuid_to_int(relation.from_character_id),
                to_character_id=_uuid_to_int(relation.to_character_id),
                relation_type=relation.relation_type,
                description=relation.description,
                updated_at=_utcnow(),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise ValueError(f"CharacterRelation {rel_id} not found")

        stmt2 = select(CharacterRelationORM).where(CharacterRelationORM.id == rel_id)
        result2 = await self._session.execute(stmt2)
        orm = result2.scalar_one_or_none()
        if orm is None:
            raise ValueError(f"CharacterRelation {rel_id} not found after update")
        return _relation_orm_to_domain(orm)

    async def soft_delete_relation(self, relation_id: int) -> bool:
        """软删除关系（is_deleted=True）."""
        stmt = (
            sa_update(CharacterRelationORM)
            .where(CharacterRelationORM.id == relation_id, ~CharacterRelationORM.is_deleted)
            .values(is_deleted=True, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def hard_delete_relation(self, relation_id: int) -> bool:
        """物理删除关系."""
        stmt = select(CharacterRelationORM).where(CharacterRelationORM.id == relation_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True

    # ── 级联操作 ──

    async def soft_delete_relations_of(self, character_id: int) -> None:
        """级联软删某角色的全部关系（双向，角色软删除时调用）.

        内部执行 UPDATE 并 commit（与调用方 pending 变更同一事务）。
        """
        await self._session.execute(
            sa_update(CharacterRelationORM)
            .where(
                or_(
                    CharacterRelationORM.from_character_id == character_id,
                    CharacterRelationORM.to_character_id == character_id,
                ),
                ~CharacterRelationORM.is_deleted,
            )
            .values(is_deleted=True, updated_at=_utcnow())
        )
        await self._session.commit()

    async def restore_relations_of(self, character_id: int) -> None:
        """级联恢复某角色的全部关系（双向，角色恢复时调用）.

        内部执行 UPDATE 并 commit（与调用方 pending 变更同一事务）。
        """
        await self._session.execute(
            sa_update(CharacterRelationORM)
            .where(
                or_(
                    CharacterRelationORM.from_character_id == character_id,
                    CharacterRelationORM.to_character_id == character_id,
                ),
                CharacterRelationORM.is_deleted,
            )
            .values(is_deleted=False, updated_at=_utcnow())
        )
        await self._session.commit()
