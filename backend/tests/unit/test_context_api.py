"""上下文 API 集成测试 — Mock Service 层.

测试范围 (spec §9):
    - POST /api/v1/context/assemble → 200
    - assemble protected 超预算 → 400
    - assemble 无效 UUID → 422
    - GET /summary → 200
    - GET /summary 无效章节 → 404
    - POST /summary/refresh → 200

#329 RED（0.8.0-rc2）：summary 端点不得硬编码 model="openai/gpt-4o"——
走项目 config.model（写作链路一致）→ 回退 config.llm_default_model。
新增 TestSummaryModelResolution 断言 ensure_summary 收到项目配置模型
（当前实现传 "openai/gpt-4o" → FAIL）；既有 summary 用例补
get_chapter_service/get_project_service mock（router 修复后需要反查章节所属项目）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.core.config import config as app_config
from inkflow.domain.models.chapter import Chapter
from inkflow.domain.models.context import (
    ContextAssemblyResult,
    ContextBlock,
    ContextItem,
    ContextLayer,
    ContextSourceType,
)
from inkflow.domain.models.project import Project, ProjectConfig
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


def _chapter_with_project(project_id: uuid.UUID) -> Chapter:
    """构造带 project_id 的章节领域对象（#329 model 反查用）."""
    return Chapter(id=uuid.uuid4(), project_id=project_id, title="第一章")


