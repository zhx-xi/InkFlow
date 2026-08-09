"""SQLite 全文搜索仓储 —— 实现 SearchRepositoryProtocol（FTS5 + search_meta）.

F22 搜索索引基础设施（spec §8.2）：本仓储以原生 SQL 操作 FTS5 虚拟表
search_index 与 key-value 元数据表 search_meta，不建立 ORM 映射——
FTS5 虚拟表不是 SQLAlchemy 映射表，无法纳入 Base.metadata.create_all，
因此由 ensure_index() 幂等建表。

镜像 F15 audit_repo 模式：结构化子类型（不显式继承 Protocol），
以 AsyncSession 注入，全部操作走 sqlalchemy.text() 原生 SQL。
"""

from __future__ import annotations

import builtins
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BindParameter, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.search import SearchEntityType, SearchHit
from inkflow.domain.ports.search_repository import SearchDocument

_LAST_REBUILT_KEY = "last_rebuilt_at"

_INSERT_DOC_SQL = text(
    "INSERT INTO search_index (title, body, entity_type, entity_id, project_id) "
    "VALUES (:title, :body, :entity_type, :entity_id, :project_id)"
)

_UPSERT_META_SQL = text(
    "INSERT INTO search_meta (key, value) VALUES (:key, :value) "
    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
)


