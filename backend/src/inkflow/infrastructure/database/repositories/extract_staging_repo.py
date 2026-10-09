"""SQLite 提取暂存仓储 — 实现 ExtractionStagingRepositoryProtocol 全部方法（#1545，§5.9）.

转换函数（_orm_to_domain / payload JSON 序列化）按项目惯例放在本仓储层
（参照 extraction_run_repo.py）。

语义（spec §5.9）:
- add_many: 一次提取的全部暂存行单次事务写入（同批次原子；失败整批不落）
- list_by_batch: 按 (project_id, batch_id) 读回，写入序（id 升序），供
  GET 端点与 confirm 物化；无命中 → 空列表（幂等）
- delete_by_batch: confirm 物化后 / cancel 时清空本批，返回删除行数
  （重复删除 → 0，不报错）
- 主键入参归一：写路径 require_int_pk（越界响亮失败，ADR-063），
  读/删路径 int_pk_for_filter（越界 = 不存在）
- name 不入列（§5.9 表无该列）：从 payload 的 ``name`` 读回，避免冗余列
  与 payload 漂移
"""

from __future__ import annotations

import builtins
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.extraction import StagedEntry
from inkflow.infrastructure.database.models.extract_staging import ExtractStagingORM
from inkflow.infrastructure.database.repositories._id_guard import (
    int_pk_for_filter,
    require_int_pk,
)


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _orm_to_domain(orm: ExtractStagingORM) -> StagedEntry:
    """暂存 ORM 行 → 领域条目（payload JSON 文本 → dict；name 取自 payload）."""
    payload = json.loads(orm.payload)
    return StagedEntry(
        entity_type=orm.entity_type,
        action=orm.action,
        name=payload.get("name", ""),
        payload=payload,
    )


def _target_id(entry: StagedEntry) -> str | None:
    """update 条目指向被覆盖行（payload 内实体 UUID）；create → None（§5.9）."""
    entity_id = entry.payload.get("id")
    if entry.action != "update" or entity_id is None:
        return None
    return str(entity_id)


class SQLExtractStagingRepository:
    """SQLite 提取暂存仓储 — 实现 ExtractionStagingRepositoryProtocol 接口（§5.9）."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(
        self,
        project_id: uuid.UUID,
        batch_id: str,
        type_: str,
        entries: builtins.list[StagedEntry],
    ) -> int:
        """批量写入暂存行（本次提取的 created / updated 条目清单，§5.9）.

        Args:
            project_id: 项目主键（领域 UUID）.
            batch_id: 批次标识（同一次提取的全部源共享）.
            type_: 提取类型（``ExtractionType.value``）.
            entries: 待暂存条目列表（空列表 → 零写入，直接返回 0）.

        Returns:
            实际写入的行数.

        Raises:
            ValueError: project_id 超出 int64 范围（无本地 projects 行，ADR-063）.
        """
        if not entries:
            return 0
        pid = require_int_pk(project_id)
        now = _utcnow()
        for entry in entries:
            self._session.add(
                ExtractStagingORM(
                    project_id=pid,
                    batch_id=batch_id,
                    type=type_,
                    entity_type=entry.entity_type,
                    action=entry.action,
                    target_id=_target_id(entry),
                    payload=json.dumps(entry.payload, ensure_ascii=False),
                    created_at=now,
                )
            )
        await self._session.commit()
        return len(entries)

    async def list_by_batch(
        self, project_id: uuid.UUID, batch_id: str
    ) -> builtins.list[StagedEntry]:
        """按 (project_id, batch_id) 读回暂存条目（写入序；无命中 → 空列表）."""
        stmt = (
            select(ExtractStagingORM)
            .where(
                ExtractStagingORM.project_id == int_pk_for_filter(project_id),
                ExtractStagingORM.batch_id == batch_id,
            )
            .order_by(ExtractStagingORM.id)
        )
        result = await self._session.execute(stmt)
        return [_orm_to_domain(orm) for orm in result.scalars().all()]

    async def delete_by_batch(self, project_id: uuid.UUID, batch_id: str) -> int:
        """按 (project_id, batch_id) 删除暂存条目，返回删除行数（幂等）."""
        stmt = delete(ExtractStagingORM).where(
            ExtractStagingORM.project_id == int_pk_for_filter(project_id),
            ExtractStagingORM.batch_id == batch_id,
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]  # SQLAlchemy Result 未声明 rowcount（属性在底层 cursor）
