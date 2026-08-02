"""SQLite 提取运行仓储 — 实现 ExtractionRunRepositoryProtocol 全部方法.

转换函数（_orm_to_domain / _domain_to_orm / _uuid_to_int 辅助）按项目惯例
放在本仓储层（参照 foreshadowing_repo.py / timeline_repo.py / character_repo.py）。

语义（spec §2.3/§8.1）:
- 每 (project_id, type, source_key) 一行最新状态（upsert）——
  「每源一行最新状态，不是历史表」（历史变更审计归 F15）
- upsert 用 SQLite ``INSERT ... ON CONFLICT DO UPDATE`` 保证原子性
  （并发重复提取时最后写入者胜——单用户本地工具，无竞态处理，同 F9-F13）;
  冲突时字段整体覆盖（含 run_at 更新），行数不增、id 不变
- get 供门面增量判定（§5.2）：命中 = 该源已有 run 记录，比 content_hash
  决定 skip；未命中 = 首次提取
- list 按 run_at DESC 排序（最新在前） + type 精确过滤（不传 = 全部）+
  分页，供 runs 查询（§3.3）
- FK 级联: 项目物理删除 → run 级联物理删除（DB FK CASCADE）；
  章节删除后 run 行保留（孤儿行，不影响任何逻辑）
- 仓储层入参用 int（与 ORM 层一致），Service 负责 UUID ↔ int 转换
  （沿用 F1 `_to_int_id` 模式）；ExtractionRun.project_id 为领域 UUID，
  落库时经 _uuid_to_int 映射为 int

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与 domain/ports/extraction_run_repository.py 一致）。
"""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.extraction import (
    ExtractionRun,
    ExtractionStatus,
    ExtractionType,
)
from inkflow.infrastructure.database.models.extraction_run import ExtractionRunORM


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _uuid_to_int(value: uuid.UUID | int) -> int:
    """领域 UUID → DB int（F1 映射: uuid.int）."""
    return value.int if isinstance(value, uuid.UUID) else int(value)


def _orm_to_domain(orm: ExtractionRunORM) -> ExtractionRun:
    """提取运行 ORM 行 → 领域实体（int 主键直接暴露，project_id int → UUID）."""
    return ExtractionRun(
        id=orm.id,
        project_id=uuid.UUID(int=orm.project_id),
        type=ExtractionType(orm.type),
        source_key=orm.source_key,
        content_hash=orm.content_hash,
        status=ExtractionStatus(orm.status),
        created_count=orm.created_count,
        updated_count=orm.updated_count,
        warnings_json=orm.warnings_json,
        error=orm.error,
        model=orm.model,
        indexed=orm.indexed,
        run_at=orm.run_at,
    )


def _domain_to_orm(domain: ExtractionRun) -> ExtractionRunORM:
    """提取运行领域实体 → ORM 行（project_id UUID → int；id 由 DB 自增分配）."""
    return ExtractionRunORM(
        project_id=_uuid_to_int(domain.project_id),
        type=domain.type.value,
        source_key=domain.source_key,
        content_hash=domain.content_hash,
        status=domain.status.value,
        created_count=domain.created_count,
        updated_count=domain.updated_count,
        warnings_json=domain.warnings_json,
        error=domain.error,
        model=domain.model,
        indexed=domain.indexed,
        run_at=domain.run_at,
    )


class SQLExtractionRunRepository:
    """SQLite 提取运行仓储 — 实现 ExtractionRunRepositoryProtocol 接口."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── ExtractionRun ──

    async def get(
        self,
        project_id: int,
        type: ExtractionType,
        source_key: str,
    ) -> ExtractionRun | None:
        """按 (project_id, type, source_key) 查询最新一次 run 状态.

        门面增量判定用（spec §5.2 步骤 ①）: 命中 = 该源已有 run 记录，
        比较 content_hash 决定 skip；未命中 = 首次提取。
        """
        stmt = select(ExtractionRunORM).where(
            ExtractionRunORM.project_id == project_id,
            ExtractionRunORM.type == type.value,
            ExtractionRunORM.source_key == source_key,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def upsert(self, run: ExtractionRun) -> ExtractionRun:
        """插入或更新一次 run 记录（SQLite ON CONFLICT DO UPDATE）.

        同键 (project_id, type, source_key) 冲突时**字段整体覆盖**（含
        run_at 更新），行数不增、id 不变——每源只保留最新一次状态
        （spec §2.3）；未冲突则新建（id 由 DB 自增分配）。

        Args:
            run: 待持久化的 run（id 为 0 占位即可，落库后读回真实 id）.

        Returns:
            持久化后的 ExtractionRun（最新状态）.
        """
        orm = _domain_to_orm(run)
        payload = {
            c.key: getattr(orm, c.key)
            for c in ExtractionRunORM.__table__.columns
            if c.key not in ("id", "created_at", "updated_at")
        }
        now = _utcnow()
        # Core insert 不触发 Python 侧 column default → 审计时间戳显式给出；
        # 冲突更新时 created_at 保留原值，仅刷新 updated_at
        stmt = (
            sqlite_insert(ExtractionRunORM)
            .values(**payload, created_at=now, updated_at=now)
            .on_conflict_do_update(
                index_elements=[
                    ExtractionRunORM.project_id,
                    ExtractionRunORM.type,
                    ExtractionRunORM.source_key,
                ],
                set_={**payload, "updated_at": now},
            )
        )
        await self._session.execute(stmt)
        await self._session.commit()

        # 读回最新行（新建 = 自增 id；更新 = 原行整体覆盖）
        stmt2 = select(ExtractionRunORM).where(
            ExtractionRunORM.project_id == payload["project_id"],
            ExtractionRunORM.type == payload["type"],
            ExtractionRunORM.source_key == payload["source_key"],
        )
        result = await self._session.execute(stmt2)
        orm2 = result.scalar_one_or_none()
        if orm2 is None:
            raise RuntimeError("ExtractionRun upsert 后读回失败")
        return _orm_to_domain(orm2)

    async def list(
        self,
        project_id: int,
        type: ExtractionType | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[ExtractionRun], int]:
        """分页查询项目内的 run 记录，按 run_at DESC 排序（最新在前）.

        Args:
            project_id: 项目主键（int）.
            type: 提取类型精确过滤（不传 = 全部）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (run 列表, 总数) 元组.
        """
        base = select(ExtractionRunORM).where(
            ExtractionRunORM.project_id == project_id,
        )
        if type is not None:
            base = base.where(ExtractionRunORM.type == type.value)

        # 总数（分页前）
        count_stmt = select(func.count()).select_from(base.subquery())
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        # 排序（run_at DESC 最新在前，id DESC 兜底稳定）+ 分页
        base = base.order_by(
            ExtractionRunORM.run_at.desc(),
            ExtractionRunORM.id.desc(),
        )
        base = base.offset(offset).limit(limit)

        result = await self._session.execute(base)
        orms = result.scalars().all()
        return [_orm_to_domain(o) for o in orms], total
