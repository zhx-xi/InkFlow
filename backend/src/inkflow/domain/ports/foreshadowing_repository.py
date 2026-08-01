"""伏笔档案仓储端口 — 伏笔管理持久化契约.

ForeshadowingRepositoryProtocol 定义 Foreshadowing 的 CRUD 操作与 F6 注入
集合查询（list_open），基础设施层（SQLite / mock / memory）实现此
Protocol。仓储层方法入参用 int（与 ORM 层一致），Service 负责 UUID ↔ int
转换（沿用 F1 `_to_int_id` 模式）。

事件校验（event_id 存在性 + 同项目）不在本端口：复用 F12
TimelineRepositoryProtocol.get（Service 层构造注入，spec §8.1）。

依据: specs/f13-foreshadowing-service/spec.md §8.1。
"""

from __future__ import annotations

import builtins
from typing import Protocol

from inkflow.domain.models.foreshadowing import Foreshadowing


class ForeshadowingRepositoryProtocol(Protocol):
    """伏笔档案仓储端口.

    按 spec §2: 单实体；项目内活动伏笔 title 唯一（partial unique）；
    软删除后同名可复用。list_open 供 F6 数据源查询注入集合
    （status=open 且未软删除，按 (priority DESC, updated_at DESC) 排序）。

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9/F10/F11/F12）。
    """

    # ── Foreshadowing ──

    async def add(self, f: Foreshadowing) -> Foreshadowing:
        """插入新伏笔.

        Args:
            f: 待持久化的伏笔（id 为领域 UUID）.

        Returns:
            持久化后的 Foreshadowing.
        """
        ...

    async def get(self, foreshadowing_id: int) -> Foreshadowing | None:
        """按主键查询伏笔（不含已软删除）.

        Args:
            foreshadowing_id: 伏笔主键（int，与 ORM 层一致）.

        Returns:
            若命中则返回 Foreshadowing，否则返回 None.
        """
        ...

    async def get_by_title(self, project_id: int, title: str) -> Foreshadowing | None:
        """按 (project_id, title) 查询活动伏笔（不含已软删除）.

        同名唯一性检查用（spec §2.3 partial unique 语义）：软删除后同名
        可复用，故仅命中 is_deleted=False 的活动条目.

        Args:
            project_id: 项目主键（int）.
            title: 伏笔名.

        Returns:
            若命中活动伏笔则返回 Foreshadowing，否则返回 None.
        """
        ...

    async def list(
        self,
        project_id: int,
        search: str | None = None,
        status: str | None = None,
        sort_by: str = "priority",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[Foreshadowing], int]:
        """分页查询项目内活动伏笔列表，支持标题模糊搜索、状态过滤与排序.

        Args:
            project_id: 项目主键（int）.
            search: 伏笔名不区分大小写子串匹配（可选）.
            status: 状态精确过滤（open / resolved；不传 = 全部活动伏笔）.
            sort_by: 排序字段（priority / title / status / updated_at /
                created_at；伏笔语境下默认 priority，与注入顺序一致）.
            sort_desc: 是否倒序（默认 True，priority 大者在前；priority
                相等时按 updated_at DESC 兜底稳定排序，spec §6.2）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (伏笔列表, 总数) 元组.
        """
        ...

    async def list_open(self, project_id: int) -> builtins.list[Foreshadowing]:
        """列出项目内全部未回收伏笔（status=open 且未软删除），供 F6 注入消费.

        返回顺序即 F6 注入顺序：按 (priority DESC, updated_at DESC) 排序
        （spec §6.2/§6.3；priority 为注入优先级键，大者先注入；相等时按
        updated_at 兜底稳定排序）。F6 dynamic 层直接消费此结果（spec §5.3）.

        Args:
            project_id: 项目主键（int）.

        Returns:
            未回收伏笔列表.
        """
        ...

    async def update(self, f: Foreshadowing) -> Foreshadowing:
        """更新伏笔（按 id 定位）.

        Args:
            f: 含待更新字段的完整伏笔对象.

        Returns:
            持久化后的 Foreshadowing.
        """
        ...

    async def soft_delete(self, foreshadowing_id: int) -> bool:
        """软删除伏笔（is_deleted=True）.

        Args:
            foreshadowing_id: 伏笔主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    async def restore(self, foreshadowing_id: int) -> Foreshadowing | None:
        """恢复已软删除伏笔（原 status/resolved_at 原样保留，spec §2.4）.

        Args:
            foreshadowing_id: 伏笔主键（int）.

        Returns:
            恢复后的 Foreshadowing，不存在则返回 None.
        """
        ...

    async def hard_delete(self, foreshadowing_id: int) -> bool:
        """物理删除伏笔（仅用于 force 场景）.

        Args:
            foreshadowing_id: 伏笔主键（int）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...
