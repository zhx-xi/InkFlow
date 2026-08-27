"""#708 coverage 补测 鈥?context 路由缺口分支（直接调用 endpoint）。

被测模块: ``inkflow.api.routers.context``
补齐缺口:
- get_chapter_summary: ensure_summary 抛 ValueError 鈫?404（85 行）
- refresh_chapter_summary: 章节不存在 鈫?404（107->108 + 108 行）
- refresh_chapter_summary: 项目缺失 鈫?回退全局默认模型（111->112 + 112 行）
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from inkflow.api.routers import context as context_mod

CHAPTER_ID = str(uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8"))


def _patch_services(
    monkeypatch: pytest.MonkeyPatch,
    *,
    summary_svc: AsyncMock,
    chapter_svc: AsyncMock,
    project_svc: AsyncMock,
) -> None:
    """把模块级三个 service 工厂替换为给定 mock。"""
    monkeypatch.setattr(context_mod, "get_summary_service", lambda db: summary_svc, raising=False)
    monkeypatch.setattr(context_mod, "get_chapter_service", lambda db: chapter_svc, raising=False)
    monkeypatch.setattr(context_mod, "get_project_service", lambda db: project_svc, raising=False)


async def test_get_summary_value_error_maps_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """ensure_summary 抛 ValueError 鈫?404（85 行 except 分支）。"""
    summary_svc = AsyncMock()
    summary_svc.ensure_summary = AsyncMock(side_effect=ValueError("章节不存在"))
    chapter = SimpleNamespace(project_id=uuid.uuid4())
    chapter_svc = AsyncMock()
    chapter_svc.get_chapter = AsyncMock(return_value=chapter)
    project_svc = AsyncMock()
    project_svc.get = AsyncMock(return_value=None)
    _patch_services(
        monkeypatch,
        summary_svc=summary_svc,
        chapter_svc=chapter_svc,
        project_svc=project_svc,
    )

    with pytest.raises(HTTPException) as exc:
        await context_mod.get_chapter_summary(chapter_id=CHAPTER_ID, db=object())

    assert exc.value.status_code == 404


async def test_refresh_summary_chapter_missing_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """refresh 时章节不存在 鈫?404（107->108 + 108 行）。"""
    summary_svc = AsyncMock()
    chapter_svc = AsyncMock()
    chapter_svc.get_chapter = AsyncMock(return_value=None)
    project_svc = AsyncMock()
    _patch_services(
        monkeypatch,
        summary_svc=summary_svc,
        chapter_svc=chapter_svc,
        project_svc=project_svc,
    )

    with pytest.raises(HTTPException) as exc:
        await context_mod.refresh_chapter_summary(chapter_id=CHAPTER_ID, db=object())

    assert exc.value.status_code == 404


async def test_refresh_summary_project_missing_uses_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """项目缺失 鈫?model 回退全局默认（111->112 + 112 行）。"""
    summary_svc = AsyncMock()
    summary_svc.ensure_summary = AsyncMock(return_value="摘要")
    chapter = SimpleNamespace(project_id=uuid.uuid4())
    chapter_svc = AsyncMock()
    chapter_svc.get_chapter = AsyncMock(return_value=chapter)
    project_svc = AsyncMock()
    project_svc.get = AsyncMock(return_value=None)
    _patch_services(
        monkeypatch,
        summary_svc=summary_svc,
        chapter_svc=chapter_svc,
        project_svc=project_svc,
    )

    result = await context_mod.refresh_chapter_summary(chapter_id=CHAPTER_ID, db=object())

    assert result["summary"] == "摘要"
    call_kwargs = summary_svc.ensure_summary.await_args.kwargs
    assert call_kwargs["model"] == context_mod.app_config.llm_default_model
    assert call_kwargs["force"] is True
