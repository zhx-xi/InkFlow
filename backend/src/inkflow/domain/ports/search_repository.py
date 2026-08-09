"""F22 全文搜索索引基础设施端口 —— FTS5 + search_meta 读写契约（spec §8.2）.

SearchDocument 为基础设施 DTO（dataclass，entity_id/project_id 存 int 主键，
与 ORM 层一致）；SearchRepositoryProtocol 定义 SQLiteSearchRepository
（infrastructure/database/repositories/search_repo.py）需实现的全部操作：
索引初始化、判脏（is_stale 表名列表，2026-08-09 父侧裁定签名）、全量重建、
增量同步、FTS5 查询与 ai_maintenance 设置读写。
semantic 模式复用既有 VectorStoreProtocol（F14），不新增端口。
"""

from __future__ import annotations

import builtins
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from inkflow.domain.models.search import SearchHit


@dataclass
class SearchDocument:
    """待写入全文索引的文档（基础设施 DTO，body 为分词后文本）。"""

    entity_type: str
    entity_id: int
    project_id: int
    title: str
    body: str


class SearchRepositoryProtocol(Protocol):
    """搜索索引基础设施端口（FTS5 + 元数据；不触碰业务表）。"""

    async def ensure_index(self) -> None:
        """幂等建表：search_index（FTS5）与 search_meta（spec §2.4）。"""
        ...

    async def is_stale(self, tables: builtins.list[str]) -> bool:
        """任一表 max(updated_at) 晚于 last_rebuilt_at 则判脏（表名列表参数）。"""
        ...

    async def rebuild(self, documents: Iterable[SearchDocument]) -> None:
        """全量清空 search_index 后批量 INSERT，并刷新 last_rebuilt_at。"""
        ...

    async def incremental_sync(
        self,
        documents: Iterable[SearchDocument],
        deleted: Iterable[builtins.tuple[str, int]],
    ) -> None:
        """AI 自动维护：按 (entity_type, entity_id) 删旧插新，并刷新 meta。"""
        ...

    async def query(
        self,
        match: str,
        project_ids: builtins.list[int],
        types: builtins.list[str] | None,
        limit: int,
        offset: int,
    ) -> builtins.tuple[int, builtins.list[SearchHit]]:
        """FTS5 MATCH 查询，返回 (total, hits)；snippet() 生成 <mark> 高亮。"""
        ...

    async def get_setting(self, key: str) -> str | None:
        """读 search_meta 键值；缺失返回 None（如 ai_maintenance）。"""
        ...

    async def set_setting(self, key: str, value: str) -> None:
        """写 search_meta 键值并 commit。"""
        ...
