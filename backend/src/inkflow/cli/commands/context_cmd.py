"""Context CLI — `inkflow context <action>`."""

from __future__ import annotations

import asyncio
import uuid

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

app = typer.Typer(name="context", help="上下文管理", no_args_is_help=True)


@app.callback()
def _context_callback() -> None:
    """context 组回调——保持命令组形态（Typer 单命令提升规避，镜像 audit/export）."""


def _run_async(coro):
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
    except Exception as e:
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


@app.command("assemble")
def assemble(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", "-p"),
    chapter_id: str = typer.Option(..., "--chapter-id", "-c"),
    model: str = typer.Option(..., "--model", "-m"),
    writing_requirements: str = typer.Option(..., "--writing-requirements", "-w"),
    max_tokens: int | None = typer.Option(None, "--max-tokens"),
):
    """组装上下文（调试验证端点）"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        body: dict = {
            "project_id": str(uuid.UUID(project_id)),
            "chapter_id": str(uuid.UUID(chapter_id)),
            "model": model,
            "writing_requirements": writing_requirements,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post("/context/assemble", json=body)

    data = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
    else:
        typer.echo(
            f"✅ 上下文组装完成: {data['model']} | "
            f"{data['total_tokens']}/{data['budget_tokens']} tokens | "
            f"blocks={len(data['blocks'])} | dropped={len(data['dropped'])}"
        )
