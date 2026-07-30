"""Chapter/Volume CLI — `inkflow chapter <action>` / `inkflow volume <action>`."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid

import typer

from inkflow.core.database import async_session_factory, create_tables
from inkflow.domain.models.chapter import ChapterStatus
from inkflow.domain.services.chapter_service import ChapterService

chapter_app = typer.Typer(name="chapter", help="章节管理", no_args_is_help=True)
volume_app = typer.Typer(name="volume", help="卷管理", no_args_is_help=True)


def _run(coro):
    return asyncio.run(coro)


def _json(data):
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2, default=str)
    print()


# -- Volume --


@volume_app.command("create")
def create_vol(
    project_id: str = typer.Option(..., "--project-id", "-p"),
    title: str = typer.Option(..., "--title", "-t"),
    order: float = typer.Option(None, "--order", "-o"),
    json_output: bool = typer.Option(False, "--json"),
):
    """创建卷"""

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            return await ChapterService(s).create_volume(uuid.UUID(project_id), title, order)

    vol = _run(_impl())
    if json_output:
        _json(vol.model_dump(mode="json"))
    else:
        typer.echo(f"✅ 卷创建成功: [{vol.title}]")


@volume_app.command("list")
def list_vol(
    project_id: str = typer.Option(..., "--project-id", "-p"),
    json_output: bool = typer.Option(False, "--json"),
):
    """列出卷"""

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            return await ChapterService(s).list_volumes(uuid.UUID(project_id))

    volumes = _run(_impl())
    if json_output:
        _json([v.model_dump(mode="json") for v in volumes])
    elif not volumes:
        typer.echo("📭 暂无卷")
    else:
        for v in volumes:
            typer.echo(f"  [{v.id}] {v.title}")


@volume_app.command("delete")
def delete_vol(
    volume_id: str = typer.Option(..., "--id", "-i"),
    force: bool = typer.Option(False, "--force", "-f"),
):
    """删除卷"""
    if not force and not typer.confirm("确定删除此卷？其下章节将变为未分类"):
        raise typer.Exit()

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            return await ChapterService(s).delete_volume(uuid.UUID(volume_id))

    ok = _run(_impl())
    typer.echo(f"{'✅ 已删除' if ok else '❌ 不存在'}")


# -- Chapter --


@chapter_app.command("create")
def create_ch(
    project_id: str = typer.Option(..., "--project-id", "-p"),
    title: str = typer.Option(..., "--title", "-t"),
    volume_id: str | None = typer.Option(None, "--volume-id", "-v"),
    content: str = typer.Option("", "--content", "-c"),
    json_output: bool = typer.Option(False, "--json"),
):
    """创建章节"""

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
    if json_output:
        _json(ch.model_dump(mode="json"))
    else:
        typer.echo(f"✅ 章节创建: [{ch.title}] ({ch.word_count}字)")


@chapter_app.command("list")
def list_ch(
    project_id: str = typer.Option(..., "--project-id", "-p"),
    volume_id: str | None = typer.Option(None, "--volume-id", "-v"),
    status: str | None = typer.Option(None, "--status", "-s"),
    json_output: bool = typer.Option(False, "--json"),
):
    """列出章节"""

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            se = ChapterStatus(status) if status else None
            vid = uuid.UUID(volume_id) if volume_id else None
            return await ChapterService(s).list_chapters(uuid.UUID(project_id), vid, se)

    chapters, total = _run(_impl())
    if json_output:
        _json([c.model_dump(mode="json") for c in chapters])
    elif not chapters:
        typer.echo("📭 暂无章节")
    else:
        typer.echo(f"共 {total} 章:")
        for c in chapters:
            typer.echo(f"  [{c.id}] {c.title} ({c.status.value}) — {c.word_count}字")


@chapter_app.command()
def get(
    chapter_id: str = typer.Option(..., "--id", "-i"),
    json_output: bool = typer.Option(False, "--json"),
):
    """查看章节详情"""

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            return await ChapterService(s).get_chapter(uuid.UUID(chapter_id))

    ch = _run(_impl())
    if ch is None:
        typer.echo("❌ 章节不存在", err=True)
        raise typer.Exit(1)
    if json_output:
        _json(ch.model_dump(mode="json"))
    else:
        typer.echo(f"标题: {ch.title}\n状态: {ch.status.value}\n字数: {ch.word_count}")


@chapter_app.command()
def update(
    chapter_id: str = typer.Option(..., "--id", "-i"),
    title: str | None = typer.Option(None, "--title", "-t"),
    content: str | None = typer.Option(None, "--content", "-c"),
    status: str | None = typer.Option(None, "--status", "-s"),
    json_output: bool = typer.Option(False, "--json"),
):
    """更新章节"""

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
        typer.echo("❌ 章节不存在", err=True)
        raise typer.Exit(1)
    if json_output:
        _json(ch.model_dump(mode="json"))
    else:
        typer.echo(f"✅ 已更新: [{ch.title}]")


@chapter_app.command()
def move(
    chapter_id: str = typer.Option(..., "--id", "-i"),
    to_volume: str | None = typer.Option(None, "--to-volume", "-v"),
    json_output: bool = typer.Option(False, "--json"),
):
    """移动章节"""

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            tv = uuid.UUID(to_volume) if to_volume else None
            return await ChapterService(s).move_chapter(uuid.UUID(chapter_id), tv)

    ch = _run(_impl())
    if ch is None:
        typer.echo("❌ 章节不存在", err=True)
        raise typer.Exit(1)
    if json_output:
        _json(ch.model_dump(mode="json"))
    else:
        typer.echo(f"✅ 已移动至卷 {ch.volume_id or '未分类'}")


@chapter_app.command("delete")
def delete_ch(
    chapter_id: str = typer.Option(..., "--id", "-i"),
    force: bool = typer.Option(False, "--force", "-f"),
):
    """删除章节"""
    if not force and not typer.confirm("确定删除此章节？"):
        raise typer.Exit()

    async def _impl():
        await create_tables()
        async with async_session_factory() as s:
            return await ChapterService(s).delete_chapter(uuid.UUID(chapter_id))

    ok = _run(_impl())
    typer.echo(f"{'✅ 已删除' if ok else '❌ 不存在'}")
