"""Project CLI commands — `inkflow project <action>`."""

from __future__ import annotations

import asyncio

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.domain.models.project import Genre
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

app = typer.Typer(name="project", help="项目/书籍管理", no_args_is_help=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_async(coro):
    """Run a coroutine synchronously via asyncio.run()."""
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


# ---------------------------------------------------------------------------
# create  —  inkflow project create --name "xxx" --genre 玄幻
# ---------------------------------------------------------------------------


@app.command()
def create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", "-n", help="项目名称"),
    genre: str = typer.Option("其他", "--genre", "-g", help="小说分类"),
    language: str = typer.Option("zh-CN", "--language", "-l", help="写作语言"),
    target_words: int = typer.Option(0, "--target-words", "-w", help="目标字数"),
) -> None:
    """创建新项目"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                "/projects",
                json={
                    "name": name,
                    "genre": Genre(genre).value,
                    "language": language,
                    "target_words": target_words,
                },
            )

    project = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, project)
    else:
        typer.echo(f"✅ 项目创建成功: [{project['name']}] ({project['genre']})")


# ---------------------------------------------------------------------------
# list  —  inkflow project list [--search xxx] [--sort name]
# ---------------------------------------------------------------------------


@app.command()
def list(
    ctx: typer.Context,
    search: str | None = typer.Option(None, "--search", "-s", help="按名称搜索"),
    sort: str = typer.Option(
        "updated_at", "--sort", help="排序字段 (name / updated_at / created_at)"
    ),
) -> None:
    """列出项目"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(
                "/projects",
                params={
                    "search": search,
                    "sort_by": sort,
                    "sort_desc": True,
                    "offset": 0,
                    "limit": 50,
                },
            )

    data = _run(cli_ctx, _impl)
    projects = data.get("items", [])
    total = data.get("total", 0)
    if not projects and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无项目")
        return
    if not cli_ctx.json_output and total:
        print_result(cli_ctx, f"共 {total} 个项目")
    print_result(cli_ctx, projects)


# ---------------------------------------------------------------------------
# get  —  inkflow project get --id 1
# ---------------------------------------------------------------------------


@app.command()
def get(
    ctx: typer.Context,
    project_id: int = typer.Option(..., "--id", "-i", help="项目 ID"),
) -> None:
    """查看项目详情"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/projects/{project_id}")

    project = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, project)
    else:
        typer.echo(f"ID:         {project['id']}")
        typer.echo(f"名称:       {project['name']}")
        typer.echo(f"分类:       {project['genre']}")
        typer.echo(f"语言:       {project['language']}")
        typer.echo(f"目标字数:   {project['target_words']}")
        typer.echo(f"创建时间:   {project['created_at']}")
        typer.echo(f"更新时间:   {project['updated_at']}")


# ---------------------------------------------------------------------------
# delete  —  inkflow project delete --id 1 [--force] [--permanent]
# ---------------------------------------------------------------------------


@app.command()
def delete(
    ctx: typer.Context,
    project_id: int = typer.Option(..., "--id", "-i", help="项目 ID"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
    permanent: bool = typer.Option(False, "--permanent", "-p", help="硬删除（永久删除）"),
) -> None:
    """删除项目"""
    cli_ctx: CliContext = ctx.obj
    if not force:
        label = "永久删除" if permanent else "删除"
        if not typer.confirm(f"确定要{label}项目 #{project_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl() -> None:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            await client.delete(
                f"/projects/{project_id}",
                params={"force": "true" if permanent else "false"},
            )

    _run(cli_ctx, _impl)
    label = "永久删除" if permanent else "已删除"
    print_result(cli_ctx, f"✅ 项目 #{project_id} {label}")


# ---------------------------------------------------------------------------
# restore  —  inkflow project restore --id 1
# ---------------------------------------------------------------------------


@app.command()
def restore(
    ctx: typer.Context,
    project_id: int = typer.Option(..., "--id", "-i", help="项目 ID"),
) -> None:
    """恢复已删除的项目"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(f"/projects/{project_id}/restore")

    project = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, project)
    else:
        typer.echo(f"✅ 项目已恢复: [{project['name']}] ({project['genre']})")
