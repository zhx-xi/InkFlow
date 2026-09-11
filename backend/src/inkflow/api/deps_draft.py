"""DraftService 装配共享工厂 — #976 D4 outline 回填绑定器（books/deps 双轨复用）.

迁移自 api/routers/books.py `_build_book_service.<locals>._outline_bindder`（#988）：
- books 轨（_build_book_service）与通用轨（deps.get_draft_service，POST
  /agent/drafts/{id}/confirm 路由依赖）复用同一实现——修复 GUI 审批弹层对未绑章
  草稿 confirm 真实内核仍 409 的断头路（#976 根因：deps 装配未注入 creator/绑定器）；
- func-cov 语义：books.py 内嵌闭包只被装配构造、从未执行 → 被计为新 uncalled；
  迁出为工厂 + 顶层装配点真实注入后，闭包由 confirm 自动建章路径真实执行。
- #1097 自动建卷归卷：`make_volume_ensurer`（沿章大纲 parent_id 上溯 volume 节点 →
  按 (project_id, 卷名) ensure volumes 行）镜像 `make_outline_bindder` 同一形态
  （db 会话闭包工厂 + ORM 延迟导入 + 弱依赖永不抛错），books/deps 双轨装配。

本模块不 import deps.py（deps.py 模块级 import 本模块，成环规避）；ORM 延迟导入。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def make_outline_bindder(
    db: AsyncSession,
) -> Callable[[str, str], Awaitable[None]]:
    """#976 D4：自动建章后回填 outlines.chapter_id 的绑定器工厂.

    返回 (chapter_outline_id, chapter_uuid_str) 均为 uuid 字符串的 async 绑定器：
    str uuid → int 主键（int↔UUID 惯例）；任一行 id 超过 2^63-1 → 静默返回
    （uuid4 随机值溢出 SQLite INTEGER，int↔UUID 惯例下无对应行）；outline 行
    不存在（None）同样静默防御。装配形态镜像 deps_chat_agent._make_draft_volume_lookup
    （db 会话闭包工厂）。
    """
    from inkflow.infrastructure.database.models.outline import OutlineORM

    async def _outline_bindder(chapter_outline_id: str, chapter_uuid_str: str) -> None:
        """回填单行 outlines.chapter_id（无行/溢出守卫，永不抛错）。"""
        outline_row_id = uuid.UUID(chapter_outline_id).int
        chapter_row_id = uuid.UUID(chapter_uuid_str).int
        if outline_row_id > 2**63 - 1 or chapter_row_id > 2**63 - 1:
            return  # uuid4 随机值溢出 SQLite INTEGER：int↔UUID 惯例下无对应行
        outline_row = await db.get(OutlineORM, outline_row_id)
        if outline_row is not None:
            outline_row.chapter_id = chapter_row_id
            await db.commit()

    return _outline_bindder


def make_volume_ensurer(
    db: AsyncSession,
) -> Callable[[uuid.UUID, uuid.UUID], Awaitable[uuid.UUID | None]]:
    """#1097：confirm D4 自动建章前的「按卷大纲 ensure 卷」工厂.

    返回 (project_id, chapter_outline_id) → 卷 UUID | None 的 async 闭包：
    沿章级大纲节点 parent_id 上溯 level=="volume" 的父节点，取其 name 作卷名，
    按 (project_id, title) ensure volumes 行（命中同项目同名复用，未命中新建，
    order_index 走 SQLiteChapterRepository.get_next_volume_order 既有语义）。
    无卷父（行不存在 / 无 parent / parent 非 volume / 跨项目 / 空卷名 / id 溢出
    SQLite INTEGER）→ None（不臆造卷）；整体 try/except 包裹 —— 弱依赖契约：
    永不抛错，失败即未归卷（镜像 make_outline_bindder 的无行/溢出静默守卫）。
    """
    from inkflow.infrastructure.database.models.chapter import VolumeORM
    from inkflow.infrastructure.database.models.outline import OutlineORM
    from inkflow.infrastructure.database.repositories.chapter_repo import (
        SQLiteChapterRepository,
    )

    async def _volume_ensurer(
        project_id: uuid.UUID, chapter_outline_id: uuid.UUID
    ) -> uuid.UUID | None:
        """解析卷父 → ensure 卷 → 返回卷 UUID（失败一律 None，永不抛错）."""
        try:
            project_row_id = (
                project_id.int
                if isinstance(project_id, uuid.UUID)
                else uuid.UUID(str(project_id)).int
            )
            chapter_row_id = (
                chapter_outline_id.int
                if isinstance(chapter_outline_id, uuid.UUID)
                else uuid.UUID(str(chapter_outline_id)).int
            )
            if project_row_id > 2**63 - 1 or chapter_row_id > 2**63 - 1:
                return None  # uuid4 随机值溢出 SQLite INTEGER：int↔UUID 惯例下无对应行
            outline_row = await db.get(OutlineORM, chapter_row_id)
            if outline_row is None or outline_row.project_id != project_row_id:
                return None  # 无行 / 跨项目（项目隔离）
            if outline_row.parent_id is None:
                return None  # 无卷父（书级/总纲下孤立章，合法旧形态）
            parent_row = await db.get(OutlineORM, outline_row.parent_id)
            if (
                parent_row is None
                or parent_row.level != "volume"
                or parent_row.project_id != project_row_id
            ):
                return None  # 父行缺失 / 非卷级 / 跨项目父
            title = (parent_row.name or "").strip()
            if not title:
                return None  # 空卷名无可归
            existing_result = await db.execute(
                select(VolumeORM).where(
                    VolumeORM.project_id == project_row_id,
                    VolumeORM.title == title,
                )
            )
            existing = existing_result.scalars().first()
            if existing is not None:
                return uuid.UUID(int=int(existing.id))  # 幂等：同项目同名复用
            order_index = await SQLiteChapterRepository(db).get_next_volume_order(
                project_row_id
            )
            volume_row = VolumeORM(
                project_id=project_row_id, title=title, order_index=order_index
            )
            db.add(volume_row)
            await db.flush()
            volume_row_id = int(volume_row.id)
            await db.commit()
            return uuid.UUID(int=volume_row_id)
        except Exception:
            return None  # 弱依赖契约：永不抛错（失败即未归卷）

    return _volume_ensurer


def make_outline_autolinker(
    db: AsyncSession,
) -> Callable[[uuid.UUID, uuid.UUID, str], Awaitable[object]]:
    """#1001 正文落盘 → 章级大纲自动关联器工厂（弱依赖，永不抛错）.

    返回 (project_id, chapter_id, chapter_title) 的 async 绑定器 =
    OutlineService.auto_link_chapter_by_title：同项目内唯一精确同名章级大纲才回填，
    0/多条命中或已绑定别的章 → 不写。自建 OutlineService（不 import deps.py，
    成环规避）；generator 不注入（本路径不触发生成）。
    """
    from inkflow.domain.services.outline_service import OutlineService
    from inkflow.infrastructure.database.repositories.chapter_repo import (
        SQLiteChapterRepository,
    )
    from inkflow.infrastructure.database.repositories.outline_repo import (
        SQLiteOutlineRepository,
    )

    service = OutlineService(
        repository=SQLiteOutlineRepository(db),
        chapter_repo=SQLiteChapterRepository(db),
    )
    return service.auto_link_chapter_by_title