def _project_with_model(model: str) -> Project:
    """构造配置了指定默认模型的项目（#329 契约：model = 项目配置模型）."""
    now = datetime.now(UTC)
    return Project(
        id=uuid.uuid4(),
        name="模型项目",
        config=ProjectConfig(model=model),
        created_at=now,
        updated_at=now,
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
    @patch("inkflow.api.routers.context.get_project_service", create=True)
    @patch("inkflow.api.routers.context.get_chapter_service", create=True)
    async def test_get_summary_success(
        self,
        mock_get_chapter_svc: MagicMock,
        mock_get_project_svc: MagicMock,
        mock_get_svc: MagicMock,
    ) -> None:
        """查看摘要返回 200."""
        mock_svc = MagicMock()
        mock_svc.ensure_summary = AsyncMock(return_value="本章摘要：冒险开始")
        mock_get_svc.return_value = mock_svc
        # #329：router 修复后反查章节所属项目拿 config.model
        pid = uuid.uuid4()
        mock_get_chapter_svc.return_value.get_chapter = AsyncMock(
            return_value=_chapter_with_project(pid)
        )
        mock_get_project_svc.return_value.get = AsyncMock(
            return_value=_project_with_model("gpt-4o")
        )

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
    @patch("inkflow.api.routers.context.get_project_service", create=True)
    @patch("inkflow.api.routers.context.get_chapter_service", create=True)
    async def test_get_summary_chapter_not_found(
        self,
        mock_get_chapter_svc: MagicMock,
        mock_get_project_svc: MagicMock,
        mock_get_svc: MagicMock,
    ) -> None:
        """章节不存在返回 404."""
        mock_svc = MagicMock()
        mock_svc.ensure_summary = AsyncMock(side_effect=ValueError("章节不存在"))
        mock_get_svc.return_value = mock_svc
        # #329：章节不存在 → get_chapter 返回 None（router 直接 404，不调 ensure_summary）
        mock_get_chapter_svc.return_value.get_chapter = AsyncMock(return_value=None)
        mock_get_project_svc.return_value.get = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/context/chapters/{uuid.uuid4()}/summary")
        assert response.status_code == 404

    @patch("inkflow.api.routers.context.get_summary_service")
    @patch("inkflow.api.routers.context.get_project_service", create=True)
    @patch("inkflow.api.routers.context.get_chapter_service", create=True)
    async def test_refresh_summary_success(
        self,
        mock_get_chapter_svc: MagicMock,
        mock_get_project_svc: MagicMock,
        mock_get_svc: MagicMock,
    ) -> None:
        """强制刷新摘要返回 200."""
        mock_svc = MagicMock()
        mock_svc.ensure_summary = AsyncMock(return_value="新摘要")
        mock_get_svc.return_value = mock_svc
        # #329：router 修复后反查章节所属项目拿 config.model
        pid = uuid.uuid4()
        mock_get_chapter_svc.return_value.get_chapter = AsyncMock(
            return_value=_chapter_with_project(pid)
        )
        mock_get_project_svc.return_value.get = AsyncMock(
            return_value=_project_with_model("gpt-4o")
        )

        chapter_id = str(uuid.uuid4())
        response = client.post(f"/api/v1/context/chapters/{chapter_id}/summary/refresh")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"] == "新摘要"


class TestSummaryModelResolution:
    """#329 RED：summary 端点 model 解析契约（0.8.0-rc2）.

    旧实现硬编码 model="openai/gpt-4o"；新契约 = 章节所属项目的
    config.model（写作链路一致）→ 回退 config.llm_default_model。
    RED 形态：断言 ensure_summary 收到项目配置模型 → 旧实现传
    "openai/gpt-4o" → FAIL。
    """

    @patch("inkflow.api.routers.context.get_summary_service")
    @patch("inkflow.api.routers.context.get_project_service", create=True)
    @patch("inkflow.api.routers.context.get_chapter_service", create=True)
    async def test_get_summary_uses_project_model(
        self,
        mock_get_chapter_svc: MagicMock,
        mock_get_project_svc: MagicMock,
        mock_get_svc: MagicMock,
    ) -> None:
        """GET summary：ensure_summary 收到项目 config.model（非硬编码）."""
        mock_svc = MagicMock()
        mock_svc.ensure_summary = AsyncMock(return_value="摘要")
        mock_get_svc.return_value = mock_svc

        pid = uuid.uuid4()
        cid = uuid.uuid4()
        mock_get_chapter_svc.return_value.get_chapter = AsyncMock(
            return_value=_chapter_with_project(pid)
        )
        mock_get_project_svc.return_value.get = AsyncMock(
            return_value=_project_with_model("deepseek-v3")
        )

        response = client.get(f"/api/v1/context/chapters/{cid}/summary")

        assert response.status_code == 200
        mock_svc.ensure_summary.assert_awaited_once_with(cid, model="deepseek-v3")

    @patch("inkflow.api.routers.context.get_summary_service")
    @patch("inkflow.api.routers.context.get_project_service", create=True)
    @patch("inkflow.api.routers.context.get_chapter_service", create=True)
    async def test_refresh_summary_uses_project_model(
        self,
        mock_get_chapter_svc: MagicMock,
        mock_get_project_svc: MagicMock,
        mock_get_svc: MagicMock,
    ) -> None:
        """POST refresh：ensure_summary 收到项目 config.model（force=True 保留）."""
        mock_svc = MagicMock()
        mock_svc.ensure_summary = AsyncMock(return_value="新摘要")
        mock_get_svc.return_value = mock_svc

        pid = uuid.uuid4()
        cid = uuid.uuid4()
        mock_get_chapter_svc.return_value.get_chapter = AsyncMock(
            return_value=_chapter_with_project(pid)
        )
        mock_get_project_svc.return_value.get = AsyncMock(
            return_value=_project_with_model("zhipu/glm-4.5")
        )

        response = client.post(f"/api/v1/context/chapters/{cid}/summary/refresh")

        assert response.status_code == 200
        mock_svc.ensure_summary.assert_awaited_once_with(cid, model="zhipu/glm-4.5", force=True)

    @patch("inkflow.api.routers.context.get_summary_service")
    @patch("inkflow.api.routers.context.get_project_service", create=True)
    @patch("inkflow.api.routers.context.get_chapter_service", create=True)
    async def test_get_summary_falls_back_to_llm_default_model(
        self,
        mock_get_chapter_svc: MagicMock,
        mock_get_project_svc: MagicMock,
        mock_get_svc: MagicMock,
        monkeypatch,
    ) -> None:
        """项目无 config.model（project 缺失）→ 回退 config.llm_default_model.

        ⚠️ monkeypatch llm_default_model 为非默认值，防止与旧硬编码值
        恰好相等造成假绿（默认 "openai/gpt-4o" == 旧硬编码）。
        """
        monkeypatch.setattr(app_config, "llm_default_model", "deepseek/deepseek-chat")
        mock_svc = MagicMock()
        mock_svc.ensure_summary = AsyncMock(return_value="摘要")
        mock_get_svc.return_value = mock_svc

        pid = uuid.uuid4()
        cid = uuid.uuid4()
        mock_get_chapter_svc.return_value.get_chapter = AsyncMock(
            return_value=_chapter_with_project(pid)
        )
        mock_get_project_svc.return_value.get = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/context/chapters/{cid}/summary")

        assert response.status_code == 200
        mock_svc.ensure_summary.assert_awaited_once_with(cid, model="deepseek/deepseek-chat")


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
    @patch("inkflow.api.routers.context.get_project_service", create=True)
    @patch("inkflow.api.routers.context.get_chapter_service", create=True)
    async def test_refresh_summary_chapter_not_found_404(
        self,
        mock_get_chapter_svc: MagicMock,
        mock_get_project_svc: MagicMock,
        mock_get_svc: MagicMock,
    ) -> None:
        """强制刷新摘要：章节不存在（ensure_summary 抛 ValueError）→ 404."""
        mock_svc = MagicMock()
        mock_svc.ensure_summary = AsyncMock(side_effect=ValueError("章节不存在"))
        mock_get_svc.return_value = mock_svc
        # #329：router 修复后先反查章节（真实 DB 路径须 mock，否则 128 位 UUID int
        # 绑定 64 位 SQLITE INTEGER 抛 OverflowError → 500 非 404）
        mock_get_chapter_svc.return_value.get_chapter = AsyncMock(
            return_value=_chapter_with_project(uuid.uuid4())
        )
        mock_get_project_svc.return_value.get = AsyncMock(
            return_value=_project_with_model("gpt-4o")
        )

        response = client.post(f"/api/v1/context/chapters/{uuid.uuid4()}/summary/refresh")
        assert response.status_code == 404
        assert response.json()["detail"] == "章节不存在"
