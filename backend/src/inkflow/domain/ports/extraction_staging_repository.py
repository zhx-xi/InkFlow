"""F14 提取暂存仓储端口 — 两段式暂存的持久化契约（#1545，§5.9）.

ExtractionStagingRepositoryProtocol 定义暂存行的批量写入 / 按批读取 / 按批
删除操作，基础设施层（SQLite / mock / memory）实现此 Protocol。`project_id`
入参统一用领域 UUID（同 extraction_run_repository.py，不自行 ``.int``）。

暂存行不承载业务语义（物化判定在门面层 ``ExtractionService.confirm_staged``）；
仓储只负责「按 (project_id, batch_id) 存取 StagedEntry 列表」。

依据: specs/f14-extraction/spec.md §5.9。
"""

from __future__ import annotations

import builtins
import uuid
from typing import Protocol

from inkflow.domain.models.extraction import StagedEntry


class ExtractionStagingRepositoryProtocol(Protocol):
    """提取暂存仓储端口（§5.9）.

    注: 类内方法名 ``list_by_batch`` 不遮蔽内置 ``list``，但为与
    extraction_run_repository.py 保持同一返回注解口径，列表类型统一写作
    ``builtins.list[...]``。
    """

    async def add_many(
        self,
        project_id: uuid.UUID,
        batch_id: str,
        type_: str,
        entries: builtins.list[StagedEntry],
    ) -> int:
        """批量写入暂存行（本次提取的 created / updated 条目清单）.

        Args:
            project_id: 项目主键（领域 UUID）.
            batch_id: 批次标识（同一次提取的全部源共享）.
            type_: 提取类型（``ExtractionType.value``）.
            entries: 待暂存条目列表.

        Returns:
            实际写入的行数.
        """
        ...

    async def list_by_batch(
        self, project_id: uuid.UUID, batch_id: str
    ) -> builtins.list[StagedEntry]:
        """按 (project_id, batch_id) 读取暂存条目（写入序）.

        Args:
            project_id: 项目主键（领域 UUID）.
            batch_id: 批次标识.

        Returns:
            暂存条目列表（无命中 → 空列表，幂等语义）.
        """
        ...

    async def delete_by_batch(self, project_id: uuid.UUID, batch_id: str) -> int:
        """按 (project_id, batch_id) 删除暂存条目（confirm / cancel 共用）.

        Args:
            project_id: 项目主键（领域 UUID）.
            batch_id: 批次标识.

        Returns:
            实际删除的行数（重复删除 → 0，不报错）.
        """
        ...
