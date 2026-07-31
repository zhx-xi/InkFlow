"""F3 WritingService 测试 — Mock LLM + Mock PromptManager + Mock Repos."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.project import ProjectConfig
from inkflow.domain.models.writing import (
    ContinueWritingRequest,
    RevisionRequest,
    WritingMode,
    WritingRequest,
    WritingResult,
)
from inkflow.domain.ports.llm_client import ChatResponse, LLMClientProtocol, TokenUsage
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.services.writing_service import NullContextProvider, WritingService


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock(spec=LLMClientProtocol)
    llm.chat = AsyncMock()
    return llm


@pytest.fixture
def mock_prompt_manager() -> MagicMock:
    pm = MagicMock(spec=PromptTemplateProtocol)
    pm.load = MagicMock(
        return_value=PromptTemplate(
            name="writer",
            description="Writer template",
            system_prompt="You are a writer. Style: {style}",
            human_prompt="Outline: {outline}\nContext: {context}\nMin words: {min_words}",
            variables=["style", "outline", "context", "min_words"],
        )
    )
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[
                {"role": "system", "content": "You are a writer. Style: 热血少年"},
                {
                    "role": "user",
                    "content": "Outline: test outline\nContext: test context\nMin words: 2000",
                },
            ],
            token_estimate=100,
        )
    )
    return pm


@pytest.fixture
def mock_project_repo() -> MagicMock:
    from inkflow.domain.models.project import Project

    repo = MagicMock()
    project = Project(
        id=uuid.uuid4(),
        name="测试小说",
        genre="玄幻",
        language="zh-CN",
        target_words=100000,
        config=ProjectConfig(model="openai/gpt-4o", temperature=0.7, writing_style="热血少年"),
        is_deleted=False,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    repo.get = AsyncMock(return_value=project)
    return repo


@pytest.fixture
def mock_chapter_repo(mock_project_repo) -> MagicMock:
    from inkflow.domain.models.chapter import Chapter, ChapterStatus

    project = mock_project_repo.get.return_value  # noqa: F841 — used for project_id

    async def _get_chapter(chapter_id):
        return Chapter(
            id=chapter_id,
            project_id=project.id,  # type: ignore[union-attr]
            volume_id=None,
            title="第一章",
            content="",
            status=ChapterStatus.DRAFT,
            word_count=0,
            order_index=1.0,
            status_history=[],
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )

    repo = MagicMock()
    repo.get_chapter = AsyncMock(side_effect=_get_chapter)
    return repo


@pytest.fixture
def proj_id(mock_project_repo) -> uuid.UUID:
    return mock_project_repo.get.return_value.id  # type: ignore[union-attr]


@pytest.fixture
def service(mock_llm, mock_prompt_manager, mock_project_repo, mock_chapter_repo) -> WritingService:
    return WritingService(
        llm_client=mock_llm,
        prompt_manager=mock_prompt_manager,
        project_repo=mock_project_repo,
        chapter_repo=mock_chapter_repo,
        context_provider=NullContextProvider(),
    )


def _good_content() -> str:
    return "# 第一章 试炼\n\n" + "正文内容。" * 500


class TestWritingService:
    async def test_generate_chapter_success(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=2000, total_tokens=2100),
        )
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="主角首次踏入宗门试炼",
            context="",
        )
        result = await service.generate_chapter(request)
        assert isinstance(result, WritingResult)
        assert result.mode == WritingMode.GENERATE
        assert result.word_count >= 2000
        assert result.format_valid is True
        assert result.retry_count == 0
        assert result.model == "openai/gpt-4o"

    async def test_generate_retries_on_bad_format(self, service, mock_llm, proj_id) -> None:
        bad_content = "```\n# 标题\n正文\n```"
        good_content = _good_content()
        mock_llm.chat.side_effect = [
            ChatResponse(content=bad_content, model="openai/gpt-4o"),
            ChatResponse(
                content=good_content,
                model="openai/gpt-4o",
                token_usage=TokenUsage(
                    prompt_tokens=100, completion_tokens=2000, total_tokens=2100
                ),
            ),
        ]
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="test outline",
        )
        result = await service.generate_chapter(request)
        assert result.retry_count == 1
        assert result.format_valid is True

    async def test_generate_retries_exhausted(self, service, mock_llm, proj_id) -> None:
        bad = "```json\n{}\n```"
        mock_llm.chat.return_value = ChatResponse(content=bad, model="openai/gpt-4o")
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="test",
        )
        result = await service.generate_chapter(request)
        assert result.format_valid is False
        assert result.retry_count == 3
        assert len(result.warnings) > 0

    async def test_generate_llm_error_propagates(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.side_effect = LLMRequestError("API key invalid")
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="test",
        )
        with pytest.raises(LLMRequestError):
            await service.generate_chapter(request)

    async def test_generate_injects_style(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=2000, total_tokens=2100),
        )
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="test outline",
            style_hint="暗黑风格",
        )
        result = await service.generate_chapter(request)
        assert result.format_valid is True

    async def test_generate_uses_project_config(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=2000, total_tokens=2100),
        )
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="test",
        )
        result = await service.generate_chapter(request)
        assert result.model == "openai/gpt-4o"

    async def test_continue_injects_tail_anchor(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=1000, total_tokens=1100),
        )
        existing = "这是已有内容" * 20
        request = ContinueWritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            existing_content=existing,
        )
        result = await service.continue_writing(request)
        assert result.format_valid is True

    async def test_revise_default_low_temperature(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=500, total_tokens=600),
        )
        request = RevisionRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            content="待修订原文内容。" * 10,
            feedback="节奏太慢，删减环境描写",
        )
        result = await service.revise_content(request)
        assert result.mode == WritingMode.REVISE

    async def test_revise_unlocatable_range_warns(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=500, total_tokens=600),
        )
        request = RevisionRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            content="待修订原文内容。" * 10,
            feedback="修改意见",
            target_range="第99段",
        )
        result = await service.revise_content(request)
        assert any("未定位" in w or "定位" in w for w in result.warnings)

    async def test_null_context_provider(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=2000, total_tokens=2100),
        )
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="test",
            context="caller-provided context",
        )
        result = await service.generate_chapter(request)
        assert result.format_valid is True


class TestNullContextProvider:
    async def test_returns_empty(self) -> None:
        provider = NullContextProvider()
        result = await provider.get_context(
            project_id=uuid.uuid4(),
            chapter_id=uuid.uuid4(),
            mode=WritingMode.GENERATE,
        )
        assert result == ""
