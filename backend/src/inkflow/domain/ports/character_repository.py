"""角色/分组/关系仓储端口 — 角色管理持久化契约.

CharacterRepositoryProtocol 定义 Character / CharacterGroup /
CharacterRelation 三组 CRUD 操作，基础设施层（SQLite / mock / memory）
实现此 Protocol。仓储层方法入参用 int（与 ORM 层一致），Service 负责
UUID ↔ int 转换（沿用 F1 `_to_int_id` 模式）。

依据: specs/f9-character/spec.md §8.1。
"""

from __future__ import annotations

import builtins
from typing import Protocol

from inkflow.domain.models.character import (
    Character,
    CharacterGroup,
    CharacterRelation,
)


class CharacterRepositoryProtocol(Protocol):
    """角色/分组/关系仓储端口.

    按 spec §2.4: 项目内角色 name 唯一、关系 (from, to, relation_type)
    唯一（全唯一索引）；v1.1 真删语义下删除即物理消失（关系由 DB FK
    CASCADE 级联）。

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``。
    """

    # ── Character ──

    async def add(self, character: Character) -> Character:
        """插入新角色.

        Args:
            character: 待持久化的角色（id 为领域 UUID）.

        Returns:
            持久化后的 Character.
        """
        ...

    async def get(self, character_id: int) -> Character | None:
        """按主键查询角色.

        Args:
            character_id: 角色主键（int，与 ORM 层一致）.

        Returns:
            若命中则返回 Character，否则返回 None.
        """
        ...

    async def get_by_name(self, project_id: int, name: str) -> Character | None:
        """按项目内角色名查询角色.

        Args:
            project_id: 项目主键（int）.
            name: 角色名（已去空白）.

        Returns:
            若命中则返回 Character，否则返回 None.
        """
        ...

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
        """分页查询项目内角色列表，支持搜索与分组过滤.

        Args:
            project_id: 项目主键（int）.
            search: 角色名模糊搜索（可选）.
            group_id: 分组主键过滤（可选）.
            sort_by: 排序字段（updated_at / name / created_at）.
            sort_desc: 是否倒序.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (角色列表, 总数) 元组.
        """
        ...

    async def update(self, character: Character) -> Character:
        """更新角色（按 id 定位）.

        Args:
            character: 含待更新字段的完整角色对象.

        Returns:
            持久化后的 Character.
        """
        ...

    async def hard_delete(self, character_id: int) -> bool:
        """物理删除角色（关系由 DB FK CASCADE 级联删除，v1.1 默认真删语义）.

        Args:
            character_id: 角色主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    # ── CharacterGroup ──

    async def add_group(self, group: CharacterGroup) -> CharacterGroup:
        """插入新分组.

        Args:
            group: 待持久化的分组.

        Returns:
            持久化后的 CharacterGroup.
        """
        ...

    async def get_group(self, group_id: int) -> CharacterGroup | None:
        """按主键查询分组.

        Args:
            group_id: 分组主键（int）.

        Returns:
            若命中则返回 CharacterGroup，否则返回 None.
        """
        ...

    async def list_groups(self, project_id: int) -> builtins.list[CharacterGroup]:
        """查询项目内全部分组.

        Args:
            project_id: 项目主键（int）.

        Returns:
            分组列表（按 sort_order 升序）.
        """
        ...

    async def update_group(self, group: CharacterGroup) -> CharacterGroup:
        """更新分组（按 id 定位）.

        Args:
            group: 含待更新字段的完整分组对象.

        Returns:
            持久化后的 CharacterGroup.
        """
        ...

    async def hard_delete_group(self, group_id: int) -> bool:
        """物理删除分组（成员角色 group_id 置 NULL，v1.1 默认真删语义）.

        Args:
            group_id: 分组主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    # ── CharacterRelation ──

    async def add_relation(self, relation: CharacterRelation) -> CharacterRelation:
        """插入新关系.

        Args:
            relation: 待持久化的关系.

        Returns:
            持久化后的 CharacterRelation.
        """
        ...

    async def get_relation(self, relation_id: int) -> CharacterRelation | None:
        """按主键查询关系.

        Args:
            relation_id: 关系主键（int）.

        Returns:
            若命中则返回 CharacterRelation，否则返回 None.
        """
        ...

    async def get_relation_by_key(
        self, from_id: int, to_id: int, relation_type: str
    ) -> CharacterRelation | None:
        """按 (from, to, relation_type) 唯一键查询关系.

        Args:
            from_id: 起点角色主键（int）.
            to_id: 终点角色主键（int）.
            relation_type: 关系类型.

        Returns:
            若命中则返回 CharacterRelation，否则返回 None.
        """
        ...

    async def list_relations(
        self, project_id: int, character_id: int | None = None
    ) -> builtins.list[CharacterRelation]:
        """查询项目内关系列表，可按角色过滤（双向）.

        Args:
            project_id: 项目主键（int）.
            character_id: 角色主键（可选）；提供时返回该角色作为
                起点或终点的全部关系（双向）.

        Returns:
            关系列表.
        """
        ...

    async def update_relation(self, relation: CharacterRelation) -> CharacterRelation:
        """更新关系（按 id 定位）.

        Args:
            relation: 含待更新字段的完整关系对象.

        Returns:
            持久化后的 CharacterRelation.
        """
        ...

    async def hard_delete_relation(self, relation_id: int) -> bool:
        """物理删除关系（v1.1 默认真删语义）.

        Args:
            relation_id: 关系主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...
