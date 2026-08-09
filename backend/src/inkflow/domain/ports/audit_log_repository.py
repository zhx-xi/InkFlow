"""审计日志仓储端口 — F34 章节审计轻量记录持久化契约.

AuditLogRepositoryProtocol 定义 audit_logs 轻量记录（Q1=C）的 CRUD 契约：
add 插入一条审计记录并返回含 ORM 主键背书的领域实体；latest_pending 取该章
最新 pending 记录（确认状态机前置校验）；confirm 落库确认动作/备注/时间；
list 按项目分页查询（可追溯入口）。基础设施层
（SQLiteAuditLogRepository，infrastructure/database/repositories/
audit_log_repo.py）结构化实现此 Protocol。

依据: specs/f34-chapter-audit/spec.md §8.1/§8.2。
"""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Protocol

from inkflow.domain.models.chapter_audit import AuditLog


class AuditLogRepositoryProtocol(Protocol):
    """审计日志仓储端口（spec §8.1，F15 audit_repo 先例）.

    所有 id 参数/返回均为 int 主键或 uuid.UUID(int=...) 背书形式，
    领域 UUID ↔ ORM int 转换在仓储实现层完成。
    """

    async def add(self, log: AuditLog) -> AuditLog:
        """插入一条审计记录，返回含 ORM 主键背书的 AuditLog.

        Args:
            log: 领域审计记录（id 由仓储按 ORM 自增主键生成）.

        Returns:
            已落库的 AuditLog（id = uuid.UUID(int=orm_id)）.
        """
        ...

    async def latest_pending(self, chapter_id: int) -> AuditLog | None:
        """返回该章最新 pending 审计记录（created_at desc 取最新）.

        Args:
            chapter_id: 章节主键（int）.

        Returns:
            最新 pending 记录；该章无 pending（已全部确认/从未审计）→ None.
        """
        ...

    async def confirm(
        self, log_id: int, *, action: str, note: str, confirmed_at: datetime
    ) -> AuditLog | None:
        """确认审计记录（action 映射为 status + note + confirmed_at 落库）.

        Args:
            log_id: 审计记录主键（int）.
            action: 确认动作（accept→accepted / reject→rejected）.
            note: 确认备注（拒绝原因等）.
            confirmed_at: 确认时间（UTC）.

        Returns:
            更新后的 AuditLog；log_id 不存在 → None.
        """
        ...

    async def list(
        self, project_id: int, *, offset: int = 0, limit: int = 20
    ) -> tuple[builtins.list[AuditLog], int]:
        """按项目分页查询审计记录（created_at desc 最新在前）.

        Args:
            project_id: 项目主键（int）.
            offset: 分页偏移（默认 0）.
            limit: 每页条数（默认 20）.

        Returns:
            (页内 AuditLog 列表, 该项目审计记录总数).
        """
        ...
