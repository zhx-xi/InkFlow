"""SQLite 会话仓储 —— 实现 SessionRepositoryProtocol 全部方法.

转换函数（_orm_to_domain / _domain_to_orm / int↔UUID 辅助）按项目惯例
放在本仓储层（参照 timeline_repo.py / foreshadowing_repo.py）。

语义（spec §2/§6/§7）：
- 双实体 CRUD：会话列表按 created_at DESC（最新在前，spec §6.2）；
  日志按 seq ASC 稳定排序（履历顺序）
- 过滤组合: session_type / status / project_id / search(title icontains)
  任意组合 AND；全缺省 = 全部未归档会话（is_deleted=0）
- 软删除 = UPDATE is_deleted=1；restore 解除归档；hard_delete 物理删除
  （日志随 FK CASCADE 级联删除，spec §2.5）
- get 一律排除已归档会话；list 默认排除（include_deleted=True 时含归档全量）；
  list_include_deleted 详情可追档
  （归档也可读，spec §7 #7）
- 日志 seq 分配: next_seq = 会话内 max(seq)+1（无日志 = 1，会话间隔离）
- list_logs 不因会话归档过滤（归档 404 由服务层判定，仓储只做物理查询
  ——履历保留契约，spec §2.2）
- (session_id, seq) 唯一约束: 重复 seq 插入 → IntegrityError（spec §7 #13）

注意: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/session_repository.py 一致）。
"""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime
from typing import overload

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.session import (
    LogLevel,
    Session,
    SessionLogEntry,
    SessionStatus,
    SessionType,
)
from inkflow.infrastructure.database.models.session import SessionLogORM, SessionORM


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _int_to_uuid(value: int | uuid.UUID | None) -> uuid.UUID | None:
    """DB int → 领域 UUID，F1 映射: uuid.UUID(int=...)."""
    if value is None:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(int=value)


def _uuid_to_int(value: uuid.UUID | int) -> int:
    """领域 UUID → DB int，F1 映射: uuid.int."""
    return value.int if isinstance(value, uuid.UUID) else int(value)


@overload
def _as_utc(value: datetime) -> datetime: ...


@overload
def _as_utc(value: None) -> None: ...


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite DateTime(timezone=True) 读回 naive datetime，统一补 UTC 时区.

    测试契约要求领域对象「时区感知」（docstring: 当前 UTC 时间）：
    落库值均为 UTC，读回后对 naive 值做 replace(tzinfo=UTC) 归一化。
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _orm_to_domain(orm: SessionORM) -> Session:
    """会话 ORM 行 → 领域实体（int PK → UUID）."""
    return Session(
        id=uuid.UUID(int=orm.id),
        session_type=SessionType(orm.session_type),
        status=SessionStatus(orm.status),
        project_id=_int_to_uuid(orm.project_id),
        title=orm.title,
        description=orm.description,
        context=orm.context or {},
        result=orm.result or {},
        error=orm.error,
        started_at=_as_utc(orm.started_at),
        paused_at=_as_utc(orm.paused_at),
        completed_at=_as_utc(orm.completed_at),
        is_deleted=orm.is_deleted,
        created_at=_as_utc(orm.created_at),
        updated_at=_as_utc(orm.updated_at),
    )


def _domain_to_orm(domain: Session) -> SessionORM:
    """会话领域实体 → ORM 行（UUID → int；id 由 DB 自增分配，不落库）."""
    return SessionORM(
        session_type=domain.session_type.value,
        status=domain.status.value,
        project_id=(_uuid_to_int(domain.project_id) if domain.project_id is not None else None),
        title=domain.title,
        description=domain.description,
        context=domain.context,
        result=domain.result,
        error=domain.error,
        started_at=domain.started_at,
        paused_at=domain.paused_at,
        completed_at=domain.completed_at,
        is_deleted=domain.is_deleted,
        created_at=domain.created_at,
        updated_at=domain.updated_at,
    )


def _log_orm_to_domain(orm: SessionLogORM) -> SessionLogEntry:
    """日志 ORM 行 → 领域实体（int PK / session_id → UUID）."""
    return SessionLogEntry(
        id=uuid.UUID(int=orm.id),
        session_id=uuid.UUID(int=orm.session_id),
        seq=orm.seq,
        level=LogLevel(orm.level),
        message=orm.message,
        payload=orm.payload or {},
        created_at=_as_utc(orm.created_at),
    )


def _log_domain_to_orm(domain: SessionLogEntry) -> SessionLogORM:
    """日志领域实体 → ORM 行（UUID → int；id 由 DB 自增分配，不落库）."""
    return SessionLogORM(
        session_id=_uuid_to_int(domain.session_id),
        seq=domain.seq,
        level=domain.level.value,
        message=domain.message,
        payload=domain.payload,
        created_at=domain.created_at,
    )


