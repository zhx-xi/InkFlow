"""时间线事件仓储端口 — 时间线管理持久化契约.

TimelineRepositoryProtocol 定义 TimelineEvent 的 CRUD 操作与叙事位置辅助
方法，基础设施层（SQLite / mock / memory）实现此 Protocol。仓储层方法入参
用 int（与 ORM 层一致），Service 负责 UUID ↔ int 转换（沿用 F1
`_to_int_id` 模式）。

依据: specs/f12-timeline/spec.md §8.1。
"""

from __future__ import annotations

import builtins
from typing import Protocol

from inkflow.domain.models.timeline import TimelineEvent


class TimelineRepositoryProtocol(Protocol):
    """时间线事件仓储端口.

    按 spec §2: 单实体（无子实体、无唯一约束）；事件列表默认按
    narrative_position ASC 排序；双线视图/一致性检查需要全量事件
    （list_all）。v1.1 真删语义下删除即物理消失。

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9/F10/F11）。
    """

    # ── TimelineEvent ──

    async def add(self, event: TimelineEvent) -> TimelineEvent:
        """插入新事件.

        Args:
            event: 待持久化的事件（id 为领域 UUID）.

        Returns:
            持久化后的 TimelineEvent.
        """
        ...

    async def get(self, event_id: int) -> TimelineEvent | None:
        """按主键查询事件.

        Args:
            event_id: 事件主键（int，与 ORM 层一致）.

        Returns:
            若命中则返回 TimelineEvent，否则返回 None.
        """
        ...

    async def list(
        self,
        project_id: int,
        search: str | None = None,
        sort_by: str = "narrative_position",
        sort_desc: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[TimelineEvent], int]:
        """分页查询项目内事件列表，支持标题模糊搜索与排序.

        Args:
            project_id: 项目主键（int）.
            search: 事件标题模糊搜索（可选）.
            sort_by: 排序字段（narrative_position / time_value / created_at /
                updated_at）.
            sort_desc: 是否倒序（默认升序，narrative_position 小者在前）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (事件列表, 总数) 元组.
        """
        ...

    async def list_all(self, project_id: int) -> builtins.list[TimelineEvent]:
        """列出项目内全部事件，按 (narrative_position ASC, created_at ASC) 稳定排序.

        双线视图/一致性检查直接消费此全量结果.

        Args:
            project_id: 项目主键（int）.

        Returns:
            事件列表.
        """
        ...

    async def list_by_chapter(
        self, project_id: int, chapter_id: int
    ) -> builtins.list[TimelineEvent]:
        """列出项目内事件中 source_chapter_id 等于指定章的事件.

        F14 提取合并用（spec §5.5 合并策略）: 按 title 比对由服务层完成，
        本方法只负责按来源章拉取候选集。按 (narrative_position ASC,
        created_at ASC) 排序。

        Args:
            project_id: 项目主键（int）.
            chapter_id: 来源章节主键（int，与 ORM 层一致）.

        Returns:
            指定来源章的事件列表.
        """
        ...

    async def next_position(self, project_id: int) -> int:
        """计算项目内下一个叙事位置：max(narrative_position)+1（无事件时 = 1）.

        在 add 前调用（narrative_position=None 时）.

        Args:
            project_id: 项目主键（int）.

        Returns:
            下一个 narrative_position 值.
        """
        ...

    async def update(self, event: TimelineEvent) -> TimelineEvent:
        """更新事件（按 id 定位）.

        Args:
            event: 含待更新字段的完整事件对象.

        Returns:
            持久化后的 TimelineEvent.
        """
        ...

    async def hard_delete(self, event_id: int) -> bool:
        """物理删除事件（v1.1 默认真删语义）.

        Args:
            event_id: 事件主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...
