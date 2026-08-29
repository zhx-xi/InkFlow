"""摘要服务 — 前文章节摘要生成与缓存管理.

SummaryService 负责:
1. 摘要缓存查询/更新（通过 SummaryRepositoryProtocol）
2. LLM 驱动的前文章节摘要生成
3. 缓存失效检测（章节更新后自动重新生成）

依据: specs/f6-context/spec.md §4.6.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Protocol

from inkflow.core.config import config
from inkflow.domain.models.chapter import Chapter as ChapterDomain
from inkflow.domain.models.context import ChapterSummary
from inkflow.domain.ports.context_errors import SummaryGenerationError
from inkflow.domain.ports.llm_client import ChatMessage, LLMClientProtocol
from inkflow.domain.ports.prompt_template import PromptTemplateProtocol
from inkflow.domain.ports.summary_repository import SummaryRepositoryProtocol

logger = logging.getLogger(__name__)


class ChapterReaderProtocol(Protocol):
    """读取章节内容的端口 — 由 F2 chapter_repo 提供.

    避免直接依赖 ChapterRepositoryProtocol，只暴露最小接口.
    """

    async def get_chapter(self, chapter_id: int) -> ChapterDomain | None: ...


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


class SummaryService:
    """前文摘要服务.

    依赖:
        - summary_repo: 摘要缓存仓储
        - llm_client: LLM 客户端（F5）
        - prompt_manager: Prompt 模板管理器（F5）
        - chapter_reader: 章节内容读取器
    """

    def __init__(
        self,
        summary_repo: SummaryRepositoryProtocol,
        llm_client: LLMClientProtocol,
        prompt_manager: PromptTemplateProtocol,
        chapter_reader: ChapterReaderProtocol,
    ) -> None:
        self._repo = summary_repo
        self._llm = llm_client
        self._prompts = prompt_manager
        self._chapters = chapter_reader

    async def ensure_summary(self, chapter_id: uuid.UUID, model: str, force: bool = False) -> str:
        """确保章节摘要存在且未过期.

        流程:
        1. 查缓存
        2. 未命中 → 生成
        3. 命中但章节已更新 → 重新生成
        4. 命中且未过期 → 返回缓存

        Args:
            chapter_id: 章节 ID（domain UUID）.
            model: 摘要模型.
            force: 强制重新生成.

        Returns:
            摘要文本（≤ 300 字）.
        """
        chapter_id_int = int(chapter_id) if isinstance(chapter_id, uuid.UUID) else chapter_id

        # 查找章节
        chapter = await self._chapters.get_chapter(chapter_id_int)
        if chapter is None:
            raise ValueError(f"章节不存在: {chapter_id}")

        # 查缓存
        cached = await self._repo.get(chapter_id_int)

        if force or cached is None:
            return await self._generate_and_cache(chapter, model)

        # 失效检测：章节 updated_at > 摘要 updated_at
        if chapter.updated_at.isoformat() > cached.updated_at:
            return await self._generate_and_cache(chapter, model)

        return cached.summary

    async def summarize_chapter(self, chapter: ChapterDomain, model: str) -> str:
        """调用 LLM 生成章节摘要.

        Args:
            chapter: 章节领域对象.
            model: 摘要模型.

        Returns:
            摘要文本（≤ 300 字）.

        Raises:
            SummaryGenerationError: LLM 调用失败.
        """
        try:
            template = self._prompts.load("context_summary")
            rendered = self._prompts.render(
                template,
                {
                    "chapter_title": chapter.title,
                    "chapter_content": chapter.content[:8000],  # 截断过长内容
                },
            )

            messages = [
                ChatMessage(role=m["role"], content=m["content"]) for m in rendered.messages
            ]

            # #470: 无 provider 前缀（如新项目默认 "gpt-4o"）→ 回退全局默认（有前缀）
            resolved_model = model
            if "/" not in model:
                resolved_model = config.llm_default_model

            response = await self._llm.chat(messages, model=resolved_model)
            summary = response.content.strip()

            # 简单截断保证 ≤ 300 字（LLM 可能不遵守）
            if len(summary) > 300:
                summary = summary[:297] + "..."
        except Exception as e:
            raise SummaryGenerationError(chapter_id=str(chapter.id), detail=str(e)) from e
        else:
            return summary

    async def list_recent(self, project_id: uuid.UUID, limit: int = 10) -> list[ChapterSummary]:
        """获取项目内按章节序号倒序的最新摘要列表.

        Args:
            project_id: 项目 ID（domain UUID）.
            limit: 最大返回数.

        Returns:
            摘要列表.
        """
        pid_int = int(project_id) if isinstance(project_id, uuid.UUID) else project_id
        return await self._repo.list_recent(pid_int, limit)

    async def _generate_and_cache(self, chapter: ChapterDomain, model: str) -> str:
        """生成摘要并写入缓存."""
        summary = await self.summarize_chapter(chapter, model)
        # 如果 chapter.id 是 UUID，需要转换为 int 传给 repo
        chapter_id_int = int(chapter.id) if isinstance(chapter.id, uuid.UUID) else chapter.id
        await self._repo.upsert(chapter_id_int, summary, model)
        return summary
