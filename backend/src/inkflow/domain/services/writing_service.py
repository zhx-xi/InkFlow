"""F3 写作管道服务 — generate_chapter / continue_writing / revise_content."""

from __future__ import annotations

import uuid

from inkflow.domain.models.writing import (
    ContinueWritingRequest,
    RevisionRequest,
    WritingMode,
    WritingRequest,
    WritingResult,
)
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.prompt_template import PromptTemplateProtocol
from inkflow.domain.services._format_validator import FormatValidator
from inkflow.domain.services._word_count import count_words

_MAX_RETRIES = 3


class _NotFoundError(Exception):
    """资源不存在异常。API 层映射为 404。"""


class NullContextProvider:
    """F6 未实现时的空上下文注入器。"""

    async def get_context(
        self,
        *,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None = None,
        mode: str,
    ) -> str:
        return ""


class WritingService:
    """AI 写作管道服务 — 生成/续写/修订章节内容。"""

    def __init__(
        self,
        *,
        llm_client: LLMClientProtocol,
        prompt_manager: PromptTemplateProtocol,
        project_repo,
        chapter_repo,
        context_provider=None,
    ) -> None:
        self._llm = llm_client
        self._prompts = prompt_manager
        self._project_repo = project_repo
        self._chapter_repo = chapter_repo
        self._context_provider = context_provider or NullContextProvider()

    # ── generate_chapter ──────────────────────────────────────────

    async def generate_chapter(self, request: WritingRequest) -> WritingResult:
        project = await self._project_repo.get(request.project_id)
        await self._validate_chapter(request.project_id, request.chapter_id)

        style = request.style_hint or project.config.writing_style or ""
        model = request.model or project.config.model
        temperature = (
            request.temperature if request.temperature is not None else project.config.temperature
        )

        ctx = await self._context_provider.get_context(
            project_id=request.project_id,
            chapter_id=request.chapter_id,
            mode="generate",
        )
        full_context = request.context or ctx or ""

        return await self._generate_with_retry(
            mode=WritingMode.GENERATE,
            style=style,
            outline=request.outline,
            context=full_context,
            min_words=request.min_words,
            model=model,
            temperature=temperature,
        )

    # ── continue_writing ──────────────────────────────────────────

    async def continue_writing(self, request: ContinueWritingRequest) -> WritingResult:
        project = await self._project_repo.get(request.project_id)
        await self._validate_chapter(request.project_id, request.chapter_id)

        style = request.style_hint or project.config.writing_style or ""
        model = request.model or project.config.model
        temperature = (
            request.temperature if request.temperature is not None else project.config.temperature
        )
        tail = request.existing_content[-800:]

        ctx = await self._context_provider.get_context(
            project_id=request.project_id,
            chapter_id=request.chapter_id,
            mode="continue",
        )
        full_context = request.context or ctx or ""

        return await self._generate_with_retry(
            mode=WritingMode.CONTINUE,
            style=style,
            outline=f"续写：{tail}",
            context=full_context,
            min_words=request.target_words,
            model=model,
            temperature=temperature,
        )

    # ── revise_content ────────────────────────────────────────────

    async def revise_content(self, request: RevisionRequest) -> WritingResult:
        await self._project_repo.get(request.project_id)
        await self._validate_chapter(request.project_id, request.chapter_id)

        model = request.model or "openai/gpt-4o"
        temperature = request.temperature if request.temperature is not None else 0.4

        warnings: list[str] = []
        if request.target_range and request.target_range not in request.content:
            warnings.append(f"未能定位目标范围 '{request.target_range}'，已对全文执行修订")

        system_msg = ChatMessage(
            role="system",
            content="你是专业小说修订助手。保留原文风格，仅修复指出的问题。",
        )
        user_msg = ChatMessage(
            role="user",
            content=(
                f"原文：\n{request.content}\n\n"
                f"修订意见：{request.feedback}\n"
                + (f"目标范围：{request.target_range}\n" if request.target_range else "")
                + "请输出修订后的完整内容，保持原有叙事风格与口吻。"
            ),
        )

        response = await self._llm.chat(
            messages=[system_msg, user_msg],
            model=model,
            temperature=temperature,
        )

        wc = count_words(response.content)
        return WritingResult(
            content=response.content,
            word_count=wc,
            mode=WritingMode.REVISE,
            format_valid=True,
            retry_count=0,
            model=response.model,
            token_usage=response.token_usage,
            warnings=warnings,
        )

    # ── internals ─────────────────────────────────────────────────

    async def _validate_chapter(self, project_id: uuid.UUID, chapter_id: uuid.UUID) -> None:
        """校验章节存在且属于该项目。失败抛出 _NotFoundError。"""
        chapter = await self._chapter_repo.get_chapter(chapter_id)
        if chapter is None or chapter.project_id != project_id:
            raise _NotFoundError("章节不存在")

    async def _generate_with_retry(
        self,
        *,
        mode: WritingMode,
        style: str,
        outline: str,
        context: str,
        min_words: int,
        model: str,
        temperature: float,
    ) -> WritingResult:
        """带格式修复重试的生成/续写管道."""
        system_msg = ChatMessage(
            role="system",
            content=f"你是专业小说作者。{style}" if style else "你是专业小说作者。",
        )
        user_msg = ChatMessage(
            role="user",
            content=(
                f"大纲：{outline}\n"
                + (f"上下文：{context}\n" if context else "")
                + f"最少字数：{min_words}\n"
                + "请直接输出正文内容（Markdown 格式，章节标题使用 # 标记），"
                "不要输出 JSON 或代码块标记。"
            ),
        )
        messages: list[ChatMessage] = [system_msg, user_msg]

        retry_count = 0
        last_response = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self._llm.chat(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                )
            except LLMRequestError:
                raise  # LLM 错误不消耗格式重试

            last_response = response
            validation = FormatValidator.validate(response.content, min_words)

            if validation.valid:
                return WritingResult(
                    content=response.content,
                    word_count=count_words(response.content),
                    mode=mode,
                    format_valid=True,
                    retry_count=retry_count,
                    model=response.model,
                    token_usage=response.token_usage,
                    warnings=[],
                )

            retry_count += 1
            if retry_count > _MAX_RETRIES:
                break

            # 构建修复 Prompt
            fix_prompt = (
                "上一版输出存在以下格式问题，请修正：\n"
                + "\n".join(f"  - {e}" for e in validation.errors)
                + "\n\n请重新输出完整正文。"
            )
            messages.append(ChatMessage(role="assistant", content=response.content))
            messages.append(ChatMessage(role="user", content=fix_prompt))

        # 重试耗尽
        wc = count_words(last_response.content) if last_response else 0
        return WritingResult(
            content=last_response.content if last_response else "",
            word_count=wc,
            mode=mode,
            format_valid=False,
            retry_count=_MAX_RETRIES,
            model=model,
            token_usage=last_response.token_usage if last_response else None,
            warnings=[
                f"格式校验未通过（{_MAX_RETRIES} 次重试后仍异常）",
                *([f"字数不足: {wc}/{min_words}"] if wc < min_words else []),
            ],
        )
