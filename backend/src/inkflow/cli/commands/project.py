"""Project CLI commands — `inkflow project <action>`."""

from __future__ import annotations

import asyncio
import json
import sys

import typer

from inkflow.core.database import async_session_factory, create_tables
from inkflow.domain.models.project import Genre
from inkflow.domain.services.project_service import ProjectService

app = typer.Typer(name="project", help="项目/书籍管理", no_args_is_help=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_async(coro):
    """Run a coroutine synchronously via asyncio.run()."""
    return asyncio.run(coro)


def _project_to_dict(project) -> dict:
    """Serialize a Project domain model to a JSON-safe dict."""
    return project.model_dump(mode="json")


def _print_json(data) -> None:
    """Print data as formatted JSON to stdout."""
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    print()


# ---------------------------------------------------------------------------
# create  —  inkflow project create --name "xxx" --genre 玄幻
# ---------------------------------------------------------------------------


@app.command()
def create(
    name: str = typer.Option(..., "--name", "-n", help="项目名称"),
    genre: str = typer.Option("其他", "--genre", "-g", help="小说分类"),
    language: str = typer.Option("zh-CN", "--language", "-l", help="写作语言"),
    target_words: int = typer.Option(0, "--target-words", "-w", help="目标字数"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """创建新项目"""
    # Convert genre string to Genre enum
    genre_enum = Genre(genre)

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = ProjectService(session)
            return await svc.create_project(
                name=name,
                genre=genre_enum,
                language=language,
                target_words=target_words,
            )

    project = _run_async(_impl())
    if json_output:
        _print_json(_project_to_dict(project))
    else:
        typer.echo(f"✅ 项目创建成功: [{project.name}] ({project.genre.value})")


# ---------------------------------------------------------------------------
# list  —  inkflow project list [--search xxx] [--sort name] [--json]
# ---------------------------------------------------------------------------


@app.command()
def list(
    search: str | None = typer.Option(None, "--search", "-s", help="按名称搜索"),
    sort: str = typer.Option(
        "updated_at", "--sort", help="排序字段 (name / updated_at / created_at)"
    ),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """列出项目"""

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = ProjectService(session)
            return await svc.list_projects(search=search, sort_by=sort)

    projects, total = _run_async(_impl())
    if json_output:
        _print_json([_project_to_dict(p) for p in projects])
    else:
        if not projects:
            typer.echo("📭 暂无项目")
            return
        typer.echo(f"共 {total} 个项目:\n")
        for p in projects:
            typer.echo(f"  [{p.id}] {p.name} ({p.genre.value}) — {p.target_words} 字")


# ---------------------------------------------------------------------------
# get  —  inkflow project get --id 1
# ---------------------------------------------------------------------------


@app.command()
def get(
    project_id: int = typer.Option(..., "--id", "-i", help="项目 ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """查看项目详情"""

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = ProjectService(session)
            return await svc.get(project_id)

    project = _run_async(_impl())
    if project is None:
        typer.echo("❌ 项目不存在", err=True)
        raise typer.Exit(code=1)
    if json_output:
        _print_json(_project_to_dict(project))
    else:
        typer.echo(f"ID:         {project.id}")
        typer.echo(f"名称:       {project.name}")
        typer.echo(f"分类:       {project.genre.value}")
        typer.echo(f"语言:       {project.language}")
        typer.echo(f"目标字数:   {project.target_words}")
        typer.echo(f"创建时间:   {project.created_at}")
        typer.echo(f"更新时间:   {project.updated_at}")


# ---------------------------------------------------------------------------
# delete  —  inkflow project delete --id 1 [--force] [--permanent]
# ---------------------------------------------------------------------------


@app.command()
def delete(
    project_id: int = typer.Option(..., "--id", "-i", help="项目 ID"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
    permanent: bool = typer.Option(False, "--permanent", "-p", help="硬删除（永久删除）"),
) -> None:
    """删除项目"""
    if not force:
        label = "永久删除" if permanent else "删除"
        if not typer.confirm(f"确定要{label}项目 #{project_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = ProjectService(session)
            if permanent:
                return await svc.hard_delete(project_id)
            else:
                return await svc.soft_delete(project_id)

    ok = _run_async(_impl())
    if ok:
        label = "永久删除" if permanent else "已删除"
        typer.echo(f"✅ 项目 #{project_id} {label}")
    else:
        typer.echo("❌ 项目不存在", err=True)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# restore  —  inkflow project restore --id 1
# ---------------------------------------------------------------------------


@app.command()
def restore(
    project_id: int = typer.Option(..., "--id", "-i", help="项目 ID"),
) -> None:
    """恢复已删除的项目"""

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = ProjectService(session)
            return await svc.restore(project_id)

    project = _run_async(_impl())
    if project is None:
        typer.echo("❌ 项目不存在", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"✅ 项目已恢复: [{project.name}] ({project.genre.value})")
