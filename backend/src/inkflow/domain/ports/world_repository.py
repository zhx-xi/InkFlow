"""世界观条目仓储端口 — 世界观管理持久化契约.

WorldRepositoryProtocol 定义 WorldSetting 的 CRUD 操作与类别聚合，
基础设施层（SQLite / mock / memory）实现此 Protocol。仓储层方法入参
用 int（与 ORM 层一致），Service 负责 UUID ↔ int 转换（沿用 F1
`_to_int_id` 模式）。

依据: specs/f10-world-service/spec.md §8.1。
"""

from __future__ import annotations

import builtins
from typing import Protocol

from inkflow.domain.models.world import WorldSetting


class WorldRepositoryProtocol(Protocol):
    """世界观条目仓储端口.

    按 spec §2.4: 项目内活动条目 name 唯一（partial unique）；
    软删除后同名可复用。list_categories 聚合活动条目类别计数。

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9）。
    """

    # ── WorldSetting ──

    async def add(self, setting: WorldSetting) -> WorldSetting:
        """插入新条目.

        Args:
            setting: 待持久化的条目（id 为领域 UUID）.

        Returns:
            持久化后的 WorldSetting.
        """
        ...

    async def get(self, setting_id: int) -> WorldSetting | None:
        """按主键查询条目（不含已软删除）.

        Args:
            setting_id: 条目主键（int，与 ORM 层一致）.

        Returns:
            若命中则返回 WorldSetting，否则返回 None.
        """
        ...

    async def get_by_name(self, project_id: int, name: str) -> WorldSetting | None:
        """按项目内条目名查询活动条目；跨层同名多条时返回最早创建
        （created_at ASC）的一条（spec §2.4 确定性声明）.

        Args:
            project_id: 项目主键（int）.
            name: 条目名（已去空白）.

        Returns:
            若命中活动条目则返回 WorldSetting，否则返回 None.
        """
        ...

    async def list(
        self,
        project_id: int,
        search: str | None = None,
        category: str | None = None,
        sort_by: str = "updated_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
        parent_id: int | None = None,
        top_level_only: bool = False,
    ) -> tuple[builtins.list[WorldSetting], int]:
        """分页查询项目内条目列表，支持搜索与类别过滤（Q3=A 列表 parent_id 过滤）.

        Args:
            project_id: 项目主键（int）.
            search: 条目名模糊搜索（可选）.
            category: 类别精确过滤（可选，不含已软删除条目）.
            sort_by: 排序字段（updated_at / name / created_at）.
            sort_desc: 是否倒序.
            offset: 分页偏移.
            limit: 分页大小.
            parent_id: 直接父级过滤（可选；top_level_only=False 时生效）.
            top_level_only: True 只返回顶层（parent_id IS NULL）.

        Returns:
            (条目列表, 总数) 元组.
        """
        ...

    async def list_categories(self, project_id: int) -> builtins.list[tuple[str, int]]:
        """聚合项目内活动条目的类别计数（排除空类别）.

        Args:
            project_id: 项目主键（int）.

        Returns:
            (类别, 条目数) 列表，按计数降序、类别名升序.
        """
        ...

    async def update(self, setting: WorldSetting) -> WorldSetting:
        """更新条目（按 id 定位）.

        Args:
            setting: 含待更新字段的完整条目对象.

        Returns:
            持久化后的 WorldSetting.
        """
        ...

    async def soft_delete(self, setting_id: int) -> bool:
        """软删除条目（is_deleted=True）.

        Args:
            setting_id: 条目主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    async def restore(self, setting_id: int) -> WorldSetting | None:
        """恢复已软删除条目.

        Args:
            setting_id: 条目主键（int）.

        Returns:
            恢复后的 WorldSetting，不存在则返回 None.
        """
        ...

    async def hard_delete(self, setting_id: int) -> bool:
        """物理删除条目（仅用于 force 场景）.

        Args:
            setting_id: 条目主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    async def get_by_parent_and_name(
        self, project_id: int, parent_id: int | None, name: str
    ) -> WorldSetting | None:
        """按 (project_id, parent_id, name) 查询活动条目（parent_id=None = 顶层）——
        同级唯一校验用（spec §5.1）。"""
        ...

    async def collect_ancestor_ids(self, setting_id: int) -> builtins.list[int]:
        """祖先链 id 列表，**不含自身**（父链，从近到远 [父, 祖父, ...]；
        用于循环防护：检查新父的祖先链是否含自身，spec §5.2）。"""
        ...

    async def list_descendants(self, setting_id: int) -> builtins.list[WorldSetting]:
        """子树（**含自身**），层序（父先子后，同层 created_at ASC）；
        仅活动条目（is_deleted=0）；不存在/软删 id → 空列表（spec §5.3）。"""
        ...

    async def hard_delete_many(self, setting_ids: builtins.list[int]) -> int:
        """单事务原子物理删除（DELETE WHERE id IN (...)），返回删除行数；
        空列表 → 0 不报错；不存在的 id 不影响计数（spec §5.5 级联真删）。"""
        ...

    async def delete_with_reparent(self, setting_id: int, reparent_to: int) -> bool:
        """单事务: UPDATE 直接子地点 parent_id=reparent_to WHERE parent_id=setting_id
        + DELETE 自身；返回自身是否被删（不存在 → False，spec §5.5 reparent）。"""
        ...
