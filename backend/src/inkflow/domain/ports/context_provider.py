"""上下文注入端口 — 定义领域层与上下文管理服务之间的契约.

F6 (context_service) 实现此 Protocol。
F6 未实现时，F3 使用 NullContextProvider（返回空字符串）。
"""

from __future__ import annotations

import uuid
from typing import Protocol


class ContextProviderProtocol(Protocol):
    """上下文注入端口 — 由 F6 (context_service) 实现。

    F6 未实现时，F3 使用 NullContextProvider（返回空字符串），
    上下文由调用方通过请求中的 context 字段传入。
    """

    async def get_context(
        self,
        *,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None = None,
        mode: str,
    ) -> str:
        """返回注入到写作 Prompt 的上下文文本（角色/设定/前文摘要/伏笔）。

        Args:
            project_id: 项目 ID。
            chapter_id: 章节 ID（可选）。
            mode: 写作模式 ("generate" / "continue" / "revise")。
        """
        ...
