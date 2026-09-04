"""日志 REST API — 前端桥接上报 + 日志页查询（F57 #888-S1 / spec §3）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from inkflow.core.config import config
from inkflow.logging import StructuredLogRecord, StructuredLogStore, instrument, mask_fields

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


def _resolve_project_id(value: str | None) -> int | None:
    """解析 project_id 查询参数（B3 #496）：None→None；纯数字→int；合法 UUID→.int；非法→422。

    Args:
        value: FastAPI 查询参数原始串（None = 未提供，不过滤）。

    Returns:
        仓储层 int 主键（UUID 取 uuid.UUID(value).int，与 F1 `_to_int_id` 口径一致）。

    Raises:
        HTTPException: 非数字非 UUID → 422 detail 逐字
            「project_id 须为整数或合法 UUID」。须在 query_logs 函数体内调用
            （@instrument 才能捕获端点内异常产生 WARN E_HTTP_422 埋点——
            contract-496 §2 实现约束；走 Depends 抛错则 B4 回查落空）。
    """
    if value is None:
        return None
    if value.isdigit():
        return int(value)
    try:
        return uuid.UUID(value).int
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="project_id 须为整数或合法 UUID",
        ) from exc


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
@instrument(caller_type="api")
async def query_logs(
    level: str | None = None,
    caller_type: str | None = None,
    project_id: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    q: str | None = None,
    correlation_id: str | None = None,
    page: int = 0,
    limit: int = 50,
    store: StructuredLogStore = Depends(get_log_store),
) -> dict:
    """日志页查询 → F7 信封 {ok, data:{items,total,offset,limit}}。"""
    # 直调面（test_logs_i18n_direct 既有形态）直接传 int 主键原样透传；
    # HTTP 面经 FastAPI 恒为 str/None → 走 _resolve_project_id 归一（UUID→int）。
    resolved_project_id = (
        _resolve_project_id(project_id) if isinstance(project_id, str) else project_id
    )
    items, total = store.query(
        level=level,
        caller_type=caller_type,
        project_id=resolved_project_id,
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
@instrument(caller_type="api")
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
