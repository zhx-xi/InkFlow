"""摘要仓储端口 — 前文摘要的持久化契约.

SummaryRepositoryProtocol 定义 get / upsert / list_recent 三个操作，
基础设施层（SQLite / mock / memory）实现此 Protocol.
"""

from __future__ import annotations

from typing import Protocol

from inkflow.domain.models.context import ChapterSummary


class SummaryRepositoryProtocol(Protocol):
    """摘要仓储端口 — 前文摘要缓存 CRUD.

    按 spec §3.5: chapter_id 唯一约束（每章一条摘要），
    updated_at 用于失效检测（chapter.updated_at > summary.updated_at → 重新生成）.
    """

    async def get(self, chapter_id: int) -> ChapterSummary | None:
        """查询章节摘要缓存.

        Args:
            chapter_id: 章节主键（int，与 ORM 层一致）.

        Returns:
            若命中则返回 ChapterSummary，否则返回 None.
        """
        ...

    async def upsert(self, chapter_id: int, summary: str, model: str) -> ChapterSummary:
        """插入或更新摘要缓存.

        若该章节已有摘要则更新 summary / model / updated_at，否则插入新记录.

        Args:
            chapter_id: 章节主键（int）.
            summary: 摘要文本（≤ 300 字）.
            model: 生成摘要所用模型.

        Returns:
            持久化后的 ChapterSummary.
        """
        ...

    async def list_recent(self, project_id: int, limit: int = 10) -> list[ChapterSummary]:
        """获取项目内按章节序号倒序排列的最新摘要列表.

        Args:
            project_id: 项目主键（int）.
            limit: 最大返回数.

        Returns:
            章节摘要列表（按 chapter_index 倒序，最新在前）.
        """
        ...
