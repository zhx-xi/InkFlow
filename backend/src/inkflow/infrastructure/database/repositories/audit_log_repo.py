"""SQLite 审计日志仓储 — 实现 AuditLogRepositoryProtocol 的全部方法."""

from __future__ import annotations

import builtins
import uuid
from datetime import datetime
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.chapter_audit import AuditLog
from inkflow.infrastructure.database.models.audit_log import AuditLogORM


def _log_orm_to_domain(orm: AuditLogORM) -> AuditLog:
    """ORM → 领域模型：int 主键背书为 uuid.UUID(int=...).

    转换规则与既有仓储一致（summary_repo.py 先例）：领域 UUID 由 ORM
    int 主键背书生成，add 传入的 log.id 不直接落库（由自增主键生成）。
    """
    return AuditLog(
        id=uuid.UUID(int=orm.id),
        project_id=uuid.UUID(int=orm.project_id),
        chapter_id=uuid.UUID(int=orm.chapter_id) if orm.chapter_id is not None else None,
        chapter_title=orm.chapter_title,
        # status 由 ORM str 列读出，运行时恒为三态之一（service/confirm 写入前映射），
        # mypy 需显式收窄为领域 Literal（mypy 无法从 Mapped[str] 推断字面量）
        status=cast(Literal["pending", "accepted", "rejected"], orm.status),
        severity_summary=orm.severity_summary,
        summary=orm.summary,
        degraded=orm.degraded,
        note=orm.note,
        created_at=orm.created_at,
        confirmed_at=orm.confirmed_at,
    )


class SQLiteAuditLogRepository:
    """SQLite 审计日志仓储实现（AuditLogRepositoryProtocol 结构化子类型）.

    不显式继承 Protocol（结构化子类型），由 F34 服务层按
    AuditLogRepositoryProtocol 注入使用（session 注入 + 轻量 CRUD）。
    """

    def __init__(self, session: AsyncSession) -> None:
        """以异步会话构造仓储（注入方式与既有仓储一致）."""
        self._session = session

    async def add(self, log: AuditLog) -> AuditLog:
        """插入一条审计记录并返回含 ORM 主键背书的领域实体.

        Args:
            log: 领域审计记录（id 为占位，以 ORM 自增主键生成为准）.

        Returns:
            已落库的 AuditLog（id = uuid.UUID(int=orm_id)）.
        """
        orm = AuditLogORM(
            project_id=log.project_id.int,
            chapter_id=log.chapter_id.int if log.chapter_id else None,
            chapter_title=log.chapter_title,
            status=log.status,
            severity_summary=log.severity_summary,
            summary=log.summary,
            degraded=log.degraded,
            note=log.note,
            created_at=log.created_at,
            confirmed_at=log.confirmed_at,
        )
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _log_orm_to_domain(orm)

    async def latest_pending(self, chapter_id: int) -> AuditLog | None:
        """返回该章最新 pending 审计记录（created_at desc，id desc 兜底）.

        Args:
            chapter_id: 章节主键（int，与 ORM 层一致）.

        Returns:
            最新 pending 记录；该章无 pending（已全部确认/从未审计）→ None.
        """
        stmt = (
            select(AuditLogORM)
            .where(
                AuditLogORM.chapter_id == chapter_id,
                AuditLogORM.status == "pending",
            )
            .order_by(AuditLogORM.created_at.desc(), AuditLogORM.id.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _log_orm_to_domain(orm) if orm else None

    async def confirm(
        self, log_id: int, *, action: str, note: str, confirmed_at: datetime
    ) -> AuditLog | None:
        """确认审计记录：action 映射为 status（accept→accepted / reject→rejected）落库.

        Args:
            log_id: 审计记录主键（int）.
            action: 确认动作（accept=接受 / reject=拒绝，映射为落库状态）.
            note: 确认备注（拒绝原因等，写入 audit_logs.note）.
            confirmed_at: 确认时间（UTC）.

        Returns:
            更新后的 AuditLog；log_id 不存在 → None.
        """
        stmt = select(AuditLogORM).where(AuditLogORM.id == log_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        orm.status = "accepted" if action == "accept" else "rejected"
        orm.note = note
        orm.confirmed_at = confirmed_at
        await self._session.commit()
        await self._session.refresh(orm)
        return _log_orm_to_domain(orm)

    async def list(
        self, project_id: int, *, offset: int = 0, limit: int = 20
    ) -> tuple[builtins.list[AuditLog], int]:
        """按项目分页查询审计记录（created_at desc 最新在前）.

        Args:
            project_id: 项目主键（int，与 ORM 层一致）.
            offset: 分页偏移（默认 0）.
            limit: 每页条数（默认 20）.

        Returns:
            (页内 AuditLog 列表, 该项目审计记录总数).
        """
        stmt = (
            select(AuditLogORM)
            .where(AuditLogORM.project_id == project_id)
            .order_by(AuditLogORM.created_at.desc(), AuditLogORM.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        items = [_log_orm_to_domain(o) for o in result.scalars().all()]
        total_stmt = (
            select(func.count())
            .select_from(AuditLogORM)
            .where(AuditLogORM.project_id == project_id)
        )
        total = (await self._session.execute(total_stmt)).scalar_one()
        return items, total
