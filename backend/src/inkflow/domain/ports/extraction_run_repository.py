"""F14 增量追踪记录仓储端口 — 提取运行状态持久化契约.

ExtractionRunRepositoryProtocol 定义 ExtractionRun 的查询与 upsert 操作，
基础设施层（SQLite / mock / memory）实现此 Protocol。仓储层方法入参用 int
（与 ORM 层一致），Service 负责 UUID ↔ int 转换（沿用 F1 `_to_int_id`
模式）。

依据: specs/f14-extraction-service/spec.md §8.1。
"""

from __future__ import annotations

import builtins
from typing import Protocol

from inkflow.domain.models.extraction import ExtractionRun, ExtractionType


class ExtractionRunRepositoryProtocol(Protocol):
    """增量追踪记录仓储端口.

    每 (project_id, type, source_key) 一行最新状态（upsert）；get 供门面
    增量判定（§5.2），list 供 runs 查询（§3.3）。

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9-F13）。
    """

    async def get(
        self, project_id: int, type: ExtractionType, source_key: str
    ) -> ExtractionRun | None:
        """按 (project_id, type, source_key) 查询最新 run 记录.

        Args:
            project_id: 项目主键（int，与 ORM 层一致）.
            type: 提取类型.
            source_key: 源标识（章节模式=str(chapter_id)；手动模式="manual"）.

        Returns:
            若命中则返回 ExtractionRun，否则返回 None.
        """
        ...

    async def upsert(self, run: ExtractionRun) -> ExtractionRun:
        """写入 run 记录（INSERT ... ON CONFLICT(project_id, type, source_key)
        DO UPDATE，字段整体覆盖，run_at 更新）.

        Args:
            run: 待持久化的 ExtractionRun（id 为 DB 自增主键）.

        Returns:
            持久化后的 ExtractionRun.
        """
        ...

    async def list(
        self,
        project_id: int,
        type: ExtractionType | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[ExtractionRun], int]:
        """分页查询项目内 run 记录，按 run_at DESC 排序（最新在前）.

        Args:
            project_id: 项目主键（int）.
            type: 按提取类型过滤（None = 全部类型）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (run 列表, 总数) 元组.
        """
        ...