class SQLiteSearchRepository:
    """SQLite FTS5 全文搜索仓储（SearchRepositoryProtocol 结构化子类型）.

    不显式继承 Protocol，由 F22 服务层按 SearchRepositoryProtocol 注入使用；
    entity_id / project_id 存 int 主键（陷阱 18：FTS 存 int，
    查询结果用 uuid.UUID(int=...) 转回 UUID）。
    """

    def __init__(self, session: AsyncSession) -> None:
        """以异步会话构造仓储（注入方式与既有仓储一致）."""
        self._session = session

    async def ensure_index(self) -> None:
        """幂等创建 search_index（FTS5）与 search_meta 元数据表（spec §2.4）."""
        await self._session.execute(
            text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5("
                "title, body, entity_type UNINDEXED, entity_id UNINDEXED, "
                "project_id UNINDEXED)"
            )
        )
        await self._session.execute(
            text("CREATE TABLE IF NOT EXISTS search_meta " "(key TEXT PRIMARY KEY, value TEXT)")
        )
        await self._session.commit()

    async def is_stale(self, tables: builtins.list[str]) -> bool:
        """任一业务表 max(updated_at) 晚于 last_rebuilt_at 则判脏（表名白名单参数）.

        表名为 service 常量白名单传入，直接拼接（SQLite 表名不能作绑定参数）；
        max(updated_at) 为 NULL 的空表跳过；两侧时间统一归一化为 UTC aware。
        """
        row = await self._session.execute(
            text("SELECT value FROM search_meta WHERE key = :key"),
            {"key": _LAST_REBUILT_KEY},
        )
        last_rebuilt = row.scalar()
        if last_rebuilt is None:
            return True
        rebuilt_at = self._as_utc(last_rebuilt)
        for table in tables:
            result = await self._session.execute(text(f"SELECT max(updated_at) FROM {table}"))
            max_updated = result.scalar()
            if max_updated is None:
                continue
            if self._as_utc(max_updated) > rebuilt_at:
                return True
        return False

    async def rebuild(self, documents: Iterable[SearchDocument]) -> None:
        """全量清空 search_index 后批量 INSERT，并刷新 last_rebuilt_at（幂等）."""
        await self._session.execute(text("DELETE FROM search_index"))
        params = [
            {
                "title": doc.title,
                "body": doc.body,
                "entity_type": doc.entity_type,
                "entity_id": doc.entity_id,
                "project_id": doc.project_id,
            }
            for doc in documents
        ]
        if params:
            await self._session.execute(_INSERT_DOC_SQL, params)
        await self._set_last_rebuilt()
        await self._session.commit()

    async def incremental_sync(
        self,
        documents: Iterable[SearchDocument],
        deleted: Iterable[builtins.tuple[str, int]],
    ) -> None:
        """先删 deleted 对、再对 documents 按 (entity_type, entity_id) 删旧插新（spec §5.3）.

        deleted 与 documents 可能覆盖同一 (entity_type, entity_id)：
        先处理 deleted 清旧行，后插入 documents 新行，保证净效果为替换。
        """
        delete_sql = text(
            "DELETE FROM search_index "
            "WHERE entity_type = :entity_type AND entity_id = :entity_id"
        )
        for entity_type, entity_id in deleted:
            await self._session.execute(
                delete_sql,
                {"entity_type": entity_type, "entity_id": entity_id},
            )
        for doc in documents:
            await self._session.execute(
                delete_sql,
                {"entity_type": doc.entity_type, "entity_id": doc.entity_id},
            )
            await self._session.execute(
                _INSERT_DOC_SQL,
                {
                    "title": doc.title,
                    "body": doc.body,
                    "entity_type": doc.entity_type,
                    "entity_id": doc.entity_id,
                    "project_id": doc.project_id,
                },
            )
        await self._set_last_rebuilt()
        await self._session.commit()

    async def query(
        self,
        match: str,
        project_ids: builtins.list[int],
        types: builtins.list[str] | None,
        limit: int,
        offset: int,
    ) -> builtins.tuple[int, builtins.list[SearchHit]]:
        """FTS5 MATCH 查询，返回 (total, hits)；snippet 高亮 + rank 分数.

        snippet 列索引 = 1（第 1 列 body；第 0 列 title 不参与高亮，spec §5.4）；
        total 为同条件 COUNT(*)（不受 limit 影响）。
        """
        select_head = (
            "SELECT entity_type, entity_id, project_id, title, "
            "snippet(search_index, 1, '<mark>', '</mark>', '…', 48) AS snippet, "
            "rank AS score "
            "FROM search_index "
            "WHERE search_index MATCH :match AND project_id IN :project_ids"
        )
        count_head = (
            "SELECT COUNT(*) FROM search_index "
            "WHERE search_index MATCH :match AND project_id IN :project_ids"
        )
        type_clause = " AND entity_type IN :types" if types is not None else ""

        in_binds: list[BindParameter[Any]] = [
            bindparam("match"),
            bindparam("project_ids", expanding=True),
        ]
        if types is not None:
            in_binds.append(bindparam("types", expanding=True))

        query_stmt = text(
            select_head + type_clause + " ORDER BY rank LIMIT :limit OFFSET :offset"
        ).bindparams(*in_binds, bindparam("limit"), bindparam("offset"))
        count_stmt = text(count_head + type_clause).bindparams(*in_binds)

        params: dict[str, object] = {"match": match, "project_ids": project_ids}
        if types is not None:
            params["types"] = types

        result = await self._session.execute(
            query_stmt, {**params, "limit": limit, "offset": offset}
        )
        count_row = await self._session.execute(count_stmt, params)
        total = int(count_row.scalar() or 0)

        hits = [
            SearchHit(
                entity_type=SearchEntityType(row.entity_type),
                entity_id=uuid.UUID(int=row.entity_id),
                project_id=uuid.UUID(int=row.project_id),
                title=row.title,
                snippet=row.snippet,
                score=float(row.score),
            )
            for row in result.all()
        ]
        return total, hits

    async def get_setting(self, key: str) -> str | None:
        """读 search_meta 键值；缺失键返回 None（如 ai_maintenance 默认 None）."""
        result = await self._session.execute(
            text("SELECT value FROM search_meta WHERE key = :key"),
            {"key": key},
        )
        return result.scalar()

    async def set_setting(self, key: str, value: str) -> None:
        """写 search_meta 键值并 commit."""
        await self._session.execute(
            _UPSERT_META_SQL,
            {"key": key, "value": value},
        )
        await self._session.commit()

    async def _set_last_rebuilt(self) -> None:
        """upsert last_rebuilt_at = now(UTC) ISO 格式（与 spec §8.2 判脏约定一致）."""
        await self._session.execute(
            _UPSERT_META_SQL,
            {"key": _LAST_REBUILT_KEY, "value": datetime.now(UTC).isoformat()},
        )

    @staticmethod
    def _as_utc(value: object) -> datetime:
        """归一化为 UTC aware datetime（SQLite 读回 str / naive datetime 按 UTC 处理）."""
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
