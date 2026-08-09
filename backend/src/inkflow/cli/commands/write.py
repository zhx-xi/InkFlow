"""F3 write 子命令 — next / continue / revise（F23 流式；Issue #169 CLI 恒经 HTTP）."""

from __future__ import annotations

import asyncio
import uuid

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.domain.models.writing import WritingMode, WritingRequest
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

app = typer.Typer(help="AI 写作命令", no_args_is_help=True)

_SHOW_CONTEXT_NOTE = "(--show-context 功能将在 F6 联调时启用)"


def _get_cli_ctx(ctx: typer.Context) -> CliContext:
    """从 typer.Context.obj 取 CliContext；根 app 尚未接线 --json 时回退人类模式."""
    return ctx.obj if isinstance(ctx.obj, CliContext) else CliContext()


def _run_async(coro):
    """同步运行协程（CLI 命令内 asyncio.run）."""
    return asyncio.run(coro)


def _run(cli_ctx: CliContext, coro_fn):
    """执行内核调用并统一映射 HTTP 异常为 F7 错误信封（退出码 1）."""
    try:
        return _run_async(coro_fn())
    except HttpApiError as exc:
        code, message = map_http_error(exc.status_code, exc.detail, exc.code)
        print_error(cli_ctx, code, message)
    except KernelStartupError as exc:
        print_error(cli_ctx, "KERNEL_ERROR", f"内核启动失败: {exc}")


async def _collect_stream(cli_ctx: CliContext, events, mode: str) -> dict:
    """消费内核 SSE 流式事件（dict 帧，F23 §6），流结束后返回 WritingResult dict.

    人类模式: 逐 delta 用 typer.echo(delta, nl=False) 连续打印（chunk 间无分隔，拼接 == 全文）
    --json:    静默收集 delta（不打印任何中间输出），仅由调用方输出信封
    流中 error 帧（done=True + error）→ {"error": ...} 标记，调用方映射 LLM_ERROR
    """
    parts: list[str] = []
    done_ev: dict | None = None
    async for ev in events:
        if ev.get("delta"):
            parts.append(ev["delta"])
            if not cli_ctx.json_output:
                typer.echo(ev["delta"], nl=False)
        elif ev.get("done"):
            done_ev = ev

    content = "".join(parts)
    if done_ev is not None and done_ev.get("error"):
        return {"error": done_ev["error"]}
    if done_ev is None:
        # 防御: 流异常终止（无 done 帧）——不崩溃，按空结果回退（真实内核恒发 done 帧）
        done_ev = {
            "format_valid": False,
            "warnings": ["生成内容为空"],
            "word_count": len(content),
            "model": "",
        }
    return {
        "content": content,
        "word_count": (
            done_ev["word_count"] if done_ev.get("word_count") is not None else len(content)
        ),
        "mode": mode,
        "format_valid": bool(done_ev.get("format_valid") or False),
        "retry_count": 0,
        "model": done_ev.get("model") or "",
        "token_usage": done_ev.get("token_usage"),
        "warnings": done_ev.get("warnings", []),
    }


def _echo_warnings(warnings: list[str]) -> None:
    """格式校验/修订警告逐条 echo（spec §4.1 / §7 E6/E7）."""
    for w in warnings:
        typer.echo(f"⚠ {w}")


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

    async def _impl() -> list[dict]:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            results: list[dict] = []
            for _ in range(count):
                request = WritingRequest(
                    project_id=uuid.UUID(project_id),
                    chapter_id=uuid.UUID(chapter_id),
                    outline=outline,
                    context=context,
                    min_words=min_words,
                    style_hint=style or None,
                )
                body = request.model_dump(mode="json", exclude_none=True)
                body["mode"] = WritingMode.GENERATE.value
                results.append(
                    await _collect_stream(
                        cli_ctx,
                        client.stream_sse("/writing/stream", json=body),
                        WritingMode.GENERATE.value,
                    )
                )
            return results

    results = _run(cli_ctx, _impl)
    if results is None:
        return
    for i, result in enumerate(results):
        if result.get("error"):
            print_error(cli_ctx, "LLM_ERROR", result["error"])
        if not cli_ctx.json_output:
            status = "✅" if result["format_valid"] else "⚠️"
            typer.echo(
                f"{status} 章节生成成功: {result['word_count']} 字 "
                f"(重试 {result['retry_count']} 次, {result['model']})"
            )
            _echo_warnings(result["warnings"])
            if i < len(results) - 1:
                typer.echo()  # 章间空行分隔（spec §4.1）
    if cli_ctx.json_output:
        data = results[0] if len(results) == 1 else results
        print_result(cli_ctx, data)
    if show_context and not cli_ctx.json_output:
        typer.echo(_SHOW_CONTEXT_NOTE)


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

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            # 章节原文经 HTTP 获取（Issue #169：CLI 不再直连仓储）
            chapter = await client.get(f"/chapters/{chapter_id}")
            body = {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "existing_content": chapter.get("content") or "",
                "target_words": target_words,
                "context": context,
                "mode": WritingMode.CONTINUE.value,
            }
            return await _collect_stream(
                cli_ctx,
                client.stream_sse("/writing/stream", json=body),
                WritingMode.CONTINUE.value,
            )

    result = _run(cli_ctx, _impl)
    if result is None:
        return
    if result.get("error"):
        print_error(cli_ctx, "LLM_ERROR", result["error"])
    if cli_ctx.json_output:
        print_result(cli_ctx, result)
    else:
        typer.echo(f"✅ 续写完成: {result['word_count']} 字 ({result['model']})")
        _echo_warnings(result["warnings"])


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

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            # 章节原文经 HTTP 获取（Issue #169：CLI 不再直连仓储）
            chapter = await client.get(f"/chapters/{chapter_id}")
            body = {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "content": chapter.get("content") or "",
                "feedback": instruction,
                "mode": WritingMode.REVISE.value,
            }
            if range_ is not None:
                body["target_range"] = range_
            return await _collect_stream(
                cli_ctx,
                client.stream_sse("/writing/stream", json=body),
                WritingMode.REVISE.value,
            )

    result = _run(cli_ctx, _impl)
    if result is None:
        return
    if result.get("error"):
        print_error(cli_ctx, "LLM_ERROR", result["error"])
    if cli_ctx.json_output:
        print_result(cli_ctx, result)
    else:
        typer.echo(f"✅ 修订完成: {result['word_count']} 字 ({result['model']})")
        _echo_warnings(result["warnings"])
