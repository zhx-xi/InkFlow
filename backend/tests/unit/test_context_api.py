"""上下文 API 集成测试 — Mock Service 层.

测试范围 (spec §9):
    - POST /api/v1/context/assemble → 200
    - assemble protected 超预算 → 400
    - assemble 无效 UUID → 422
    - GET /summary → 200
    - GET /summary 无效章节 → 404
    - POST /summary/refresh → 200
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.context import (
    ContextAssemblyResult,
    ContextBlock,
    ContextItem,
    ContextLayer,
    ContextSourceType,
)
from inkflow.domain.ports.context_errors import ContextBudgetExceededError

client = TestClient(app)


# ── 辅助工厂 ────────────────────────────────────────────────────


def _mock_result() -> ContextAssemblyResult:
    return ContextAssemblyResult(
        blocks=[
            ContextBlock(
                item=ContextItem(
                    source=ContextSourceType.WRITING_REQUIREMENTS,
                    title="写作要求",
                    content="续写第5章",
                    priority=100,
                ),
                layer=ContextLayer.PROTECTED,
                token_count=10,
            )
        ],
        budget_tokens=102400,
        total_tokens=10,
        model="openai/gpt-4o",
        dropped=[],
    )


# ── 测试套件 ────────────────────────────────────────────────────


class TestContextAssembleAPI:
    """POST /api/v1/context/assemble 端点测试."""

    @patch("inkflow.api.routers.context.get_context_service")
    async def test_assemble_success(self, mock_get_svc: MagicMock) -> None:
        """正常组装上下文返回 200."""
        mock_svc = MagicMock()
        mock_svc.build_context = AsyncMock(return_value=_mock_result())
        mock_get_svc.return_value = mock_svc

        response = client.post(
            "/api/v1/context/assemble",
            json={
                "project_id": str(uuid.uuid4()),
                "chapter_id": str(uuid.uuid4()),
                "model": "openai/gpt-4o",
                "writing_requirements": "续写第5章，保持悬疑氛围",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "blocks" in data
        assert "budget_tokens" in data
        assert "total_tokens" in data
        assert "dropped" in data

    @patch("inkflow.api.routers.context.get_context_service")
    async def test_assemble_budget_exceeded(self, mock_get_svc: MagicMock) -> None:
        """Protected 层超预算返回 400."""
        mock_svc = MagicMock()
        mock_svc.build_context = AsyncMock(
            side_effect=ContextBudgetExceededError(
                budget=1000, required=5000, suggestion="精简写作要求"
            )
        )
        mock_get_svc.return_value = mock_svc

        response = client.post(
            "/api/v1/context/assemble",
            json={
                "project_id": str(uuid.uuid4()),
                "chapter_id": str(uuid.uuid4()),
                "model": "openai/gpt-3.5-turbo",
                "writing_requirements": "X" * 5000,
            },
        )
        assert response.status_code == 400
        assert "预算超限" in response.json()["detail"]

    async def test_assemble_missing_writing_requirements(self) -> None:
        """缺少必填字段返回 422."""
        # writing_requirements 缺失 → Pydantic 422
        response = client.post(
            "/api/v1/context/assemble",
            json={
                "project_id": str(uuid.uuid4()),
                "chapter_id": str(uuid.uuid4()),
                "model": "openai/gpt-4o",
            },
        )
        assert response.status_code == 422

    async def test_assemble_invalid_uuid(self) -> None:
        """无效 UUID 格式返回 422."""
        response = client.post(
            "/api/v1/context/assemble",
            json={
                "project_id": "not-a-uuid",
                "chapter_id": str(uuid.uuid4()),
                "model": "openai/gpt-4o",
                "writing_requirements": "test",
            },
        )
        assert response.status_code == 422


class TestSummaryAPI:
    """摘要查看/刷新端点测试."""

    @patch("inkflow.api.routers.context.get_summary_service")
    async def test_get_summary_success(self, mock_get_svc: MagicMock) -> None:
        """查看摘要返回 200."""
        mock_svc = MagicMock()
        mock_svc.ensure_summary = AsyncMock(return_value="本章摘要：冒险开始")
        mock_get_svc.return_value = mock_svc

        chapter_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/context/chapters/{chapter_id}/summary")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert data["summary"] == "本章摘要：冒险开始"

    async def test_get_summary_invalid_uuid(self) -> None:
        """无效 UUID 返回 404."""
        response = client.get("/api/v1/context/chapters/not-a-uuid/summary")
        assert response.status_code == 404

    @patch("inkflow.api.routers.context.get_summary_service")
    async def test_get_summary_chapter_not_found(self, mock_get_svc: MagicMock) -> None:
        """章节不存在返回 404."""
        mock_svc = MagicMock()
        mock_svc.ensure_summary = AsyncMock(side_effect=ValueError("章节不存在"))
        mock_get_svc.return_value = mock_svc

        response = client.get(f"/api/v1/context/chapters/{uuid.uuid4()}/summary")
        assert response.status_code == 404

    @patch("inkflow.api.routers.context.get_summary_service")
    async def test_refresh_summary_success(self, mock_get_svc: MagicMock) -> None:
        """强制刷新摘要返回 200."""
        mock_svc = MagicMock()
        mock_svc.ensure_summary = AsyncMock(return_value="新摘要")
        mock_get_svc.return_value = mock_svc

        chapter_id = str(uuid.uuid4())
        response = client.post(f"/api/v1/context/chapters/{chapter_id}/summary/refresh")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"] == "新摘要"


class TestContextCoverageGaps:
    """F6 覆盖率补齐：assemble ValueError 分支 / refresh 无效 UUID 与章节缺失."""

    @patch("inkflow.api.routers.context.get_context_service")
    async def test_assemble_value_error_400(self, mock_get_svc: MagicMock) -> None:
        """build_context 抛 ValueError（参数校验失败）→ 400（消息即 detail）."""
        mock_svc = MagicMock()
        mock_svc.build_context = AsyncMock(side_effect=ValueError("写作要求超过预算"))
        mock_get_svc.return_value = mock_svc

        response = client.post(
            "/api/v1/context/assemble",
            json={
                "project_id": str(uuid.uuid4()),
                "chapter_id": str(uuid.uuid4()),
                "model": "openai/gpt-4o",
                "writing_requirements": "X" * 5000,
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "写作要求超过预算"

    async def test_refresh_summary_invalid_uuid_404(self) -> None:
        """强制刷新摘要：无效 UUID → 404「章节不存在」."""
        response = client.post("/api/v1/context/chapters/not-a-uuid/summary/refresh")
        assert response.status_code == 404
        assert response.json()["detail"] == "章节不存在"

    @patch("inkflow.api.routers.context.get_summary_service")
    async def test_refresh_summary_chapter_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """强制刷新摘要：章节不存在（ensure_summary 抛 ValueError）→ 404."""
        mock_svc = MagicMock()
        mock_svc.ensure_summary = AsyncMock(side_effect=ValueError("章节不存在"))
        mock_get_svc.return_value = mock_svc

        response = client.post(f"/api/v1/context/chapters/{uuid.uuid4()}/summary/refresh")
        assert response.status_code == 404
        assert response.json()["detail"] == "章节不存在"
