"""F24 会话管理 REST API — 12 个端点：会话 CRUD + 四态状态机 + 履历日志.

端点风格沿用 F12/F13：会话为全局资源（不嵌套项目路径——任务履历跨项目，
spec §4 决策 4）；路径前缀 /api/v1 + 静态动作段（pause/resume/complete/fail/
restore），与动态会话 ID 无冲突。

各端点通过 `Depends(get_db)` 注入数据库 session，再调用模块级
`get_session_service(db)` 获取 SessionService —— 单元测试通过
`@patch("inkflow.api.routers.sessions.get_session_service")` 来 mock
服务层（同 F9-F13 模式）。

错误映射（spec §8.1 异常映射表）:
- 无效 UUID → 404「会话不存在」（同 F12 _parse_id 模式）
- SessionNotFoundError / F9 ProjectNotFoundError → 404（detail = str(e)）
- SessionServiceError（含 SessionTransitionError）→ 422（detail = str(e)）
- 其余异常 → 500 {"detail": "数据库错误"}（spec §3.4 DB_ERROR）

响应序列化: 时间戳统一 UTC aware（naive 视为 UTC，spec §3.2 响应 Z 后缀；
真实服务/仓储产出均 aware，此处仅兜底 naive 输入），保证响应契约一致。

依据: specs/f24-session-service/spec.md §3/§7/§8。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db, get_session_service
from inkflow.domain.models.session import (
    SessionComplete,
    SessionCreate,
    SessionFail,
    SessionLogCreate,
    SessionStatus,
    SessionType,
    SessionUpdate,
)
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.session_errors import (
    SessionNotFoundError,
    SessionServiceError,
    SessionTransitionError,
)
from inkflow.domain.services.session_service import SessionService

router = APIRouter(prefix="/api/v1", tags=["会话"])


def _parse_id(id_str: str, detail: str = "会话不存在") -> uuid.UUID:
    """安全解析 ID 字符串，支持 UUID 格式和整数格式（同 F12/F13）。"""
    try:
        return uuid.UUID(id_str)
    except ValueError:
        try:
            return uuid.UUID(int=int(id_str))
        except (ValueError, OverflowError) as err:
            raise HTTPException(status_code=404, detail=detail) from err


def _get_svc(db: AsyncSession) -> SessionService:
    """获取 SessionService 实例（方便 mock）。"""
    return get_session_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §8.1）。"""
    try:
        return await coro
    except SessionTransitionError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except SessionServiceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="数据库错误") from e


def _utc_aware(value: Any) -> Any:
    """递归将 naive datetime 归一为 UTC aware（aware 值原样保留）。"""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, dict):
        return {k: _utc_aware(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_utc_aware(v) for v in value]
    return value


def _dump(model: BaseModel) -> dict[str, Any]:
    """序列化模型为 JSON dict（datetime 统一 UTC，spec §3.2 响应 Z 后缀）。"""
    data = _utc_aware(model.model_dump(mode="python"))
    return type(model).model_validate(data).model_dump(mode="json")


# ── 会话 CRUD ─────────────────────────────────────────────


@router.post("/sessions", status_code=201)
async def create_session(
    data: SessionCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建会话（spec §3.2；创建即 active，project_id 可空）。"""
    svc = _get_svc(db)
    view = await _run_service(svc.create(data=data))
    return _dump(view)


@router.get("/sessions")
async def list_sessions(
    session_type: SessionType | None = Query(None),
    status: SessionStatus | None = Query(None),
    project_id: str | None = Query(None),
    search: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """会话列表（过滤 + 分页，spec §3.1/§6.3；project_id 解析为 UUID 透传）。"""
    pid = _parse_id(project_id, detail="会话不存在") if project_id is not None else None
    svc = _get_svc(db)
    items, total = await _run_service(
        svc.list(
            session_type=session_type,
            status=status,
            project_id=pid,
            search=search,
            offset=offset,
            limit=limit,
        )
    )
    return {
        "items": [_dump(v) for v in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """会话详情（含已归档，履历可追溯，spec §7 #7）。"""
    sid = _parse_id(session_id)
    svc = _get_svc(db)
    view = await _run_service(svc.get(session_id=sid))
    if view is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return _dump(view)


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str,
    data: SessionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """部分更新会话（SessionUpdate 全可选；status 静默忽略，spec §7 #10/#11）。"""
    sid = _parse_id(session_id)
    svc = _get_svc(db)
    session = await _run_service(svc.update(session_id=sid, data=data))
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return _dump(session)


# ── 状态机动作（spec §2.4）────────────────────────────────


@router.post("/sessions/{session_id}/pause")
async def pause_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """暂停会话（active→paused，写 paused_at=now，spec §5.2）。"""
    sid = _parse_id(session_id)
    svc = _get_svc(db)
    session = await _run_service(svc.pause(session_id=sid))
    return _dump(session)


@router.post("/sessions/{session_id}/resume")
async def resume_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """恢复会话（paused→active，清 paused_at，spec §3.3 响应 null）。"""
    sid = _parse_id(session_id)
    svc = _get_svc(db)
    session = await _run_service(svc.resume(session_id=sid))
    return _dump(session)


@router.post("/sessions/{session_id}/complete")
async def complete_session(
    session_id: str,
    data: SessionComplete,
    db: AsyncSession = Depends(get_db),
):
    """完成会话（active|paused→completed，写 completed_at=now + result，spec §5.2）。"""
    sid = _parse_id(session_id)
    svc = _get_svc(db)
    session = await _run_service(svc.complete(session_id=sid, data=data))
    return _dump(session)


@router.post("/sessions/{session_id}/fail")
async def fail_session(
    session_id: str,
    data: SessionFail,
    db: AsyncSession = Depends(get_db),
):
    """失败会话（active|paused→failed，写 completed_at=now + error，spec §5.2）。"""
    sid = _parse_id(session_id)
    svc = _get_svc(db)
    session = await _run_service(svc.fail(session_id=sid, data=data))
    return _dump(session)


# ── 履历日志（spec §2.2/§5.4）────────────────────────────


@router.post("/sessions/{session_id}/logs", status_code=201)
async def add_session_log(
    session_id: str,
    data: SessionLogCreate,
    db: AsyncSession = Depends(get_db),
):
    """追加履历日志（seq 由服务层分配，1 起；终态可追加，Q2 拍板）。"""
    sid = _parse_id(session_id)
    svc = _get_svc(db)
    entry = await _run_service(svc.add_log(session_id=sid, data=data))
    return _dump(entry)


@router.get("/sessions/{session_id}/logs")
async def list_session_logs(
    session_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """履历日志列表（seq ASC，分页，spec §3.1）。"""
    sid = _parse_id(session_id)
    svc = _get_svc(db)
    items, total = await _run_service(svc.list_logs(session_id=sid, offset=offset, limit=limit))
    return {
        "items": [_dump(e) for e in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


# ── 删除 / 恢复（spec §2.5 两级删除）──────────────────────


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """删除会话（默认归档；?force=true 真实删除，spec §2.5）。"""
    sid = _parse_id(session_id)
    svc = _get_svc(db)
    ok = await _run_service(svc.delete(session_id=sid, force=force))
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")


@router.post("/sessions/{session_id}/restore")
async def restore_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """解除归档（未归档幂等，spec §2.5）。"""
    sid = _parse_id(session_id)
    svc = _get_svc(db)
    session = await _run_service(svc.restore(session_id=sid))
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return _dump(session)
