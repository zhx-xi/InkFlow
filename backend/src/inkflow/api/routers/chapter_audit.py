"""F34 章节审计 REST API — 触发审计 / 用户确认 / 审计记录查询.

三个端点（spec §3.1）:
- POST /projects/{project_id}/chapters/{chapter_id}/audit
  （body: AuditTriggerRequest）→ 200 完整 ChapterAuditReport
- POST /projects/{project_id}/chapters/{chapter_id}/audit/confirm
  （body: AuditConfirmRequest）→ 200 {status, confirmed_at}
- GET  /projects/{project_id}/audit-logs → 200 {total, logs}（分页）

端点风格沿用 F15 audit.py / F16 style.py：`Depends(get_db)` 注入数据库
session，再经模块级 `_get_svc(db)` 获取 ChapterAuditService——单元测试
通过 `@patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")`
mock 服务层（同 F9-F16 模式）。

错误映射（spec §3.3 异常映射表）:
- 无效 UUID（_parse_id / _parse_chapter_id）→ 404「项目不存在/章节不存在」
- ProjectNotFoundError / ChapterNotFoundError → 404，消息即 detail
- NoPendingAuditError → 422，消息即 detail
- 其余异常 → 500「内部错误: ...」

依据: specs/f34-chapter-audit/spec.md §3/§7/§9。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_chapter_audit_service, get_db
from inkflow.domain.models.chapter_audit import (
    AuditConfirmRequest,
    AuditTriggerRequest,
)
from inkflow.domain.ports.chapter_audit_errors import NoPendingAuditError
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ChapterNotFoundError
from inkflow.domain.services.chapter_audit_service import ChapterAuditService
from inkflow.logging import instrument

router = APIRouter(prefix="/api/v1", tags=["章节审计"])


def _parse_id(project_id: str) -> uuid.UUID:
    """安全解析项目 ID 字符串，支持 UUID 格式和整数格式（同 F9-F16）.

    无效 UUID → 404「项目不存在」（spec §3.3，统一解析失败处理，
    不进入服务层）。
    """
    try:
        return uuid.UUID(project_id)
    except ValueError:
        try:
            return uuid.UUID(int=int(project_id))
        except (ValueError, OverflowError) as err:
            raise HTTPException(status_code=404, detail="项目不存在") from err


def _parse_chapter_id(chapter_id: str) -> uuid.UUID:
    """安全解析章节 ID 字符串，支持 UUID 格式和整数格式（同 F9-F16）.

    无效 UUID → 404「章节不存在」（spec §3.3，与 project_id 两段路径
    参数独立解析）。
    """
    try:
        return uuid.UUID(chapter_id)
    except ValueError:
        try:
            return uuid.UUID(int=int(chapter_id))
        except (ValueError, OverflowError) as err:
            raise HTTPException(status_code=404, detail="章节不存在") from err


def _get_svc(db: AsyncSession) -> ChapterAuditService:
    """获取 ChapterAuditService 实例（方便 mock）."""
    return get_chapter_audit_service(db)


async def _run_service(coro: Awaitable[Any]) -> Any:
    """执行服务调用并统一映射业务异常到 HTTP 状态码（spec §3.3）.

    404: ProjectNotFoundError（项目不存在）/ ChapterNotFoundError（章节不存在），
        消息即 detail。
    422: NoPendingAuditError（该章无待确认审计），消息即 detail。
    500: 其余异常（DB 读取失败等）→「内部错误: ...」。
    """
    try:
        return await coro
    except ProjectNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ChapterNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except NoPendingAuditError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"内部错误: {e}") from e


@router.post("/projects/{project_id}/chapters/{chapter_id}/audit")
@instrument(caller_type="api")
async def trigger_audit(
    request: AuditTriggerRequest,
    project_id: str,
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """手动触发单章审计（spec §3.1）——返回完整 ChapterAuditReport.

    include_static 透传服务层（默认 True，spec §2.4 AuditTriggerRequest），
    model_dump(mode="json") 信封序列化（spec §3.2）。
    """
    pid = _parse_id(project_id)
    cid = _parse_chapter_id(chapter_id)
    svc = _get_svc(db)
    report = await _run_service(svc.audit(pid, cid, include_static=request.include_static))
    return report.model_dump(mode="json")


@router.post("/projects/{project_id}/chapters/{chapter_id}/audit/confirm")
@instrument(caller_type="api")
async def confirm_audit(
    request: AuditConfirmRequest,
    project_id: str,
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """用户确认审计结果（accept/reject，spec §3.1）——返回状态与确认时间.

    action/note 透传服务层（spec §2.4 AuditConfirmRequest），confirmed_at
    ISO 序列化（无确认时为 null）。
    """
    pid = _parse_id(project_id)
    cid = _parse_chapter_id(chapter_id)
    svc = _get_svc(db)
    log = await _run_service(svc.confirm(pid, cid, action=request.action, note=request.note))
    return {
        "status": log.status,
        "confirmed_at": log.confirmed_at.isoformat() if log.confirmed_at else None,
    }


@router.get("/projects/{project_id}/audit-logs")
@instrument(caller_type="api")
async def list_audit_logs(
    project_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """审计记录分页查询（spec §3.1 / §7 E15）——返回 total + logs.

    limit 默认 20、范围 [1,100]；offset 默认 0、下界 0；越界由 FastAPI
    Query 校验拦为 422（服务层不被调用）。
    """
    pid = _parse_id(project_id)
    svc = _get_svc(db)
    logs, total = await _run_service(svc.list_logs(pid, offset=offset, limit=limit))
    return {"total": total, "logs": [log.model_dump(mode="json") for log in logs]}
