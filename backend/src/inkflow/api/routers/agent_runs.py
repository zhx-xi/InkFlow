"""F27 Agent Runs REST API — run 决策轨迹查询 + 草稿确认流（spec §3）.

与既有 agent.py（pipelines 管线端点）同前缀 /api/v1/agent、不同文件——FastAPI
按路由路径去重，两个 router 允许共存（tasks 的 runs/drafts 查询确认流）。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from inkflow.api.deps import get_agent_run_repo, get_draft_service
from inkflow.domain.models.draft import DraftStatus
from inkflow.domain.services._word_count import count_words
from inkflow.domain.services.draft_service import (
    DraftNotFoundError,
    DraftService,
    DraftStateError,
)
from inkflow.infrastructure.database.repositories.agent_run_repo import (
    SQLiteAgentRunRepository,
)

router = APIRouter(prefix="/api/v1/agent", tags=["AgentRuns"])


def _parse_id(id_str: str, detail: str = "资源不存在") -> uuid.UUID:
    """安全解析 UUID（镜像 agent.py）."""
    try:
        return uuid.UUID(id_str)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=detail) from err


def _dump(obj: BaseModel | dict) -> dict:
    """领域实体 → JSON dict；测试 mock 直返 dict 时原样透传."""
    if isinstance(obj, dict):
        return obj
    return obj.model_dump(mode="json")


@router.get("/runs")
async def list_runs(
    project_id: uuid.UUID = Query(...),
    limit: int = Query(20, ge=1, le=100),
    repo: SQLiteAgentRunRepository = Depends(get_agent_run_repo),
) -> dict:
    """项目 run 列表（倒序，分页）→ {"items": [...], "total": N}."""
    items, total = await repo.list(project_id=project_id, limit=limit)
    return {"items": [_dump(r) for r in items], "total": total}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    repo: SQLiteAgentRunRepository = Depends(get_agent_run_repo),
) -> dict:
    """单次 run 决策轨迹（steps 全量）→ run dict / 404."""
    run = await repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return _dump(run)


@router.get("/drafts")
async def list_drafts(
    project_id: uuid.UUID = Query(...),
    status: str | None = Query(None),
    svc: DraftService = Depends(get_draft_service),
) -> dict:
    """草稿列表（用户确认入口）→ {"items": [...], "total": N}."""
    status_enum = DraftStatus(status) if status else None
    items, total = await svc.list(project_id, status=status_enum)
    return {"items": [_dump(d) for d in items], "total": total}


class ConfirmRequest(BaseModel):
    """draft confirm 请求体 — chapter_id 可选（草稿未绑定时指定）."""

    chapter_id: uuid.UUID | None = None


@router.post("/drafts/{draft_id}/confirm")
async def confirm_draft(
    draft_id: str,
    body: ConfirmRequest | None = None,
    svc: DraftService = Depends(get_draft_service),
) -> dict:
    """确认草稿 → 写入正式章节 + draft 置 CONFIRMED."""
    try:
        draft = await svc.confirm(
            draft_id,
            chapter_id=body.chapter_id if body else None,
        )
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "draft_id": draft.id,
        "status": draft.status.value,
        "chapter_id": str(draft.chapter_id) if draft.chapter_id else None,
    }


@router.post("/drafts/{draft_id}/reject")
async def reject_draft(
    draft_id: str,
    svc: DraftService = Depends(get_draft_service),
) -> dict:
    """拒绝草稿（保留记录）."""
    try:
        draft = await svc.reject(draft_id)
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"draft_id": draft.id, "status": draft.status.value}


class DraftUpdateRequest(BaseModel):
    """draft 编辑请求体 — content 必填非空（镜像 DraftService.create 语义）."""

    content: str = Field(..., min_length=1)  # Pydantic min_length=1 防空串


@router.patch("/drafts/{draft_id}")
async def update_draft(
    draft_id: str,
    body: DraftUpdateRequest,
    svc: DraftService = Depends(get_draft_service),
) -> dict:
    """编辑草稿正文（确认前手动修改；F28 diff 事件捕获入口）."""
    try:
        draft = await svc.update(draft_id, body.content)
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    learned = bool(getattr(svc, "last_learned", False))
    return {
        "draft_id": draft.id,
        "status": draft.status.value,
        "word_count": count_words(draft.content),
        "learned": learned,
    }


class PruneOrphansRequest(BaseModel):
    """prune-orphans 请求体 — dry_run 可选（默认 False）."""

    dry_run: bool = False


@router.post("/drafts/prune-orphans")
async def prune_orphan_drafts(
    body: PruneOrphansRequest | None = None,
    svc: DraftService = Depends(get_draft_service),
) -> dict:
    """删除孤儿草稿（project_id=全零，#275 数据清理）→ {"deleted": N}."""
    count = await svc.prune_orphans(dry_run=body.dry_run if body else False)
    return {"deleted": count}
