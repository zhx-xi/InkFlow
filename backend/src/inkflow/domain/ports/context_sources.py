"""上下文数据源端口 — 定义各种上下文数据源的契约.

各 ContextSource 产出 ContextItem 列表，由 ContextService 收集后统一预算分配.
Phase 1 空实现：CharacterSource / WorldSource / ForeshadowingSource 返回空列表，
机制与注入格式先行就位，待 F8/F9/F14 实现后替换.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from inkflow.domain.models.context import ContextItem


class ContextSourceProtocol(Protocol):
    """上下文数据源泛型端口 — 每个数据源类型对应一个实现."""

    async def collect(
        self,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None,
    ) -> list[ContextItem]:
        """收集该数据源的所有上下文条目.

        Args:
            project_id: 项目 ID.
            chapter_id: 当前写作章节 ID（可为 None：#680 chat agent 未锁定章节时
                传 None；当前各源均忽略 chapter_id，仅接口对齐）.

        Returns:
            该数据源产出的 ContextItem 列表（空列表 = 无数据，正常路径）.
        """
        ...
