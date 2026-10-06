"""Context CLI — `inkflow context <action>`."""

from __future__ import annotations

import asyncio
import uuid

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel
from inkflow.logging import instrument

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
@instrument(caller_type="cli")
def assemble(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", "-p"),
    chapter_id: str = typer.Option(..., "--chapter-id", "-c"),
    model: str = typer.Option(..., "--model", "-m"),
    writing_requirements: str = typer.Option(..., "--writing-requirements", "-w"),
    max_tokens: int | None = typer.Option(None, "--max-tokens"),
    show_system_prompt: bool = typer.Option(
        False, "--show-system-prompt", help="打印写手轨 system prompt（默认关闭）"
    ),
    show_skills: bool = typer.Option(False, "--show-skills", help="打印有效技能集清单（默认关闭）"),
    show_tools: bool = typer.Option(
        False, "--show-tools", help="打印装配层 tool id 清单（默认关闭）"
    ),
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
        # 观测开关默认关闭：不开启时**不进请求体**（守住「缺省响应不变」）
        if show_system_prompt:
            body["show_system_prompt"] = True
        if show_skills:
            body["show_skills"] = True
        if show_tools:
            body["show_tools"] = True
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
        _print_observability(
            data,
            show_system_prompt=show_system_prompt,
            show_skills=show_skills,
            show_tools=show_tools,
        )


def _print_observability(
    data: dict,
    *,
    show_system_prompt: bool,
    show_skills: bool,
    show_tools: bool,
) -> None:
    """打印装配观测段（#1480 目标装配预览）——按**显式开启的 flag** 逐段输出.

    只依据本地 flag 而非响应键：缺省响应本就不含三键，但显式传 false 与第三方响应
    夹带时都不应误导用户（观测面永远由本地开关驱动）。
    """
    if not (show_system_prompt or show_skills or show_tools):
        return
    typer.echo("🔍 装配可观测（目标装配预览，#1480）")
    if show_system_prompt:
        prompt = data.get("system_prompt") or ""
        typer.echo(f"  system_prompt（{len(prompt)} 字符）：")
        typer.echo(prompt)
    if show_skills:
        skills = data.get("skills") or []
        typer.echo(f"  技能（{len(skills)}）：")
        for item in skills:
            typer.echo(f"    - {item['name']}  source={item['source']}  bytes={item['bytes']}")
    if show_tools:
        tools = data.get("tools") or []
        typer.echo(f"  工具（{len(tools)}）：{', '.join(tools)}")
