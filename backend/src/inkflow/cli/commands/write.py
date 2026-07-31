"""F3 write 子命令 — next / continue / revise."""

from __future__ import annotations

import asyncio
import uuid

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.core.database import async_session_factory
from inkflow.domain.models.writing import (
    ContinueWritingRequest,
    RevisionRequest,
    WritingRequest,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.services.writing_service import NullContextProvider, WritingService
from inkflow.infrastructure.database.repositories.chapter_repo import SQLiteChapterRepository
from inkflow.infrastructure.database.repositories.project_repo import SQLiteProjectRepository
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager

app = typer.Typer(help="AI 写作命令", no_args_is_help=True)

_SHOW_CONTEXT_NOTE = "(--show-context 功能将在 F6 联调时启用)"


def _get_cli_ctx(ctx: typer.Context) -> CliContext:
    """从 typer.Context.obj 取 CliContext；根 app 尚未接线 --json 时回退人类模式."""
    return ctx.obj if isinstance(ctx.obj, CliContext) else CliContext()


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


@app.command("next")
def next(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID"),
    chapter_id: str = typer.Option(..., "--chapter-id", help="章节 ID"),
    outline: str = typer.Option(..., "--outline", help="章节大纲"),
    context: str = typer.Option("", "--context", help="额外上下文"),
    min_words: int = typer.Option(2000, "--min-words", help="最少字数"),
    style: str = typer.Option("", "--style", help="写作风格"),
    count: int = typer.Option(1, "--count", help="生成章节数"),
    show_context: bool = typer.Option(False, "--show-context", help="显示注入的上下文"),
) -> None:
    """从大纲生成完整章节."""

    cli_ctx = _get_cli_ctx(ctx)

    async def _run() -> None:
        try:
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
                results = [await service.generate_chapter(request) for _ in range(count)]
                data = (
                    results[0].model_dump(mode="json")
                    if count == 1
                    else [r.model_dump(mode="json") for r in results]
                )
                print_result(cli_ctx, data)
                if show_context and not cli_ctx.json_output:
                    typer.echo(_SHOW_CONTEXT_NOTE)
        except LLMRequestError as exc:
            print_error(cli_ctx, "LLM_ERROR", f"LLM 调用失败: {exc}")

    asyncio.run(_run())


@app.command("continue")
def continue_(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID"),
    chapter_id: str = typer.Option(..., "--chapter-id", help="章节 ID"),
    target_words: int = typer.Option(2000, "--target-words", help="目标字数"),
    context: str = typer.Option("", "--context", help="额外上下文"),
) -> None:
    """接续已有内容继续写作."""

    cli_ctx = _get_cli_ctx(ctx)

    # existing_content is read from the chapter via the service
    async def _run() -> None:
        try:
            async with async_session_factory() as db:
                service = _build_service(db)
                chapter_repo = SQLiteChapterRepository(db)
                chapter = await chapter_repo.get_chapter(uuid.UUID(chapter_id).int)
                if not chapter:
                    print_error(cli_ctx, "NOT_FOUND", "章节不存在")
                assert chapter is not None  # print_error 已退出；仅用于类型收窄

                request = ContinueWritingRequest(
                    project_id=uuid.UUID(project_id),
                    chapter_id=uuid.UUID(chapter_id),
                    existing_content=chapter.content or "",
                    target_words=target_words,
                    context=context,
                )
                result = await service.continue_writing(request)
                print_result(cli_ctx, result.model_dump(mode="json"))
        except LLMRequestError as exc:
            print_error(cli_ctx, "LLM_ERROR", f"LLM 调用失败: {exc}")

    asyncio.run(_run())


@app.command("revise")
def revise(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID"),
    chapter_id: str = typer.Option(..., "--chapter-id", help="章节 ID"),
    instruction: str = typer.Option(..., "--instruction", help="修订指令"),
    range_: str = typer.Option(None, "--range", help="目标范围（如 '第3段'）"),
) -> None:
    """基于修订指令修改内容."""

    cli_ctx = _get_cli_ctx(ctx)

    async def _run() -> None:
        try:
            async with async_session_factory() as db:
                service = _build_service(db)
                chapter_repo = SQLiteChapterRepository(db)
                chapter = await chapter_repo.get_chapter(uuid.UUID(chapter_id).int)
                if not chapter:
                    print_error(cli_ctx, "NOT_FOUND", "章节不存在")
                assert chapter is not None  # print_error 已退出；仅用于类型收窄

                request = RevisionRequest(
                    project_id=uuid.UUID(project_id),
                    chapter_id=uuid.UUID(chapter_id),
                    content=chapter.content or "",
                    feedback=instruction,
                    target_range=range_,
                )
                result = await service.revise_content(request)
                print_result(cli_ctx, result.model_dump(mode="json"))
        except LLMRequestError as exc:
            print_error(cli_ctx, "LLM_ERROR", f"LLM 调用失败: {exc}")

    asyncio.run(_run())
