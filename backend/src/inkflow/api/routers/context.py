"""上下文管理 REST API — 调试与验证端点.

F6 是内部服务，正常写作路径由 F3 直接调用（无 HTTP）。
以下端点用于调试与验证。

端点:
    POST   /api/v1/context/assemble      — 组装上下文（调试）
    GET    /api/v1/context/chapters/{id}/summary       — 查看摘要缓存
    POST   /api/v1/context/chapters/{id}/summary/refresh — 强制重新生成摘要

依据: specs/f6-context-service/spec.md §5.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import (
    get_chapter_service,
    get_context_service,
    get_db,
    get_project_service,
    get_summary_service,
)
from inkflow.core.config import config as app_config
from inkflow.domain.models.context import ContextRequest
from inkflow.domain.ports.context_errors import ContextBudgetExceededError

router = APIRouter(prefix="/api/v1/context", tags=["上下文管理"])


# ── 组装上下文 ───────────────────────────────────────────────────


@router.post("/assemble")
async def assemble_context(
    request: ContextRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """组装上下文（调试端点）.

    与 F3 调用 build_context 的路径一致，用于独立验证组装结果.
    """
    svc = get_context_service(db)
    try:
        result = await svc.build_context(request)
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ContextBudgetExceededError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 摘要查看 ─────────────────────────────────────────────────────


@router.get("/chapters/{chapter_id}/summary")
async def get_chapter_summary(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查看章节摘要缓存."""
    try:
        cid = uuid.UUID(chapter_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail="章节不存在") from err

    svc = get_summary_service(db)
    try:
        # #329：model 走项目 config.model（与写作链路一致）→ 回退全局默认
        cid_int = cid.int
        chapter = await get_chapter_service(db).get_chapter(cid_int)
        if chapter is None:
            raise HTTPException(status_code=404, detail="章节不存在")
        project = await get_project_service(db).get(chapter.project_id)
        model = project.config.model if project else ""
        if not model:
            model = app_config.llm_default_model
        summary_text = await svc.ensure_summary(cid, model=model)
        return {"summary": summary_text, "chapter_id": str(cid)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ── 强制刷新摘要 ──────────────────────────────────────────────────


@router.post("/chapters/{chapter_id}/summary/refresh")
async def refresh_chapter_summary(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """强制重新生成章节摘要."""
    try:
        cid = uuid.UUID(chapter_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail="章节不存在") from err

    svc = get_summary_service(db)
    try:
        # #329：model 走项目 config.model（与写作链路一致）→ 回退全局默认
        cid_int = cid.int
        chapter = await get_chapter_service(db).get_chapter(cid_int)
        if chapter is None:
            raise HTTPException(status_code=404, detail="章节不存在")
        project = await get_project_service(db).get(chapter.project_id)
        model = project.config.model if project else ""
        if not model:
            model = app_config.llm_default_model
        summary_text = await svc.ensure_summary(cid, model=model, force=True)
        return {"summary": summary_text, "chapter_id": str(cid)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
