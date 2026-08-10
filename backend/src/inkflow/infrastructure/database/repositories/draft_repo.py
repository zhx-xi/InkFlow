"""SQLite 草稿仓储 — F27 草稿保存区的持久化（status 状态机 + 正文修改）.

转换函数（_orm_to_domain）按项目惯例放在本仓储层（参照
foreshadowing_repo.py / agent_template_repo.py）。

语义（spec §5.3，父侧契约 test_draft_repo.py docstring）:
- create: 创建 status=DRAFT 草稿（id 由 ORM default 生成 uuid4 字符串），
  单次 commit（单工具单事务，ADR-F 约束②）
- get: 按草稿 id（uuid4 字符串）查询
- list: 按 project_id + status 过滤，created_at desc（最新在前）+
  offset/limit 分页，返回 (页内容, 该项目全量 total)
- update_status: 状态机迁移 draft → confirmed/rejected（confirmed 回填
  confirmed_at）；不存在 → None
- update_content: 确认前用户手动修改正文落库；不存在 → None
- 领域 UUID ↔ uuid4 字符串转换在仓储层（project_id/chapter_id 列存
  str(uuid)，与 AgentExecutionORM 先例一致）

注: 方法名 ``list`` 会遮蔽类作用域中的内置 ``list``，返回注解统一
写作 ``builtins.list[...]``（与既有仓储惯例一致）。
"""

from __future__ import annotations

import builtins
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.infrastructure.database.models.agent_run import DraftORM


def _orm_to_domain(orm: DraftORM) -> Draft:
    """Draft ORM 行 → 领域实体（uuid 字符串 → UUID）."""
    return Draft(
        id=orm.id,
        project_id=uuid.UUID(orm.project_id),
        chapter_id=uuid.UUID(orm.chapter_id) if orm.chapter_id is not None else None,
        agent_run_id=orm.agent_run_id,
        content=orm.content,
        status=DraftStatus(orm.status),
        summary=orm.summary,
        created_at=orm.created_at,
        confirmed_at=orm.confirmed_at,
    )


class SQLiteDraftRepository:
    """SQLite 草稿仓储（session 注入，镜像 F34 audit_log_repo 模式）."""

    def __init__(self, db_session: AsyncSession) -> None:
        """以异步会话构造仓储（注入方式与既有仓储一致）."""
        self._session = db_session

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None,
        content: str,
        summary: str = "",
        agent_run_id: str | None = None,
    ) -> Draft:
        """创建草稿（status=DRAFT），单次 commit（单工具单事务，ADR-F 约束②）.

        Args:
            project_id: 所属项目 UUID.
            chapter_id: 目标章节 UUID（None = 确认时指定）.
            content: 草稿正文.
            summary: 草稿摘要（默认空）.
            agent_run_id: 产生该草稿的 run id（可空）.

        Returns:
            已落库的 Draft（id 为 uuid4 字符串，created_at 为 ORM default
            生成的 UTC 时间）.
        """
        orm = DraftORM(
            project_id=str(project_id),
            chapter_id=str(chapter_id) if chapter_id is not None else None,
            content=content,
            summary=summary,
            agent_run_id=agent_run_id,
        )
        self._session.add(orm)
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def get(self, draft_id: str) -> Draft | None:
        """按草稿 id 查询（uuid4 字符串）；缺失 → None."""
        stmt = select(DraftORM).where(DraftORM.id == draft_id)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return _orm_to_domain(orm) if orm else None

    async def list(
        self,
        project_id: uuid.UUID,
        status: DraftStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[Draft], int]:
        """按项目 + 状态分页查询草稿，created_at desc（最新在前）.

        Args:
            project_id: 所属项目 UUID.
            status: 状态精确过滤（不传 = 全部）.
            offset: 分页偏移（默认 0）.
            limit: 每页条数（默认 50）.

        Returns:
            (页内 Draft 列表, 该项目草稿总数).
        """
        base = select(DraftORM).where(DraftORM.project_id == str(project_id))
        if status is not None:
            base = base.where(DraftORM.status == status.value)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self._session.execute(count_stmt)).scalar_one()
        base = base.order_by(DraftORM.created_at.desc()).offset(offset).limit(limit)
        result = await self._session.execute(base)
        return [_orm_to_domain(o) for o in result.scalars().all()], total

    async def update_status(
        self,
        draft_id: str,
        status: DraftStatus,
        confirmed_at: datetime | None = None,
    ) -> Draft | None:
        """更新草稿状态（draft → confirmed/rejected；confirmed 回填 confirmed_at）.

        Args:
            draft_id: 草稿 id（uuid4 字符串）.
            status: 目标状态.
            confirmed_at: 确认时间（UTC；confirmed 时回填，rejected 保持 None）.

        Returns:
            更新后的 Draft；draft_id 不存在 → None.
        """
        orm = await self._session.get(DraftORM, draft_id)
        if orm is None:
            return None
        orm.status = status.value
        orm.confirmed_at = confirmed_at
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)

    async def update_content(self, draft_id: str, content: str) -> Draft | None:
        """修改草稿正文（确认前用户手动修改落库）.

        Args:
            draft_id: 草稿 id（uuid4 字符串）.
            content: 新正文.

        Returns:
            更新后的 Draft；draft_id 不存在 → None.
        """
        orm = await self._session.get(DraftORM, draft_id)
        if orm is None:
            return None
        orm.content = content
        await self._session.commit()
        await self._session.refresh(orm)
        return _orm_to_domain(orm)
