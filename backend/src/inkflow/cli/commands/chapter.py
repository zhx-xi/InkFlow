"""Chapter/Volume CLI — `inkflow chapter <action>` / `inkflow volume <action>`."""

from __future__ import annotations

import asyncio
import uuid

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.core.database import async_session_factory, create_tables
from inkflow.domain.models.chapter import ChapterStatus
from inkflow.domain.services.chapter_service import ChapterService

chapter_app = typer.Typer(name="chapter", help="章节管理", no_args_is_help=True)
volume_app = typer.Typer(name="volume", help="卷管理", no_args_is_help=True)


def _run(coro):
    return asyncio.run(coro)


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

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            return await ChapterService(s).create_volume(uuid.UUID(project_id), title, order)

    vol = _run(_impl())
    if cli_ctx.json_output:
        print_result(cli_ctx, vol.model_dump(mode="json"))
    else:
        typer.echo(f"✅ 卷创建成功: [{vol.title}]")


@volume_app.command("list")
def list_vol(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", "-p"),
):
    """列出卷"""
    cli_ctx: CliContext = ctx.obj

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            return await ChapterService(s).list_volumes(uuid.UUID(project_id))

    volumes = _run(_impl())
    print_result(cli_ctx, [v.model_dump(mode="json") for v in volumes])


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

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            return await ChapterService(s).delete_volume(uuid.UUID(volume_id))

    ok = _run(_impl())
    if not ok:
        print_error(cli_ctx, "NOT_FOUND", "卷不存在")
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

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            return await ChapterService(s).create_chapter(
                uuid.UUID(project_id),
                title,
                uuid.UUID(volume_id) if volume_id else None,
                content,
            )

    ch = _run(_impl())
    if cli_ctx.json_output:
        print_result(cli_ctx, ch.model_dump(mode="json"))
    else:
        typer.echo(f"✅ 章节创建: [{ch.title}] ({ch.word_count}字)")


@chapter_app.command("list")
def list_ch(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", "-p"),
    volume_id: str | None = typer.Option(None, "--volume-id", "-v"),
    status: str | None = typer.Option(None, "--status", "-s"),
):
    """列出章节"""
    cli_ctx: CliContext = ctx.obj

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            se = ChapterStatus(status) if status else None
            vid = uuid.UUID(volume_id) if volume_id else None
            return await ChapterService(s).list_chapters(uuid.UUID(project_id), vid, se)

    chapters, total = _run(_impl())
    print_result(
        cli_ctx,
        {"total": total, "chapters": [c.model_dump(mode="json") for c in chapters]},
    )


@chapter_app.command()
def get(
    ctx: typer.Context,
    chapter_id: str = typer.Option(..., "--id", "-i"),
):
    """查看章节详情"""
    cli_ctx: CliContext = ctx.obj

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            return await ChapterService(s).get_chapter(uuid.UUID(chapter_id))

    ch = _run(_impl())
    if ch is None:
        print_error(cli_ctx, "NOT_FOUND", "章节不存在")
    print_result(cli_ctx, ch.model_dump(mode="json"))


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

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            from inkflow.domain.models.chapter import ChapterUpdate

            dto = ChapterUpdate(
                title=title,
                content=content,
                status=ChapterStatus(status) if status else None,
            )
            return await ChapterService(s).update_chapter(uuid.UUID(chapter_id), dto)

    ch = _run(_impl())
    if ch is None:
        print_error(cli_ctx, "NOT_FOUND", "章节不存在")
    print_result(cli_ctx, ch.model_dump(mode="json"))


@chapter_app.command()
def move(
    ctx: typer.Context,
    chapter_id: str = typer.Option(..., "--id", "-i"),
    to_volume: str | None = typer.Option(None, "--to-volume", "-v"),
):
    """移动章节"""
    cli_ctx: CliContext = ctx.obj

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            tv = uuid.UUID(to_volume) if to_volume else None
            return await ChapterService(s).move_chapter(uuid.UUID(chapter_id), tv)

    ch = _run(_impl())
    if ch is None:
        print_error(cli_ctx, "NOT_FOUND", "章节不存在")
    print_result(cli_ctx, ch.model_dump(mode="json"))


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

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            return await ChapterService(s).delete_chapter(uuid.UUID(chapter_id))

    ok = _run(_impl())
    if not ok:
        print_error(cli_ctx, "NOT_FOUND", "章节不存在")
    print_result(cli_ctx, {"deleted": True})