class SQLiteSessionRepository:
    """SQLite 会话仓储 —— 实现 SessionRepositoryProtocol 接口."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ──── Session ────

    async def add(self, session: Session) -> Session:
        """插入新会话（id 由 DB 自增分配，读回时映射为 UUID）."""
        orm = _domain_to_orm(session)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, session_id: int) -> Session | None:
        """按主键查询会话（不含已归档）."""
        stmt = select(SessionORM).where(
            SessionORM.id == session_id,
            ~SessionORM.is_deleted,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

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

        include_deleted=False 时全缺省 = 全部未归档会话（既有语义）；True = 活动 + 归档
        全量（#486 会话页需列出/恢复已归档会话）；total = 未分页过滤总数；
        列表按 created_at DESC 排序（最新在前，spec §6.2）.

        Args:
            session_type: 会话类型精确过滤（writing / task；不传 = 全部）.
            status: 状态精确过滤（active / paused / completed / failed；不传 = 全部）.
            project_id: 项目主键精确过滤（不传 = 全部；含 project_id 为空的全局会话）.
            search: 标题不区分大小写子串匹配（可选，不匹配 description）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (会话列表, 总数) 元组；列表按 created_at DESC 排序.
        """
        base = select(SessionORM)
        if not include_deleted:
            base = base.where(~SessionORM.is_deleted)

        if session_type is not None:
            base = base.where(SessionORM.session_type == session_type)
        if status is not None:
            base = base.where(SessionORM.status == status)
        if project_id is not None:
            base = base.where(SessionORM.project_id == project_id)
        if search:
            base = base.where(SessionORM.title.ilike(f"%{search}%"))

        # 总数（分页前）
        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        # 排序 + 分页
        stmt = base.order_by(SessionORM.created_at.desc()).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [_orm_to_domain(o) for o in orms], total

    async def list_include_deleted(self, session_id: int) -> Session | None:
        """按主键查询会话（含已归档；详情可追档，归档也可读）."""
        stmt = select(SessionORM).where(SessionORM.id == session_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def update(self, session: Session) -> Session:
        """更新会话（按 id 定位，updated_at 自动刷新）.

        Raises:
            ValueError: 会话不存在
        """
        session_id = _uuid_to_int(session.id)
        stmt = (
            sa_update(SessionORM)
            .where(SessionORM.id == session_id)
            .values(
                session_type=session.session_type.value,
                status=session.status.value,
                project_id=(
                    _uuid_to_int(session.project_id) if session.project_id is not None else None
                ),
                title=session.title,
                description=session.description,
                context=session.context,
                result=session.result,
                error=session.error,
                started_at=session.started_at,
                paused_at=session.paused_at,
                completed_at=session.completed_at,
                updated_at=_utcnow(),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        if result.rowcount == 0:  # type: ignore[attr-defined]  # SQLAlchemy Result 类未声明 rowcount（属性在底层 cursor）
            raise ValueError(f"Session {session_id} not found")

        stmt2 = select(SessionORM).where(SessionORM.id == session_id)
        result2 = await self._session.execute(stmt2)
        orm = result2.scalar_one_or_none()
        if orm is None:
            raise ValueError(f"Session {session_id} not found after update")
        return _orm_to_domain(orm)

    async def soft_delete(self, session_id: int) -> bool:
        """归档会话（is_deleted=True）.

        Returns:
            True 表示成功归档一条记录，False 表示未找到/已归档
        """
        stmt = (
            sa_update(SessionORM)
            .where(SessionORM.id == session_id, ~SessionORM.is_deleted)
            .values(is_deleted=True, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return bool(result.rowcount > 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 类未声明 rowcount（属性在底层 cursor）

    async def restore(self, session_id: int) -> Session | None:
        """解除已归档会话（is_deleted=False）.

        Returns:
            解除后的 Session；记录不存在或未归档时返回 None（重复操作无副作用）
        """
        stmt = (
            sa_update(SessionORM)
            .where(SessionORM.id == session_id, SessionORM.is_deleted)
            .values(is_deleted=False, updated_at=_utcnow())
        )
        result = await self._session.execute(stmt)
        if result.rowcount == 0:  # type: ignore[attr-defined]  # SQLAlchemy Result 类未声明 rowcount（属性在底层 cursor）
            await self._session.commit()
            return None
        await self._session.commit()
        return await self.get(session_id)

    async def hard_delete(self, session_id: int) -> bool:
        """物理删除会话（日志随 FK CASCADE 级联删除）.

        Returns:
            True 表示删除成功，False 表示不存在
        """
        stmt = select(SessionORM).where(SessionORM.id == session_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return False
        await self._session.delete(orm)
        await self._session.commit()
        return True

    # ──── SessionLogEntry ────

    async def add_log(self, entry: SessionLogEntry) -> SessionLogEntry:
        """插入日志条目（seq 由服务层经 next_seq 分配）."""
        orm = _log_domain_to_orm(entry)
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _log_orm_to_domain(orm)

    async def next_seq(self, session_id: int) -> int:
        """计算会话内下一条日志序号（max(seq)+1；无日志时 = 1）."""
        stmt = select(func.coalesce(func.max(SessionLogORM.seq), 0) + 1).where(
            SessionLogORM.session_id == session_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def list_logs(
        self,
        session_id: int,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[SessionLogEntry], int]:
        """分页查询会话日志，按 seq ASC 稳定排序（不因会话归档过滤）.

        Args:
            session_id: 会话主键（int，与 ORM 层一致）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (日志列表, 总数) 元组.
        """
        base = select(SessionLogORM).where(SessionLogORM.session_id == session_id)

        # 总数（分页前）
        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        # 排序 + 分页
        stmt = base.order_by(SessionLogORM.seq.asc()).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        orms = result.scalars().all()
        return [_log_orm_to_domain(o) for o in orms], total

    async def count_logs(self, session_id: int) -> int:
        """统计会话日志条数（SessionView.log_count）."""
        stmt = (
            select(func.count())
            .select_from(SessionLogORM)
            .where(SessionLogORM.session_id == session_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def last_log(self, session_id: int) -> SessionLogEntry | None:
        """查询会话最新日志条目（SessionView.last_log；无日志时返回 None）."""
        stmt = (
            select(SessionLogORM)
            .where(SessionLogORM.session_id == session_id)
            .order_by(SessionLogORM.seq.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _log_orm_to_domain(orm) if orm else None
