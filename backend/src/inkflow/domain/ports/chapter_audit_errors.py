"""F34 章节审计领域异常.

F34 专属异常类型，继承自 Exception。
依据: specs/f34-chapter-audit/spec.md §3.3 异常映射表 + §7 边界情况。

异常映射约定（spec §3.3）:
- NoPendingAuditError = 该章无待确认审计（无 pending 记录），API 层映射为 422
- ProjectNotFoundError / ChapterNotFoundError 复用 F9 character_errors /
  F14 extraction_errors 既有类（陷阱 16：错误类不导出到 ports/__init__.py，
  router 显式 except）——本模块 re-export 统一入口，供 F34 router/service
  从单一模块导入。
"""

from __future__ import annotations

from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ChapterNotFoundError

__all__ = [
    "ChapterNotFoundError",
    "NoPendingAuditError",
    "ProjectNotFoundError",
]


class NoPendingAuditError(Exception):
    """该章无待确认审计 — confirm 校验失败，API 层映射为 422.

    该章从未审计或最新记录已确认（spec §7 E9）时抛出，
    消息即 422 响应 detail（CLI 对应退出 1，E12）。
    """

    def __init__(self, message: str = "该章无待确认审计") -> None:
        super().__init__(message)
