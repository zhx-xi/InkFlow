"""F34 章节审计 REST API — 触发审计 / 用户确认 / 审计记录查询 / 明细读口.

四个端点（spec §3.1）:
- POST /projects/{project_id}/chapters/{chapter_id}/audit
  （body: AuditTriggerRequest）→ 200 完整 ChapterAuditReport
- POST /projects/{project_id}/chapters/{chapter_id}/audit/confirm
  （body: AuditConfirmRequest）→ 200 {status, confirmed_at}
- GET  /projects/{project_id}/audit-logs → 200 {total, logs}（分页）
- GET  /audit-logs/{log_id} → 200 AuditLogDetail（#1420 findings 明细读口）

端点风格沿用 F15 audit.py / F16 style.py：`Depends(get_db)` 注入数据库
session，再经模块级服务工厂获取 ChapterAuditService——带项目段的端点走
`_get_svc(db, project_id)`（附带项目级 model 解析）；#1420 读口
`GET /audit-logs/{log_id}` 无项目上下文，直接走 `get_chapter_audit_service(db)`。
单元测试通过 `@patch("inkflow.api.routers.chapter_audit.get_chapter_audit_service")`
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

from inkflow.api.deps import get_chapter_audit_service, get_db, get_project_service
from inkflow.domain.models.chapter_audit import (
    AuditConfirmRequest,
    AuditRunInfo,
    AuditTriggerRequest,
)
from inkflow.domain.ports.chapter_audit_errors import AuditLogNotFoundError, NoPendingAuditError
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ChapterNotFoundError
from inkflow.domain.services.chapter_audit_service import ChapterAuditService
from inkflow.infrastructure.background.tasks import spawn_background_task
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


def _parse_log_id(log_id: str) -> uuid.UUID:
    """安全解析审计记录 ID 字符串，支持 UUID 格式和整数格式（同 _parse_id）.

    无效 UUID → 404「审计记录不存在」（统一解析失败处理，不进入服务层）。
    """
    try:
        return uuid.UUID(log_id)
    except ValueError:
        try:
            return uuid.UUID(int=int(log_id))
        except (ValueError, OverflowError) as err:
            raise HTTPException(status_code=404, detail="审计记录不存在") from err


async def _get_svc(db: AsyncSession, project_id: uuid.UUID) -> ChapterAuditService:
    """获取 ChapterAuditService 实例（方便 mock）.

    #1269：装配前先取项目级 model（`projects.config.model`）注入——
    打包产物（隔离数据目录）无全局模型时，裸构造会让审计恒降级。
    取值异常/项目不存在 → None（回落全局默认；404 判定仍由服务层负责）。
    """
    project_model: str | None = None
    try:
        project = await get_project_service(db).get(project_id)
        config_obj = getattr(project, "config", None) if project is not None else None
        value = getattr(config_obj, "model", None)
        project_model = value if isinstance(value, str) and value else None
    except Exception:  # 配置不可达绝不炸装配（回退全局默认 / 422 诊断）
        project_model = None
    return get_chapter_audit_service(db, project_model=project_model, resolve_credentials=True)


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
    except AuditLogNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"内部错误: {e}") from e


@router.post("/projects/{project_id}/chapters/{chapter_id}/audit", status_code=202)
@instrument(caller_type="api")
async def trigger_audit(
    request: AuditTriggerRequest,
    project_id: str,
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """手动触发单章审计（spec §3.1 / §5.1 v1.5）——**202 异步受理**.

    #1425：端点只做「校验 + 受理」——`submit()` 返回 `(log, created)`；`created=True`
    时经 `spawn_background_task` 派发后台执行（fire-and-forget，F44 #456 先例），
    响应体 `{log_id, status}`（status = 任务执行态 running/completed）。
    幂等复用（`created=False`）不派发任务、不新增记录（spec §7 E22）。
    include_static 透传服务层（默认 True，spec §2.4 AuditTriggerRequest）。
    """
    pid = _parse_id(project_id)
    cid = _parse_chapter_id(chapter_id)
    svc = await _get_svc(db, pid)
    log, created = await _run_service(svc.submit(pid, cid, include_static=request.include_static))
    if created:
        spawn_background_task(
            svc.run_audit_job(pid, cid, log.id, include_static=request.include_static),
            key=str(log.id),
        )
    return {"log_id": str(log.id), "status": log.run_status.value}


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
    svc = await _get_svc(db, pid)
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
    svc = await _get_svc(db, pid)
    logs, total = await _run_service(svc.list_logs(pid, offset=offset, limit=limit))
    return {"total": total, "logs": [log.model_dump(mode="json") for log in logs]}


@router.get("/audit-logs/{log_id}")
@instrument(caller_type="api")
async def get_audit_log(
    log_id: str,
    db: AsyncSession = Depends(get_db),
):
    """按审计记录 ID 取回审计明细（#1420）——轻量记录元信息 + findings 快照.

    客户端超时后（POST 响应被丢弃）的恢复路径：`--history` 找到记录 ID → 本端点取明细。
    """
    lid = _parse_log_id(log_id)
    svc = get_chapter_audit_service(db)
    detail = await _run_service(svc.get_log(lid))
    return detail.model_dump(mode="json")


@router.get("/audit-logs/{log_id}/status")
@instrument(caller_type="api")
async def get_audit_log_status(
    log_id: str,
    db: AsyncSession = Depends(get_db),
):
    """按审计记录 ID 取任务运行状态（#1425 轮询读口，spec §3.1）——轻量，不含 findings.

    `run_status` = running / completed / failed；失败原因在 `error`。
    执行完成后取 findings 走 v1.4 读口 `GET /api/v1/audit-logs/{log_id}`（复用）。
    """
    lid = _parse_log_id(log_id)
    svc = get_chapter_audit_service(db)
    log = await _run_service(svc.get_status(lid))
    return AuditRunInfo(
        log_id=log.id,
        run_status=log.run_status,
        status=log.status,
        degraded=log.degraded,
        error=log.error,
        chapter_id=log.chapter_id,
        chapter_title=log.chapter_title,
        created_at=log.created_at,
    ).model_dump(mode="json")
