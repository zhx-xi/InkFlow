"""SQLite 知识图谱关系仓储 —— 实现 KnowledgeRelationRepositoryProtocol 全部方法.

转换函数（_orm_to_domain / _domain_to_orm / int↔UUID 映射）按项目惯例
放在本仓储层（参照 project_repo.py / character_repo.py）。

级联语义（spec §2.1/§5.3，v1.1 真删）：
- 实体硬删 → 其全部关系（双向）物理删除（service 显式调用 cleanup_for_entity）
- 项目硬删 → 关系级联删除（DB FK CASCADE）
- 项目内同键关系全唯一（全唯一索引，spec §2.4）
- 唯一约束冲突直接透传 IntegrityError——冲突错误由 service 层转换为
  KnowledgeRelationConflictError（spec §5.1 规则 4）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/knowledge_relation_repository.py 一致）。
"""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.knowledge_graph import (
    EntityType,
    KnowledgeRelation,
    RelationSource,
)
from inkflow.infrastructure.database.models.knowledge_graph import KnowledgeRelationORM


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _ensure_utc(value: datetime) -> datetime:
    """补时区：SQLite DateTime 读回丢 tzinfo，测试契约断言 aware UTC（F48 固定陷阱）."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _orm_to_domain(orm: KnowledgeRelationORM) -> KnowledgeRelation:
    """关系 ORM 行 → 领域实体（int PK → UUID；读回时间补 UTC tzinfo）."""
    return KnowledgeRelation(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        source_type=EntityType(orm.source_type),
        source_id=uuid.UUID(int=orm.source_id),
        target_type=EntityType(orm.target_type),
        target_id=uuid.UUID(int=orm.target_id),
        relation_type=orm.relation_type,
        description=orm.description,
        source=RelationSource(orm.source),
        created_at=_ensure_utc(orm.created_at),
        updated_at=_ensure_utc(orm.updated_at),
    )


def _domain_to_orm(domain: KnowledgeRelation) -> KnowledgeRelationORM:
    """关系领域实体 → ORM 行（UUID → int；id 由 DB 自增分配，不落库）."""
    return KnowledgeRelationORM(
        project_id=domain.project_id.int,
        source_type=domain.source_type.value,
        source_id=domain.source_id.int,
        target_type=domain.target_type.value,
        target_id=domain.target_id.int,
        relation_type=domain.relation_type,
        description=domain.description,
        source=domain.source.value,
        created_at=domain.created_at,
        updated_at=domain.updated_at,
    )


class SQLiteKnowledgeRelationRepository:
    """SQLite 知识图谱关系仓储 —— 实现 KnowledgeRelationRepositoryProtocol 接口."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── add/get/get_by_key ──

    async def add(self, relation: KnowledgeRelation) -> KnowledgeRelation:
        """插入新关系（id 由 DB 自增分配，flush/refresh 回读 id/时间戳）.

        六元组唯一约束冲突直接透传 IntegrityError——冲突错误由 service 层转换。
        """
        orm = _domain_to_orm(relation)
        self._session.add(orm)
        await self._session.flush()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, relation_id: int) -> KnowledgeRelation | None:
        """按主键查询关系."""
        stmt = select(KnowledgeRelationORM).where(KnowledgeRelationORM.id == relation_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def get_by_key(
        self,
        project_id: int,
        source_type: str,
        source_id: int,
        target_type: str,
        target_id: int,
        relation_type: str,
    ) -> KnowledgeRelation | None:
        """按六元组唯一键查询关系."""
        stmt = select(KnowledgeRelationORM).where(
            KnowledgeRelationORM.project_id == project_id,
            KnowledgeRelationORM.source_type == source_type,
            KnowledgeRelationORM.source_id == source_id,
            KnowledgeRelationORM.target_type == target_type,
            KnowledgeRelationORM.target_id == target_id,
            KnowledgeRelationORM.relation_type == relation_type,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    # ── list（created_at DESC）与分页 ──

    async def list(
        self, project_id: int, offset: int = 0, limit: int = 50
    ) -> tuple[builtins.list[KnowledgeRelation], int]:
        """分页查询项目内关系列表（created_at DESC，新在前）.

        Returns:
            (当前页关系列表, 符合条件的总记录数).
        """
        base = select(KnowledgeRelationORM).where(KnowledgeRelationORM.project_id == project_id)
        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        stmt = (
            base.order_by(
                KnowledgeRelationORM.created_at.desc(),
                KnowledgeRelationORM.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [_orm_to_domain(o) for o in orms], total

    # ── filter（组合过滤 + 分页）──

    async def filter(
        self,
        project_id: int,
        source_type: str | None = None,
        target_type: str | None = None,
        relation_type: str | None = None,
        source: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[KnowledgeRelation], int]:
        """组合过滤 + 分页查询项目内关系（None 条件不参与，created_at DESC）.

        Returns:
            (关系列表, 总数) 元组.
        """
        base = select(KnowledgeRelationORM).where(KnowledgeRelationORM.project_id == project_id)
        if source_type is not None:
            base = base.where(KnowledgeRelationORM.source_type == source_type)
        if target_type is not None:
            base = base.where(KnowledgeRelationORM.target_type == target_type)
        if relation_type is not None:
            base = base.where(KnowledgeRelationORM.relation_type == relation_type)
        if source is not None:
            base = base.where(KnowledgeRelationORM.source == source)

        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        stmt = (
            base.order_by(
                KnowledgeRelationORM.created_at.desc(),
                KnowledgeRelationORM.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [_orm_to_domain(o) for o in orms], total

    # ── update ──

    async def update(self, relation: KnowledgeRelation) -> KnowledgeRelation:
        """按 id 定位全字段覆盖（key/description/source 均以领域对象为准，updated_at 刷新）."""
        rel_id = relation.id.int
        stmt = (
            sa_update(KnowledgeRelationORM)
            .where(KnowledgeRelationORM.id == rel_id)
            .values(
                source_type=relation.source_type.value,
                source_id=relation.source_id.int,
                target_type=relation.target_type.value,
                target_id=relation.target_id.int,
                relation_type=relation.relation_type,
                description=relation.description,
                source=relation.source.value,
                updated_at=_utcnow(),
            )
        )
        result = await self._session.execute(stmt)
        if result.rowcount == 0:  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）
            raise ValueError(f"KnowledgeRelation {rel_id} not found")
        stmt2 = select(KnowledgeRelationORM).where(KnowledgeRelationORM.id == rel_id)
        result2 = await self._session.execute(stmt2)
        orm = result2.scalar_one_or_none()
        if orm is None:
            raise ValueError(f"KnowledgeRelation {rel_id} not found after update")
        return _orm_to_domain(orm)

    # ── delete（真删语义，无 is_deleted）──

    async def delete(self, relation_id: int) -> bool:
        """真删关系（无 is_deleted）；不存在返回 False."""
        stmt = sa_delete(KnowledgeRelationORM).where(KnowledgeRelationORM.id == relation_id)
        result = await self._session.execute(stmt)
        return result.rowcount > 0  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）

    async def list_by_project(self, project_id: int) -> builtins.list[KnowledgeRelation]:
        """列出项目全部关系（图谱聚合全量，created_at ASC 供 graph 稳定排序）."""
        stmt = (
            select(KnowledgeRelationORM)
            .where(KnowledgeRelationORM.project_id == project_id)
            .order_by(KnowledgeRelationORM.created_at.asc(), KnowledgeRelationORM.id.asc())
        )
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [_orm_to_domain(o) for o in orms]

    # ── delete_by_entity / cleanup_for_entity（实体硬删级联清理）──

    async def delete_by_entity(self, entity_type: str, entity_id: int) -> int:
        """删除指定实体作为 source 或 target 的全部关系行（真删），返回删除行数.

        实体 UUID 全局唯一（uuid4），故按 entity_id 匹配 source_id/target_id；
        entity_type 保留以兼容 Protocol 签名（RED 测试契约按 ID 匹配，见
        tests/unit/test_knowledge_relation_repo.py delete_by_entity/cleanup 用例）。
        """
        stmt = sa_delete(KnowledgeRelationORM).where(
            or_(
                KnowledgeRelationORM.source_id == entity_id,
                KnowledgeRelationORM.target_id == entity_id,
            )
        )
        result = await self._session.execute(stmt)
        return result.rowcount  # type: ignore[attr-defined]  # SQLAlchemy Result 类型未声明 rowcount（属性在底层 cursor）

    async def cleanup_for_entity(self, entity_type: str, entity_id: int) -> int:
        """实体硬删级联清理 —— delete_by_entity 别名（§5.3，语义一致）."""
        return await self.delete_by_entity(entity_type, entity_id)
