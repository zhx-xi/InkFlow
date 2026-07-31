"""F3 write 子命令 — generate / continue / revise."""

from __future__ import annotations

import json as _json
import uuid

import typer

from inkflow.core.database import async_session_factory
from inkflow.domain.models.writing import (
    ContinueWritingRequest,
    RevisionRequest,
    WritingRequest,
)
from inkflow.domain.services.writing_service import NullContextProvider, WritingService
from inkflow.infrastructure.database.repositories.chapter_repo import SQLiteChapterRepository
from inkflow.infrastructure.database.repositories.project_repo import SQLiteProjectRepository
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager

app = typer.Typer(help="AI 写作命令", no_args_is_help=True)


def _build_service(db_session):
    llm = LangChainLLMClient()
    prompts = LangChainPromptManager()
    project_repo = SQLiteProjectRepository(db_session)
    chapter_repo = SQLiteChapterRepository(db_session)
    return WritingService(
        llm_client=llm,
        prompt_manager=prompts,
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        context_provider=NullContextProvider(),
    )


@app.command()
def generate(
    project_id: str = typer.Option(..., "--project-id", help="项目 ID"),
    chapter_id: str = typer.Option(..., "--chapter-id", help="章节 ID"),
    outline: str = typer.Option(..., "--outline", help="章节大纲"),
    context: str = typer.Option("", "--context", help="额外上下文"),
    min_words: int = typer.Option(2000, "--min-words", help="最少字数"),
    style: str = typer.Option("", "--style", help="写作风格"),
    json: bool = typer.Option(False, "--json", help="JSON 输出"),
) -> None:
    """从大纲生成完整章节."""

    async def _run():
        async with async_session_factory() as db:
            service = _build_service(db)
            request = WritingRequest(
                project_id=uuid.UUID(project_id),
                chapter_id=uuid.UUID(chapter_id),
                outline=outline,
                context=context,
                min_words=min_words,
                style_hint=style or None,
            )
            result = await service.generate_chapter(request)
            if json:
                typer.echo(
                    _json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
                )
            else:
                status = "✅" if result.format_valid else "⚠️"
                typer.echo(
                    f"{status} 章节生成成功: {result.word_count} 字 "
                    f"(重试 {result.retry_count} 次, {result.model})"
                )

    import asyncio

    asyncio.run(_run())


@app.command()
def continue_(
    project_id: str = typer.Option(..., "--project-id", help="项目 ID"),
    chapter_id: str = typer.Option(..., "--chapter-id", help="章节 ID"),
    target_words: int = typer.Option(2000, "--target-words", help="目标字数"),
    context: str = typer.Option("", "--context", help="额外上下文"),
    json: bool = typer.Option(False, "--json", help="JSON 输出"),
) -> None:
    """接续已有内容继续写作."""

    # existing_content is read from the chapter via the service
    async def _run():
        async with async_session_factory() as db:
            service = _build_service(db)
            chapter_repo = SQLiteChapterRepository(db)
            chapter = await chapter_repo.get_chapter(uuid.UUID(chapter_id))
            if not chapter:
                typer.echo("错误: 章节不存在", err=True)
                raise typer.Exit(1)

            request = ContinueWritingRequest(
                project_id=uuid.UUID(project_id),
                chapter_id=uuid.UUID(chapter_id),
                existing_content=chapter.content or "",
                target_words=target_words,
                context=context,
            )
            result = await service.continue_writing(request)
            if json:
                typer.echo(
                    _json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
                )
            else:
                typer.echo(f"✅ 续写完成: {result.word_count} 字 ({result.model})")

    import asyncio

    asyncio.run(_run())


@app.command()
def revise(
    project_id: str = typer.Option(..., "--project-id", help="项目 ID"),
    chapter_id: str = typer.Option(..., "--chapter-id", help="章节 ID"),
    feedback: str = typer.Option(..., "--feedback", help="修订意见"),
    range_: str = typer.Option(None, "--range", help="目标范围（如 '第3段'）"),
    json: bool = typer.Option(False, "--json", help="JSON 输出"),
) -> None:
    """基于修订意见修改内容."""

    async def _run():
        async with async_session_factory() as db:
            service = _build_service(db)
            chapter_repo = SQLiteChapterRepository(db)
            chapter = await chapter_repo.get_chapter(uuid.UUID(chapter_id))
            if not chapter:
                typer.echo("错误: 章节不存在", err=True)
                raise typer.Exit(1)

            request = RevisionRequest(
                project_id=uuid.UUID(project_id),
                chapter_id=uuid.UUID(chapter_id),
                content=chapter.content or "",
                feedback=feedback,
                target_range=range_,
            )
            result = await service.revise_content(request)
            if json:
                typer.echo(
                    _json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
                )
            else:
                typer.echo(f"✅ 修订完成: {result.word_count} 字 ({result.model})")

    import asyncio

    asyncio.run(_run())
