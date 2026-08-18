"""图谱关系仓储端口 — knowledge_relations 持久化契约.

KnowledgeRelationRepositoryProtocol 定义 KnowledgeRelation 的 CRUD 操作与
实体清理辅助方法，基础设施层（SQLite / mock / memory）实现该 Protocol。
仓储层方法入参用 int（与 ORM 层一致），Service 负责 UUID → int 转换
（沿用 F1 `_to_int_id` 模式）。

依据: specs/f48-knowledge-graph/spec.md §2.1/§5.2/§5.3。
"""

from __future__ import annotations

import builtins
from typing import Protocol

from inkflow.domain.models.knowledge_graph import KnowledgeRelation


class KnowledgeRelationRepositoryProtocol(Protocol):
    """图谱关系仓储端口.

    按 spec §2.1: 六元组 (project_id, source_type, source_id, target_type,
    target_id, relation_type) 全唯一索引；无 is_deleted 列——删除即真删。

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9/F10）。
    """

    async def add(self, relation: KnowledgeRelation) -> KnowledgeRelation:
        """插入新关系.

        Args:
            relation: 待持久化的关系（id 为领域 UUID）.

        Returns:
            持久化后的 KnowledgeRelation.
        """
        ...

    async def get(self, relation_id: int) -> KnowledgeRelation | None:
        """按主键查询关系.

        Args:
            relation_id: 关系主键（int，与 ORM 层一致）.

        Returns:
            命中则返回 KnowledgeRelation，否则返回 None.
        """
        ...

    async def get_by_key(
        self,
        project_id: int,
        source_type: str,
        source_id: int,
        target_type: str,
        target_id: int,
        relation_type: str,
    ) -> KnowledgeRelation | None:
        """按六元组唯一键查询关系.

        Args:
            project_id: 项目主键（int）.
            source_type: 起点实体类型（EntityType 值字符串）.
            source_id: 起点实体主键（int）.
            target_type: 终点实体类型（EntityType 值字符串）.
            target_id: 终点实体主键（int）.
            relation_type: 关系类型（已去空白）.

        Returns:
            命中则返回 KnowledgeRelation，否则返回 None.
        """
        ...

    async def list(
        self, project_id: int, offset: int = 0, limit: int = 50
    ) -> tuple[builtins.list[KnowledgeRelation], int]:
        """分页查询项目内关系列表（created_at DESC，新在前）.

        Args:
            project_id: 项目主键（int）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (关系列表, 总数) 元组.
        """
        ...

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
        """组合过滤 + 分页查询项目内关系.

        Args:
            project_id: 项目主键（int）.
            source_type: 起点实体类型过滤（可选）.
            target_type: 终点实体类型过滤（可选）.
            relation_type: 关系类型精确过滤（可选）.
            source: 来源过滤（manual/ai，可选）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (关系列表, 总数) 元组，created_at DESC 排序.
        """
        ...

    async def list_by_project(self, project_id: int) -> builtins.list[KnowledgeRelation]:
        """列出项目全部关系（图谱聚合全量）.

        Args:
            project_id: 项目主键（int）.

        Returns:
            项目内全部关系列表.
        """
        ...

    async def update(self, relation: KnowledgeRelation) -> KnowledgeRelation | None:
        """更新关系（按 id 定位全字段覆盖）.

        Args:
            relation: 含待更新字段的完整关系对象.

        Returns:
            持久化后的 KnowledgeRelation；关系不存在返回 None.
        """
        ...

    async def delete(self, relation_id: int) -> bool:
        """真删关系（无 is_deleted）.

        Args:
            relation_id: 关系主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    async def delete_by_entity(self, entity_type: str, entity_id: int) -> int:
        """删除指定实体作为 source 或 target 的全部关系行.

        Args:
            entity_type: 实体类型（EntityType 值字符串）.
            entity_id: 实体主键（int）.

        Returns:
            删除行数.
        """
        ...

    async def cleanup_for_entity(self, entity_type: str, entity_id: int) -> int:
        """实体硬删级联清理 — delete_by_entity 别名（§5.3，语义一致）.

        Args:
            entity_type: 实体类型（EntityType 值字符串）.
            entity_id: 实体主键（int）.

        Returns:
            删除行数.
        """
        ...
