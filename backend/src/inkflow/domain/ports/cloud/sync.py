"""云端演进接口 — 项目同步（SyncProtocol）。

本地实现（Phase 1-3）: 无同步（push/pull 返回 noop 结果）
云端实现（Phase 4+）: CloudSync（项目同步）

仅定义接口，不实现任何云端功能（PRD §6.5 / spec f52-cloud-protocol）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class SyncResult:
    """同步结果。本地 noop 模式: ok=True, rev=""."""

    ok: bool
    rev: str = ""
    error: str = field(default="")


class SyncProtocol(Protocol):
    """项目同步接口。

    本地实现: 无同步 — ``push``/``pull`` 返回 ok=True 的 noop 结果。
    云端实现: CloudSync — 按项目维度增量同步。
    """

    async def push(
        self,
        project_id: str,
        payload: Mapping[str, Any],
    ) -> SyncResult: ...

    async def pull(
        self,
        project_id: str,
        since: datetime | None = None,
    ) -> SyncResult: ...
