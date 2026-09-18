"""章节摘要的章节序号解析 — 由 chapter_id 反查 chapters.order_index（#1253）.

`ChapterSummary` 与 `chapter_summaries` 表都不含章节序号（spec §3.5：表仅
chapter_id / summary / model / 时间戳），但 dynamic 层的选择规则依赖
「按 `chapter_index` 倒序」（spec §4.1）。本源在组装侧以独立轻读补这一维，
**不为显示字段新增 ORM 列或仓储 Protocol 方法**（#770 轻量契约先例）。

依据: specs/f6-context/spec.md §3.5 / §4.1.
"""

from __future__ import annotations

import uuid

from inkflow.domain.ports.chapter_repository import ChapterRepositoryProtocol

# 单章序号兜底（仓储读不到该章时使用，保证条目仍可注入且可排序）
_FALLBACK_INDEX = 0


async def resolve_chapter_index(
    chapter_repo: ChapterRepositoryProtocol | None,
    chapter_id: uuid.UUID,
) -> float:
    """解析摘要所属章节的序号（`chapters.order_index`）.

    Args:
        chapter_repo: 章节仓储（None = 未接线 → 直接兜底）.
        chapter_id: 摘要所属章节 ID（domain UUID）.

    Returns:
        章节序号；未接线 / 无此章 / 序号为空 → `_FALLBACK_INDEX`（0）.
    """
    if chapter_repo is None:
        return _FALLBACK_INDEX
    try:
        chapter = await chapter_repo.get_chapter(chapter_id)
    except Exception:
        return _FALLBACK_INDEX
    if chapter is None or chapter.order_index is None:
        return _FALLBACK_INDEX
    return float(chapter.order_index)
