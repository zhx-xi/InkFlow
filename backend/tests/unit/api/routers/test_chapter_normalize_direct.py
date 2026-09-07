"""#999 批量归一化端点 handler 同线程直接调用 — func-cov 门禁补偿。

镜像 backend/tests/unit/api/routers/test_logs_i18n_direct.py 形态：
api 层测试走 TestClient → FastAPI 在独立线程/事件循环运行 handler；func_cov_plugin
的 ``sys.settrace`` 是 per-thread，无法记录该线程的 handler 调用 → 经 HTTP 触达的
``normalize_chapter_titles`` 被判为「未调用」。本文件在主线程直接调用该 handler
（+ body 模型构造），覆盖成功 / 404 / 422 三条路径。

契约定稿 .hermes/plans/999-contract.md §4:
- 端点 POST /api/v1/projects/{pid}/chapters/normalize-titles，注册于 api/routers/chapter.py，
  形如既有端点（@instrument(caller_type="api")）。
- body / 404 / 200 响应体契约见 §4；service 由 ``get_chapter_service(db)`` 提供。

假设名（GREEN 实现据此对齐；若实现命名不同需同步）:
- handler: ``inkflow.api.routers.chapter.normalize_chapter_titles``
- body 模型: ``inkflow.api.routers.chapter.NormalizeTitlesRequest``

实现不存在 → 模块 import 即 ImportError → 本文件收集期 ERROR（RED 形态）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from inkflow.api.routers import chapter as chapter_router

# 固定项目 UUID（解析路径参数用；404 路径直接用非法串触发 _parse_id 404）
PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


def _body(fmt: str):
    """构造请求体模型（假设名 NormalizeTitlesRequest）。"""
    return chapter_router.NormalizeTitlesRequest(format=fmt)


@pytest.mark.asyncio
async def test_normalize_chapter_titles_success():
    """200：handler 返回 format/outlines_replaced/chapters_replaced，service 收到 (PID, fmt)。"""
    with patch("inkflow.api.routers.chapter.get_chapter_service") as mock_get_svc:
        svc = MagicMock()
        svc.normalize_all_titles = AsyncMock(
            return_value={"chapters_replaced": 1, "outlines_replaced": 0}
        )
        mock_get_svc.return_value = svc

        result = await chapter_router.normalize_chapter_titles(
            project_id=str(PID),
            data=_body("chinese"),
            db=MagicMock(),
        )

    assert result == {"format": "chinese", "chapters_replaced": 1, "outlines_replaced": 0}
    svc.normalize_all_titles.assert_awaited_once_with(PID, "chinese")


@pytest.mark.asyncio
async def test_normalize_chapter_titles_project_not_found_404():
    """项目 ID 非法/不存在 → HTTPException 404（detail '项目不存在'）。"""
    with patch("inkflow.api.routers.chapter.get_chapter_service") as mock_get_svc:
        svc = MagicMock()
        svc.normalize_all_titles = AsyncMock(
            return_value={"chapters_replaced": 0, "outlines_replaced": 0}
        )
        mock_get_svc.return_value = svc

        with pytest.raises(HTTPException) as ei:
            await chapter_router.normalize_chapter_titles(
                project_id="not-a-project",
                data=_body("chinese"),
                db=MagicMock(),
            )

    assert ei.value.status_code == 404
    assert ei.value.detail == "项目不存在"
    svc.normalize_all_titles.assert_not_awaited()


def test_normalize_chapter_titles_invalid_format_422():
    """非法 format → body 模型构造抛 Pydantic ValidationError（router 层 422 兜住）。"""
    with pytest.raises(ValidationError):
        _body("weird")


def test_normalize_chapter_titles_missing_format_422():
    """缺 format → body 模型构造抛 Pydantic ValidationError（必填）。"""
    with pytest.raises(ValidationError):
        chapter_router.NormalizeTitlesRequest()
