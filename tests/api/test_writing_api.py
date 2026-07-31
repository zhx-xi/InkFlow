"""F3 写作 API 集成测试 — Mock WritingService（不触发真实 LLM 调用）。

TDD RED 阶段：路由尚未注册，预期全部失败。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from inkflow.domain.models.writing import WritingMode, WritingResult
from inkflow.domain.ports.llm_client import TokenUsage
from inkflow.domain.ports.llm_errors import LLMRequestError


def _preset_result(mode: str) -> WritingResult:
    """预设 WritingResult — 模拟 WritingService 的返回。"""
    return WritingResult(
        content="# 试炼场风波\n\n清晨的薄雾尚未散尽，青云宗的试炼场已经人声鼎沸……",
        word_count=2347,
        mode=WritingMode(mode),
        format_valid=True,
        retry_count=1,
        model="deepseek/deepseek-chat",
        token_usage=TokenUsage(
            prompt_tokens=1820, completion_tokens=2600, total_tokens=4420
        ),
        warnings=[],
    )


@pytest.fixture
def mock_writing_service() -> MagicMock:
    """Mock WritingService — 三个方法均返回预设 WritingResult。"""
    svc = MagicMock()
    svc.generate_chapter = AsyncMock(return_value=_preset_result("generate"))
    svc.continue_writing = AsyncMock(return_value=_preset_result("continue"))
    svc.revise_content = AsyncMock(return_value=_preset_result("revise"))
    return svc


@pytest.fixture
def override_writing_service(mock_writing_service):
    """将 FastAPI 的 get_writing_service 替换为 Mock，避免真实 LLM/DB 调用。"""

    from inkflow.api.app import app
    from inkflow.api.deps import get_writing_service

    app.dependency_overrides[get_writing_service] = lambda: mock_writing_service
    yield mock_writing_service
    app.dependency_overrides.clear()


def _client():
    """构造 ASGI 测试客户端。"""
    from inkflow.api.app import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _payload() -> dict:
    return {
        "project_id": str(uuid.uuid4()),
        "chapter_id": str(uuid.uuid4()),
    }


# ── 成功路径 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_endpoint(override_writing_service):
    """POST /api/v1/writing/generate → 200 + WritingResult。"""
    body = {**_payload(), "outline": "主角首次踏入宗门试炼场，遭遇同门挑衅"}
    async with _client() as client:
        resp = await client.post("/api/v1/writing/generate", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "generate"
    assert data["word_count"] == 2347
    assert data["format_valid"] is True
    assert data["retry_count"] == 1
    assert data["model"] == "deepseek/deepseek-chat"
    assert data["token_usage"]["total_tokens"] == 4420
    assert data["warnings"] == []


@pytest.mark.asyncio
async def test_continue_endpoint(override_writing_service):
    """POST /api/v1/writing/continue → 200 + WritingResult。"""
    body = {**_payload(), "existing_content": "林尘深吸一口气，缓缓走向试炼台……" * 3}
    async with _client() as client:
        resp = await client.post("/api/v1/writing/continue", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "continue"
    assert data["word_count"] == 2347


@pytest.mark.asyncio
async def test_revise_endpoint(override_writing_service):
    """POST /api/v1/writing/revise → 200 + WritingResult。"""
    body = {
        **_payload(),
        "content": "……（原文段落内容，此处为待修订的完整段落文本，超过十个字符）",
        "feedback": "对话节奏太拖沓，删减无关寒暄",
        "target_range": "第 3 段",
    }
    async with _client() as client:
        resp = await client.post("/api/v1/writing/revise", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "revise"
    assert data["word_count"] == 2347


# ── 错误路径 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_project_not_found(
    override_writing_service, mock_writing_service
):
    """项目不存在 → 404 \"项目不存在\"。"""
    mock_writing_service.generate_chapter.side_effect = LLMRequestError("项目不存在")
    body = {**_payload(), "outline": "测试大纲"}
    async with _client() as client:
        resp = await client.post("/api/v1/writing/generate", json=body)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "项目不存在"


@pytest.mark.asyncio
async def test_generate_chapter_not_found(
    override_writing_service, mock_writing_service
):
    """章节不存在/不属于项目 → 404 \"章节不存在\"。"""
    mock_writing_service.generate_chapter.side_effect = LLMRequestError("章节不存在")
    body = {**_payload(), "outline": "测试大纲"}
    async with _client() as client:
        resp = await client.post("/api/v1/writing/generate", json=body)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "章节不存在"


@pytest.mark.asyncio
async def test_generate_validation_error(override_writing_service):
    """outline 缺失 → 422（Pydantic 验证，未到达服务层）。"""
    body = _payload()
    async with _client() as client:
        resp = await client.post("/api/v1/writing/generate", json=body)
    assert resp.status_code == 422
    errors = resp.json()["detail"]
    assert any("outline" in str(e.get("loc")) for e in errors)


@pytest.mark.asyncio
async def test_generate_llm_error_500(override_writing_service, mock_writing_service):
    """LLM 调用失败 → 500 + 通用消息（不泄漏内部细节，ADR-012）。"""
    mock_writing_service.generate_chapter.side_effect = LLMRequestError(
        "API key invalid"
    )
    body = {**_payload(), "outline": "测试大纲"}
    async with _client() as client:
        resp = await client.post("/api/v1/writing/generate", json=body)
    assert resp.status_code == 500
    assert resp.json()["detail"] == "LLM 调用失败，请稍后重试"
    assert "API key invalid" not in resp.text
