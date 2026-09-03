"""日志 REST API — 前端桥接上报 + 日志页查询（F57 #888-S1 / spec §3）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from inkflow.core.config import config
from inkflow.logging import StructuredLogRecord, StructuredLogStore, mask_fields

router = APIRouter(prefix="/api/v1/logs", tags=["Logs"])


def get_log_store() -> StructuredLogStore:
    """按 config.data_dir 派生结构化日志目录（POST/GET 复用同一 store 目录）。"""
    return StructuredLogStore(config.data_dir / "logs" / "structured")


def _parse_query_ts(value: str | None) -> datetime | None:
    """解析查询参数 ISO 时间串为 aware datetime（naive 按 UTC；非法→None）。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


class LogRecordInput(BaseModel):
    level: str = "INFO"
    caller_type: Literal["api", "agent", "llm", "tool", "cli", "mcp", "frontend"]
    caller_name: str
    event: str
    message_key: str
    params: dict = Field(default_factory=dict)
    correlation_id: str = ""
    project_id: int | None = None
    entity_id: str | None = None
    duration_ms: float | None = None
    error_code: str | None = None


@router.get("")
async def query_logs(
    level: str | None = None,
    caller_type: str | None = None,
    project_id: int | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    q: str | None = None,
    correlation_id: str | None = None,
    page: int = 0,
    limit: int = 50,
    store: StructuredLogStore = Depends(get_log_store),
) -> dict:
    """日志页查询 → F7 信封 {ok, data:{items,total,offset,limit}}。"""
    items, total = store.query(
        level=level,
        caller_type=caller_type,
        project_id=project_id,
        from_ts=_parse_query_ts(from_),
        to_ts=_parse_query_ts(to),
        q=q,
        correlation_id=correlation_id,
        page=page,
        limit=limit,
    )
    return {
        "ok": True,
        "data": {"items": items, "total": total, "offset": page * limit, "limit": limit},
    }


@router.post("")
async def ingest_log(
    record: LogRecordInput,
    store: StructuredLogStore = Depends(get_log_store),
) -> dict:
    """前端桥接上报：脱敏 params → 构建 StructuredLogRecord → 落 store → {ok: true}。"""
    rec = StructuredLogRecord(
        level=record.level.upper() if record.level else "INFO",
        logger="inkflow",
        caller_type=record.caller_type,
        caller_name=record.caller_name,
        event=record.event,
        message_key=record.message_key,
        params=cast(dict, mask_fields(record.params or {})),
        correlation_id=record.correlation_id,
        project_id=record.project_id,
        entity_id=record.entity_id,
        duration_ms=record.duration_ms,
        error_code=record.error_code,
    )
    store.append(rec)
    return {"ok": True}
