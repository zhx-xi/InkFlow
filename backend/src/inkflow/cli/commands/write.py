"""F3 write 子命令 — next / continue / revise（F23: 默认流式输出，spec §4）."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.core.database import async_session_factory
from inkflow.domain.models.writing import (
    ContinueWritingRequest,
    RevisionRequest,
    WritingMode,
    WritingRequest,
    WritingResult,
    WritingStreamEvent,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.services.writing_service import NullContextProvider, WritingService
from inkflow.infrastructure.database.repositories.chapter_repo import SQLiteChapterRepository
from inkflow.infrastructure.database.repositories.project_repo import SQLiteProjectRepository
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager

app = typer.Typer(help="AI 写作命令", no_args_is_help=True)

_SHOW_CONTEXT_NOTE = "(--show-context 功能将在 F6 联调时启用)"

# F23 流式（spec §7 E1）: service 前置校验失败消息 → NOT_FOUND 语义
_NOT_FOUND_MESSAGES = ("项目不存在", "章节不存在")


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


async def _collect_stream(
    cli_ctx: CliContext,
    events: AsyncGenerator[WritingStreamEvent, None],
    mode: WritingMode,
) -> WritingResult:
    """消费 service 流式事件，流结束后返回 WritingResult（spec §4.1/§4.2）.

    人类模式: 逐 delta 用 typer.echo(ev.delta, nl=False) 连续打印（chunk 间无分隔，拼接 == 全文）
    --json:    静默收集 delta（不打印任何中间输出），仅由调用方输出信封
    """
    parts: list[str] = []
    done_ev: WritingStreamEvent | None = None
    async for ev in events:
        if ev.delta:
            parts.append(ev.delta)
            if not cli_ctx.json_output:
                typer.echo(ev.delta, nl=False)
        elif ev.done:
            done_ev = ev

    content = "".join(parts)
    if done_ev is None:
        # 防御: 流异常终止（无 done 帧）——不崩溃，按空结果回退（真实 service 恒发 done 帧）
        done_ev = WritingStreamEvent(
            done=True,
            format_valid=False,
            warnings=["生成内容为空"],
            word_count=len(content),
            model="",
        )
    return WritingResult(
        content=content,
        word_count=done_ev.word_count if done_ev.word_count is not None else len(content),
        mode=mode,
        format_valid=bool(done_ev.format_valid or False),
        retry_count=0,
        model=done_ev.model or "",
        token_usage=done_ev.token_usage,
        warnings=done_ev.warnings,
    )


def _echo_warnings(warnings: list[str]) -> None:
    """格式校验/修订警告逐条 echo（spec §4.1 / §7 E6/E7）."""
    for w in warnings:
        typer.echo(w)


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
    """从大纲生成完整章节（F23: 默认流式输出，spec §4.1）."""

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
                results: list[WritingResult] = []
                for i in range(count):
                    result = await _collect_stream(
                        cli_ctx,
                        service.stream_generate(request),
                        WritingMode.GENERATE,
                    )
                    results.append(result)
                    if not cli_ctx.json_output:
                        status = "✅" if result.format_valid else "⚠️"
                        typer.echo(
                            f"{status} 章节生成成功: {result.word_count} 字 "
                            f"(重试 {result.retry_count} 次, {result.model})"
                        )
                        _echo_warnings(result.warnings)
                        if i < count - 1:
                            typer.echo()  # 章间空行分隔（spec §4.1）
                if cli_ctx.json_output:
                    data = (
                        results[0].model_dump(mode="json")
                        if count == 1
                        else [r.model_dump(mode="json") for r in results]
                    )
                    print_result(cli_ctx, data)
                if show_context and not cli_ctx.json_output:
                    typer.echo(_SHOW_CONTEXT_NOTE)
        except LLMRequestError as exc:
            message = str(exc)
            if message in _NOT_FOUND_MESSAGES:
                print_error(cli_ctx, "NOT_FOUND", message)
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
    """接续已有内容继续写作（F23: 默认流式输出，spec §4.1）."""

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
                result = await _collect_stream(
                    cli_ctx,
                    service.stream_continue(request),
                    WritingMode.CONTINUE,
                )
                if cli_ctx.json_output:
                    print_result(cli_ctx, result.model_dump(mode="json"))
                else:
                    typer.echo(f"✅ 续写完成: {result.word_count} 字 ({result.model})")
                    _echo_warnings(result.warnings)
        except LLMRequestError as exc:
            message = str(exc)
            if message in _NOT_FOUND_MESSAGES:
                print_error(cli_ctx, "NOT_FOUND", message)
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
    """基于修订指令修改内容（F23: 默认流式输出，spec §4.1）."""

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
                result = await _collect_stream(
                    cli_ctx,
                    service.stream_revise(request),
                    WritingMode.REVISE,
                )
                if cli_ctx.json_output:
                    print_result(cli_ctx, result.model_dump(mode="json"))
                else:
                    typer.echo(f"✅ 修订完成: {result.word_count} 字 ({result.model})")
                    _echo_warnings(result.warnings)
        except LLMRequestError as exc:
            message = str(exc)
            if message in _NOT_FOUND_MESSAGES:
                print_error(cli_ctx, "NOT_FOUND", message)
            print_error(cli_ctx, "LLM_ERROR", f"LLM 调用失败: {exc}")

    asyncio.run(_run())
