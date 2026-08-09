"""Chapter/Volume CLI — `inkflow chapter <action>` / `inkflow volume <action>`."""

from __future__ import annotations

import asyncio
import uuid

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.domain.models.chapter import ChapterStatus
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

chapter_app = typer.Typer(name="chapter", help="章节管理", no_args_is_help=True)
volume_app = typer.Typer(name="volume", help="卷管理", no_args_is_help=True)


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


# -- Volume --


@volume_app.command("create")
def create_vol(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", "-p"),
    title: str = typer.Option(..., "--title", "-t"),
    order: float = typer.Option(None, "--order", "-o"),
):
    """创建卷"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                f"/projects/{uuid.UUID(project_id)}/volumes",
                json={"title": title, "order_index": order},
            )

    vol = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, vol)
    else:
        typer.echo(f"✅ 卷创建成功: [{vol['title']}]")


@volume_app.command("list")
def list_vol(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", "-p"),
):
    """列出卷"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/projects/{uuid.UUID(project_id)}/volumes")

    data = _run(cli_ctx, _impl)
    print_result(cli_ctx, data.get("items", []))


@volume_app.command("delete")
def delete_vol(
    ctx: typer.Context,
    volume_id: str = typer.Option(..., "--id", "-i"),
    force: bool = typer.Option(False, "--force", "-f"),
):
    """删除卷"""
    cli_ctx: CliContext = ctx.obj
    if not force and not typer.confirm("确定删除此卷？其下章节将变为未分类"):
        raise typer.Exit()

    async def _impl() -> None:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            await client.delete(f"/volumes/{uuid.UUID(volume_id)}")

    _run(cli_ctx, _impl)
    print_result(cli_ctx, {"deleted": True})


# -- Chapter --


@chapter_app.command("create")
def create_ch(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", "-p"),
    title: str = typer.Option(..., "--title", "-t"),
    volume_id: str | None = typer.Option(None, "--volume-id", "-v"),
    content: str = typer.Option("", "--content", "-c"),
):
    """创建章节"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                f"/projects/{uuid.UUID(project_id)}/chapters",
                json={
                    "title": title,
                    "volume_id": str(uuid.UUID(volume_id)) if volume_id else None,
                    "content": content,
                },
            )

    ch = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, ch)
    else:
        typer.echo(f"✅ 章节创建: [{ch['title']}] ({ch['word_count']}字)")


@chapter_app.command("list")
def list_ch(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", "-p"),
    volume_id: str | None = typer.Option(None, "--volume-id", "-v"),
    status: str | None = typer.Option(None, "--status", "-s"),
):
    """列出章节"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(
                f"/projects/{uuid.UUID(project_id)}/chapters",
                params={
                    "volume_id": str(uuid.UUID(volume_id)) if volume_id else None,
                    "status": ChapterStatus(status).value if status else None,
                },
            )

    data = _run(cli_ctx, _impl)
    total = data.get("total", 0)
    chapters = data.get("items", [])
    print_result(cli_ctx, {"total": total, "chapters": chapters})


@chapter_app.command()
def get(
    ctx: typer.Context,
    chapter_id: str = typer.Option(..., "--id", "-i"),
):
    """查看章节详情"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/chapters/{uuid.UUID(chapter_id)}")

    ch = _run(cli_ctx, _impl)
    print_result(cli_ctx, ch)


@chapter_app.command()
def update(
    ctx: typer.Context,
    chapter_id: str = typer.Option(..., "--id", "-i"),
    title: str | None = typer.Option(None, "--title", "-t"),
    content: str | None = typer.Option(None, "--content", "-c"),
    status: str | None = typer.Option(None, "--status", "-s"),
):
    """更新章节"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        update_fields: dict[str, object] = {}
        if title is not None:
            update_fields["title"] = title
        if content is not None:
            update_fields["content"] = content
        if status is not None:
            update_fields["status"] = ChapterStatus(status).value
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch(f"/chapters/{uuid.UUID(chapter_id)}", json=update_fields)

    ch = _run(cli_ctx, _impl)
    print_result(cli_ctx, ch)


@chapter_app.command()
def move(
    ctx: typer.Context,
    chapter_id: str = typer.Option(..., "--id", "-i"),
    to_volume: str | None = typer.Option(None, "--to-volume", "-v"),
):
    """移动章节"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                f"/chapters/{uuid.UUID(chapter_id)}/move",
                params={"target_volume_id": (str(uuid.UUID(to_volume)) if to_volume else None)},
            )

    ch = _run(cli_ctx, _impl)
    print_result(cli_ctx, ch)


@chapter_app.command("delete")
def delete_ch(
    ctx: typer.Context,
    chapter_id: str = typer.Option(..., "--id", "-i"),
    force: bool = typer.Option(False, "--force", "-f"),
):
    """删除章节"""
    cli_ctx: CliContext = ctx.obj
    if not force and not typer.confirm("确定删除此章节？"):
        raise typer.Exit()

    async def _impl() -> None:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            await client.delete(f"/chapters/{uuid.UUID(chapter_id)}")

    _run(cli_ctx, _impl)
    print_result(cli_ctx, {"deleted": True})
