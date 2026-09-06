"""DraftService 装配共享工厂 — #976 D4 outline 回填绑定器（books/deps 双轨复用）.

迁移自 api/routers/books.py `_build_book_service.<locals>._outline_bindder`（#988）：
- books 轨（_build_book_service）与通用轨（deps.get_draft_service，POST
  /agent/drafts/{id}/confirm 路由依赖）复用同一实现——修复 GUI 审批弹层对未绑章
  草稿 confirm 真实内核仍 409 的断头路（#976 根因：deps 装配未注入 creator/绑定器）；
- func-cov 语义：books.py 内嵌闭包只被装配构造、从未执行 → 被计为新 uncalled；
  迁出为工厂 + 顶层装配点真实注入后，闭包由 confirm 自动建章路径真实执行。

本模块不 import deps.py（deps.py 模块级 import 本模块，成环规避）；ORM 延迟导入。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

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
