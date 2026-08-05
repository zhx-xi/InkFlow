"""T2 (ADR-026)：writing_service 真实生成 — prompt 模板 + 输出链路兼容。

验证：项目/章节落库 → WritingService.generate_chapter 真实调用 LLM →
prompt 模板渲染无错、输出可落回 WritingResult。断言宽松（非空）。
"""

import pytest

from inkflow.domain.models.project import Genre
from inkflow.domain.models.writing import WritingRequest
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.domain.services.project_service import ProjectService
from inkflow.domain.services.writing_service import WritingService
from inkflow.infrastructure.database.repositories.chapter_repo import (
    SQLiteChapterRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_writing_generate_real(db_session, llm_env):
    """真实生成一小段：项目 + 章节 + WritingService 全链路。"""
    # 建项目（用 ProjectService，取持久化后由 int PK 转换而来的真实 UUID id
    # —— 勿自行构造 uuid4()：128 位 int 超出 SQLite INTEGER 范围）
    project_svc = ProjectService(db_session)
    project = await project_svc.create_project(
        name="e2e-ai-测试", genre=Genre.KEHUAN, language="zh-CN", target_words=50000
    )
    project_id = project.id

    # 建章节
    chapter_svc = ChapterService(db_session)
    chapter = await chapter_svc.create_chapter(
        project_id=project_id, title="e2e 测试章节"
    )
    chapter_id = chapter.id

    # WritingService 真实装配（照抄 deps.py get_writing_service，api_key 注入）
    service = WritingService(
        llm_client=LangChainLLMClient(
            api_key=llm_env["api_key"], default_model=llm_env["model"]
        ),
        prompt_manager=LangChainPromptManager(),
        project_repo=SQLiteProjectRepository(db_session),
        chapter_repo=SQLiteChapterRepository(db_session),
    )

    # model 显式传入 llm_env["model"]：ProjectConfig.model 默认 "gpt-4o"（无 provider
    # 前缀），不传会触发 parse_model_string 校验失败而非真实调用
    result = await service.generate_chapter(
        WritingRequest(
            project_id=project_id,
            chapter_id=chapter_id,
            outline="主角进入试炼场，第一次面对魔兽。",
            model=llm_env["model"],
        )
    )

    assert result.content.strip()  # 非空（宽松断言，不断言质量/字数）
    assert result.word_count > 0
