"""会话仓储端口 — 会话管理持久化外契约.

SessionRepositoryProtocol 定义 Session 与 SessionLogEntry 的持久化操作
（CRUD + 过滤列表 + 归档/解除/真实删除 + 日志 seq 分配与查询），基础
设施层（SQLite / mock / memory）实现本 Protocol。仓储层方法入参用 int
（与 ORM 层一致），Service 负责 UUID ↔ int 转换（沿用 F1 `_to_int_id` 模式）。

依据: specs/f24-session/spec.md §8.2。
"""

from __future__ import annotations

import builtins
from typing import Protocol

from inkflow.domain.models.session import Session, SessionLogEntry


class SessionRepositoryProtocol(Protocol):
    """会话仓储端口.

    按 spec §2: 双实体（Session + SessionLogEntry）；会话列表按
    created_at DESC；日志按 seq ASC；归档会话不进入列表查询。
    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9-F13）。
    """

    # ── Session ──

    async def add(self, session: Session) -> Session:
        """插入新会话.

        Args:
            session: 待持久化的会话（id 为领域 UUID）.

        Returns:
            持久化后的 Session.
        """
        ...

    async def get(self, session_id: int) -> Session | None:
        """按主键查询会话（不含已归档）.

        Args:
            session_id: 会话主键（int，与 ORM 层一致）.

        Returns:
            若命中则返回 Session，否则返回 None.
        """
        ...

    async def list(
        self,
        session_type: str | None = None,
        status: str | None = None,
        project_id: int | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 50,
        include_deleted: bool = False,
    ) -> tuple[builtins.list[Session], int]:
        """分页查询会话列表，支持类型/状态/项目过滤与标题模糊搜索.

        Args:
            session_type: 会话类型精确过滤（writing / task；不传 = 全部）.
            status: 状态精确过滤（active / paused / completed / failed；不传 = 全部）.
            project_id: 项目主键精确过滤（不传 = 全部；含 project_id 为空的全局会话）.
            search: 标题不区分大小写子串匹配（可选）.
            offset: 分页偏移.
            limit: 分页大小.
            include_deleted: True = 含已归档全量（活动 + 归档一起返回）；默认 False
                保持既有活动列表语义.

        Returns:
            (会话列表, 总数) 元组；列表按 created_at DESC 排序.
        """
        ...

    async def list_include_deleted(self, session_id: int) -> Session | None:
        """按主键查询会话（含已归档；详情可追溯，归档也可读）.

        Args:
            session_id: 会话主键（int，与 ORM 层一致）.

        Returns:
            若命中则返回 Session（含已归档），否则返回 None.
        """
        ...

    async def update(self, session: Session) -> Session:
        """更新会话（按 id 定位）.

        Args:
            session: 含待更新字段的完整会话对象.

        Returns:
            持久化后的 Session.
        """
        ...

    async def soft_delete(self, session_id: int) -> bool:
        """归档会话（is_deleted=True）.

        Args:
            session_id: 会话主键（int，与 ORM 层一致）.

        Returns:
            是否归档成功（不存在返回 False）.
        """
        ...

    async def restore(self, session_id: int) -> Session | None:
        """解除已归档会话（is_deleted=False）.

        Args:
            session_id: 会话主键（int，与 ORM 层一致）.

        Returns:
            解除后的 Session，不存在则返回 None.
        """
        ...

    async def hard_delete(self, session_id: int) -> bool:
        """物理删除会话（日志随 FK CASCADE 级联删除；仅用于已归档再删 / force 场景）.

        Args:
            session_id: 会话主键（int，与 ORM 层一致）.

        Returns:
            是否删除成功（不存在返回 False）.
        """
        ...

    # ── SessionLogEntry ──

    async def add_log(self, entry: SessionLogEntry) -> SessionLogEntry:
        """插入日志条目（seq 由服务层经 next_seq 分配）.

        Args:
            entry: 待持久化的日志条目.

        Returns:
            持久化后的 SessionLogEntry.
        """
        ...

    async def next_seq(self, session_id: int) -> int:
        """计算会话内下一条日志序号（max(seq)+1；无日志时 = 1）.

        Args:
            session_id: 会话主键（int，与 ORM 层一致）.

        Returns:
            会话内递增序号.
        """
        ...

    async def list_logs(
        self,
        session_id: int,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[SessionLogEntry], int]:
        """分页查询会话日志，按 seq ASC 稳定排序.

        Args:
            session_id: 会话主键（int，与 ORM 层一致）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (日志列表, 总数) 元组.
        """
        ...

    async def count_logs(self, session_id: int) -> int:
        """统计会话日志条数（SessionView.log_count）.

        Args:
            session_id: 会话主键（int，与 ORM 层一致）.

        Returns:
            日志条数.
        """
        ...

    async def last_log(self, session_id: int) -> SessionLogEntry | None:
        """查询会话最新日志条目（SessionView.last_log；无日志时返回 None）.

        Args:
            session_id: 会话主键（int，与 ORM 层一致）.

        Returns:
            最新日志条目（seq 最大者），无日志则返回 None.
        """
        ...
