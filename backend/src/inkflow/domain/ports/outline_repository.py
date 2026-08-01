"""大纲/情节点/弧线仓储端口 — 大纲管理持久化契约.

OutlineRepositoryProtocol 定义 Outline / PlotPoint / StoryArc 三组
CRUD 操作与级联辅助方法，基础设施层（SQLite / mock / memory）实现此
Protocol。仓储层方法入参用 int（与 ORM 层一致），Service 负责 UUID ↔ int
转换（沿用 F1 `_to_int_id` 模式）。

依据: specs/f11-outline-service/spec.md §8.1。
"""

from __future__ import annotations

import builtins
from typing import Protocol

from inkflow.domain.models.outline import (
    Outline,
    PlotPoint,
    StoryArc,
)


class OutlineRepositoryProtocol(Protocol):
    """大纲/情节点/弧线仓储端口.

    按 spec §2.4: 项目内活动大纲/弧线 name 唯一（partial unique）；
    软删除后同名可复用。大纲软删 → 情节点级联（服务层编排
    soft_delete_points_of / restore_points_of）；弧线软删 → 成员
    arc_id 置 NULL（clear_arc_of_points）。

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9/F10）。
    """

    # ── Outline ──

    async def add(self, outline: Outline) -> Outline:
        """插入新大纲.

        Args:
            outline: 待持久化的大纲（id 为领域 UUID）.

        Returns:
            持久化后的 Outline.
        """
        ...

    async def get(self, outline_id: int) -> Outline | None:
        """按主键查询大纲（不含已软删除）.

        Args:
            outline_id: 大纲主键（int，与 ORM 层一致）.

        Returns:
            若命中则返回 Outline，否则返回 None.
        """
        ...

    async def get_by_name(self, project_id: int, name: str) -> Outline | None:
        """按项目内大纲名查询活动大纲.

        Args:
            project_id: 项目主键（int）.
            name: 大纲名（已去空白）.

        Returns:
            若命中活动大纲则返回 Outline，否则返回 None.
        """
        ...

    async def list(
        self,
        project_id: int,
        search: str | None = None,
        sort_by: str = "updated_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[Outline], int]:
        """分页查询项目内大纲列表，支持名称模糊搜索.

        Args:
            project_id: 项目主键（int）.
            search: 大纲名模糊搜索（可选）.
            sort_by: 排序字段（updated_at / name / sort_order）.
            sort_desc: 是否倒序.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (大纲列表, 总数) 元组.
        """
        ...

    async def update(self, outline: Outline) -> Outline:
        """更新大纲（按 id 定位）.

        Args:
            outline: 含待更新字段的完整大纲对象.

        Returns:
            持久化后的 Outline.
        """
        ...

    async def soft_delete(self, outline_id: int) -> bool:
        """软删除大纲（is_deleted=True）.

        Args:
            outline_id: 大纲主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    async def restore(self, outline_id: int) -> Outline | None:
        """恢复已软删除大纲.

        Args:
            outline_id: 大纲主键（int）.

        Returns:
            恢复后的 Outline，不存在则返回 None.
        """
        ...

    async def hard_delete(self, outline_id: int) -> bool:
        """物理删除大纲（仅用于 force 场景）.

        Args:
            outline_id: 大纲主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    async def soft_delete_points_of(self, outline_id: int) -> None:
        """级联软删除大纲的全部情节点（大纲软删时调用）.

        Args:
            outline_id: 大纲主键（int）.
        """
        ...

    async def restore_points_of(self, outline_id: int) -> None:
        """级联恢复大纲的全部情节点（大纲恢复时调用）.

        Args:
            outline_id: 大纲主键（int）.
        """
        ...

    # ── PlotPoint ──

    async def add_point(self, point: PlotPoint) -> PlotPoint:
        """插入新情节点.

        Args:
            point: 待持久化的情节点（id 为领域 UUID）.

        Returns:
            持久化后的 PlotPoint.
        """
        ...

    async def get_point(self, point_id: int) -> PlotPoint | None:
        """按主键查询情节点（不含已软删除）.

        Args:
            point_id: 情节点主键（int）.

        Returns:
            若命中则返回 PlotPoint，否则返回 None.
        """
        ...

    async def list_points(self, outline_id: int) -> builtins.list[PlotPoint]:
        """列出大纲内全部活动情节点，按 (position ASC, created_at ASC) 稳定排序.

        Args:
            outline_id: 大纲主键（int）.

        Returns:
            情节点列表.
        """
        ...

    async def list_points_by_arc(self, arc_id: int) -> builtins.list[PlotPoint]:
        """列出挂载到指定弧线的全部活动情节点.

        Args:
            arc_id: 弧线主键（int）.

        Returns:
            情节点列表.
        """
        ...

    async def next_position(self, outline_id: int) -> int:
        """计算大纲内下一个排序位置：max(position)+1（无情节点时 = 1）.

        在 add_point 前调用（position=None 时）。

        Args:
            outline_id: 大纲主键（int）.

        Returns:
            下一个 position 值.
        """
        ...

    async def update_point(self, point: PlotPoint) -> PlotPoint:
        """更新情节点（按 id 定位）.

        Args:
            point: 含待更新字段的完整情节点对象.

        Returns:
            持久化后的 PlotPoint.
        """
        ...

    async def soft_delete_point(self, point_id: int) -> bool:
        """软删除情节点（is_deleted=True）.

        Args:
            point_id: 情节点主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    async def restore_point(self, point_id: int) -> PlotPoint | None:
        """恢复已软删除情节点.

        Args:
            point_id: 情节点主键（int）.

        Returns:
            恢复后的 PlotPoint，不存在则返回 None.
        """
        ...

    async def hard_delete_point(self, point_id: int) -> bool:
        """物理删除情节点（仅用于 force 场景）.

        Args:
            point_id: 情节点主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    async def clear_arc_of_points(self, arc_id: int) -> None:
        """弧线删除时把成员情节点的 arc_id 置 NULL（不级联删情节点）.

        Args:
            arc_id: 弧线主键（int）.
        """
        ...

    # ── StoryArc ──

    async def add_arc(self, arc: StoryArc) -> StoryArc:
        """插入新故事弧线.

        Args:
            arc: 待持久化的弧线（id 为领域 UUID）.

        Returns:
            持久化后的 StoryArc.
        """
        ...

    async def get_arc(self, arc_id: int) -> StoryArc | None:
        """按主键查询故事弧线（不含已软删除）.

        Args:
            arc_id: 弧线主键（int）.

        Returns:
            若命中则返回 StoryArc，否则返回 None.
        """
        ...

    async def get_arc_by_name(self, project_id: int, name: str) -> StoryArc | None:
        """按项目内弧线名查询活动故事弧线.

        Args:
            project_id: 项目主键（int）.
            name: 弧线名（已去空白）.

        Returns:
            若命中活动弧线则返回 StoryArc，否则返回 None.
        """
        ...

    async def list_arcs(self, project_id: int) -> builtins.list[StoryArc]:
        """列出项目内全部活动故事弧线，按 name 升序.

        Args:
            project_id: 项目主键（int）.

        Returns:
            弧线列表.
        """
        ...

    async def update_arc(self, arc: StoryArc) -> StoryArc:
        """更新故事弧线（按 id 定位）.

        Args:
            arc: 含待更新字段的完整弧线对象.

        Returns:
            持久化后的 StoryArc.
        """
        ...

    async def soft_delete_arc(self, arc_id: int) -> bool:
        """软删除故事弧线（is_deleted=True）.

        Args:
            arc_id: 弧线主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    async def restore_arc(self, arc_id: int) -> StoryArc | None:
        """恢复已软删除故事弧线.

        Args:
            arc_id: 弧线主键（int）.

        Returns:
            恢复后的 StoryArc，不存在则返回 None.
        """
        ...

    async def hard_delete_arc(self, arc_id: int) -> bool:
        """物理删除故事弧线（仅用于 force 场景）.

        Args:
            arc_id: 弧线主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...
