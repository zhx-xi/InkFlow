"""Project CLI commands — `inkflow project <action>`."""

from __future__ import annotations

import asyncio
import json

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.domain.models.project import Genre
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

app = typer.Typer(name="project", help="项目/书籍管理", no_args_is_help=True)

# 模块级已有命令函数 `list`，会在字符串注解求值时遮蔽内置 list（Typer eval_str=True），
# 故此处用别名承载 list[str] 泛型供 update 命令注解使用
ConfigList = list[str]


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
    project_id: str = typer.Option(..., "--id", "-i", help="项目 ID（int 或 UUID）"),
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
    project_id: str = typer.Option(..., "--id", "-i", help="项目 ID（int 或 UUID）"),
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
    project_id: str = typer.Option(..., "--id", "-i", help="项目 ID（int 或 UUID）"),
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


# ---------------------------------------------------------------------------
# update  —  inkflow project update --id 1 [--name xxx] [--config k=v ...]
# ---------------------------------------------------------------------------


def _parse_config_value(raw: str):
    """--config 值解析：#225 三态 + 数字 + JSON（null→None；__default__→sentinel；
    数字→int/float；[ / { 开头→json.loads；其余→字符串）."""
    if raw == "null":
        return None
    try:
        if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
            return int(raw)
        f = float(raw)
        if raw.lower() not in ("nan", "inf", "-inf"):
            return f
    except ValueError:
        pass
    if raw.startswith("[") or raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return raw


@app.command("update")
def update(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--id", "-i", help="项目 ID（int 或 UUID）"),
    name: str | None = typer.Option(None, "--name", "-n", help="项目名称"),
    genre: str | None = typer.Option(None, "--genre", "-g", help="小说分类"),
    language: str | None = typer.Option(None, "--language", "-l", help="写作语言"),
    target_words: int | None = typer.Option(None, "--target-words", "-w", help="目标字数"),
    config: ConfigList = typer.Option(
        [], "--config", help="config 字段级更新 KEY=VALUE（可重复；null/__default__/JSON 值）"
    ),
    config_json: str | None = typer.Option(
        None, "--config-json", help="config 整体 JSON（与 --config 合并，--config 覆盖）"
    ),
) -> None:
    """更新项目（config 字段级，#225 三态语义）"""
    cli_ctx: CliContext = ctx.obj
    body: dict = {}
    if name is not None:
        body["name"] = name
    if genre is not None:
        body["genre"] = genre
    if language is not None:
        body["language"] = language
    if target_words is not None:
        body["target_words"] = target_words
    cfg: dict = {}
    if config_json is not None:
        try:
            parsed = json.loads(config_json)
        except json.JSONDecodeError:
            print_error(cli_ctx, "VALIDATION_ERROR", f"--config-json 不是合法 JSON: {config_json}")
            return
        if not isinstance(parsed, dict):
            print_error(cli_ctx, "VALIDATION_ERROR", "--config-json 必须是 JSON 对象")
            return
        cfg.update(parsed)
    for kv in config:
        if "=" not in kv:
            print_error(cli_ctx, "VALIDATION_ERROR", f"--config 格式应为 KEY=VALUE: {kv}")
            return
        key, _, raw = kv.partition("=")
        cfg[key] = _parse_config_value(raw)
    if cfg:
        body["config"] = cfg

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch(f"/projects/{project_id}", json=body)

    project = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, project)
    else:
        typer.echo(f"✅ 项目 #{project_id} 已更新: [{project['name']}]")
