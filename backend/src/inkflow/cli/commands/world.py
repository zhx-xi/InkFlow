"""F10 世界观管理 CLI 命令 — `inkflow world <action>`.

薄层设计：仅做参数解析/校验与结果格式化，全部业务委托 WorldService
（spec §4）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130；删除类命令二次确认 + --force；
--json + 无 --force 的删除 → VALIDATION_ERROR。

错误码映射（spec §4/§7）:
- WorldServiceError 子类（同名条目等）→ VALIDATION_ERROR
- WorldNotFoundError / ProjectNotFoundError / 无效 UUID → NOT_FOUND
- WorldExtractionError / LLMRequestError → LLM_ERROR
- 其余异常 → DB_ERROR

依据: specs/f10-world-service/spec.md §4/§4.2。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import typer
from pydantic import ValidationError

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.core.database import async_session_factory, create_tables
from inkflow.domain.models.world import (
    WorldExtractionResult,
    WorldExtractRequest,
    WorldSetting,
    WorldUpdate,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.world_errors import (
    ProjectNotFoundError,
    WorldExtractionError,
    WorldNotFoundError,
    WorldServiceError,
)
from inkflow.domain.services._world_extractor import WorldExtractor
from inkflow.domain.services.world_service import WorldService
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.database.repositories.world_repo import (
    SQLiteWorldRepository,
)
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager

app = typer.Typer(name="world", help="世界观管理", no_args_is_help=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_async(coro):
    """同步运行协程（CLI 命令内 asyncio.run）."""
    return asyncio.run(coro)


def _parse_uuid(cli_ctx: CliContext, value: str, message: str) -> uuid.UUID:
    """解析 UUID 字符串；非法输入按资源不存在处理（spec §7 无效 UUID → 404 语义）."""
    try:
        return uuid.UUID(value)
    except ValueError:
        print_error(cli_ctx, "NOT_FOUND", message)
        raise typer.Exit(1) from None  # print_error 已退出，此行不可达（静态分析用）


def _run(cli_ctx: CliContext, coro_fn):
    """执行服务调用并统一映射领域异常为 F7 错误信封（退出码 1）."""
    try:
        return _run_async(coro_fn())
    except typer.Exit:
        raise
    except (WorldNotFoundError, ProjectNotFoundError) as e:
        print_error(cli_ctx, "NOT_FOUND", str(e))
    except WorldExtractionError as e:
        print_error(cli_ctx, "LLM_ERROR", str(e))
    except LLMRequestError:
        print_error(cli_ctx, "LLM_ERROR", "LLM 调用失败，请稍后重试")
    except WorldServiceError as e:
        print_error(cli_ctx, "VALIDATION_ERROR", str(e))
    except ValidationError as e:
        messages = "; ".join(str(err.get("msg", "")) for err in e.errors())
        print_error(cli_ctx, "VALIDATION_ERROR", messages or "参数校验失败")
    except FileNotFoundError as e:
        print_error(cli_ctx, "VALIDATION_ERROR", f"文本文件不存在: {e.filename}")
    except Exception as e:  # noqa: BLE001
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


def _setting_to_dict(setting: WorldSetting) -> dict:
    """世界观条目领域模型 → JSON-safe dict."""
    return setting.model_dump(mode="json")


# ---------------------------------------------------------------------------
# create  —  inkflow world create --project-id <uuid> --name <str> ...
# ---------------------------------------------------------------------------


@app.command("create")
def create_setting_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    name: str = typer.Option(..., "--name", "-n", help="条目名"),
    category: str = typer.Option("", "--category", "-c", help="类别（空串 = 未分类）"),
    content: str = typer.Option("", "--content", help="条目内容"),
) -> None:
    """创建世界观条目"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = WorldService(repository=SQLiteWorldRepository(session))
            return await svc.create_setting(
                project_id=pid,
                name=name,
                category=category,
                content=content,
            )

    setting = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _setting_to_dict(setting))
    elif setting.category:
        typer.echo(f"✅ 世界观条目创建成功: [{setting.name}] ({setting.category})")
    else:
        typer.echo(f"✅ 世界观条目创建成功: [{setting.name}]")


# ---------------------------------------------------------------------------
# list  —  inkflow world list --project-id <uuid> [--search] [--category] ...
# ---------------------------------------------------------------------------


@app.command("list")
def list_settings_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    search: str | None = typer.Option(None, "--search", "-s", help="按条目名搜索"),
    category: str | None = typer.Option(None, "--category", "-c", help="按类别过滤"),
    sort: str = typer.Option(
        "updated_at", "--sort", help="排序字段 (name / category / updated_at / created_at)"
    ),
    sort_desc: bool = typer.Option(
        True, "--sort-desc/--no-sort-desc", help="按排序字段降序（默认开启）"
    ),
    offset: int = typer.Option(0, "--offset", help="分页偏移"),
    limit: int = typer.Option(50, "--limit", help="每页数量"),
) -> None:
    """列出项目内世界观条目"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = WorldService(repository=SQLiteWorldRepository(session))
            return await svc.list_settings(
                project_id=pid,
                search=search,
                category=category,
                sort_by=sort,
                sort_desc=sort_desc,
                offset=offset,
                limit=limit,
            )

    settings, total = _run(cli_ctx, _impl)
    if not settings and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无条目")
        return
    if not cli_ctx.json_output and total:
        print_result(cli_ctx, f"共 {total} 个条目")
    print_result(cli_ctx, [_setting_to_dict(s) for s in settings])


# ---------------------------------------------------------------------------
# categories  —  inkflow world categories --project-id <uuid>
# ---------------------------------------------------------------------------


@app.command("categories")
def list_categories_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
) -> None:
    """类别汇总（含条目数）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = WorldService(repository=SQLiteWorldRepository(session))
            return await svc.list_categories(project_id=pid)

    categories = _run(cli_ctx, _impl)
    if not categories and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无类别")
        return
    if cli_ctx.json_output:
        print_result(cli_ctx, [{"category": c, "count": n} for c, n in categories])
    else:
        for c, n in categories:
            typer.echo(f"  {c}: {n} 条")


# ---------------------------------------------------------------------------
# get  —  inkflow world get --id <uuid>
# ---------------------------------------------------------------------------


@app.command("get")
def get_setting_cmd(
    ctx: typer.Context,
    setting_id: str = typer.Option(..., "--id", "-i", help="条目 ID (UUID)"),
) -> None:
    """查看世界观条目详情"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, setting_id, "世界观条目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = WorldService(repository=SQLiteWorldRepository(session))
            return await svc.get_setting(setting_id=sid)

    setting = _run(cli_ctx, _impl)
    if setting is None:
        print_error(cli_ctx, "NOT_FOUND", "世界观条目不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _setting_to_dict(setting))
    else:
        typer.echo(f"ID:         {setting.id}")
        typer.echo(f"名称:       {setting.name}")
        typer.echo(f"类别:       {setting.category}")
        typer.echo(f"内容:       {setting.content}")
        typer.echo(f"创建时间:   {setting.created_at}")
        typer.echo(f"更新时间:   {setting.updated_at}")


# ---------------------------------------------------------------------------
# update  —  inkflow world update --id <uuid> [--name] [--category ""] ...
# ---------------------------------------------------------------------------


@app.command("update")
def update_setting_cmd(
    ctx: typer.Context,
    setting_id: str = typer.Option(..., "--id", "-i", help="条目 ID (UUID)"),
    name: str | None = typer.Option(None, "--name", "-n", help="新条目名"),
    category: str | None = typer.Option(
        None, "--category", "-c", help='新类别；传空字符串 "" 表示清除类别（置为未分类）'
    ),
    content: str | None = typer.Option(None, "--content", help="新条目内容"),
) -> None:
    """更新世界观条目（仅更新传入的字段）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, setting_id, "世界观条目不存在")

    async def _impl():
        update_fields: dict[str, object] = {}
        if name is not None:
            update_fields["name"] = name
        if category is not None:
            update_fields["category"] = category
        if content is not None:
            update_fields["content"] = content
        update = WorldUpdate(**update_fields)
        await create_tables()
        async with async_session_factory() as session:
            svc = WorldService(repository=SQLiteWorldRepository(session))
            return await svc.update_setting(setting_id=sid, update=update)

    setting = _run(cli_ctx, _impl)
    if setting is None:
        print_error(cli_ctx, "NOT_FOUND", "世界观条目不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _setting_to_dict(setting))
    else:
        typer.echo(f"✅ 条目已更新: [{setting.name}]")


# ---------------------------------------------------------------------------
# delete  —  inkflow world delete --id <uuid> [--force] [--permanent]
# ---------------------------------------------------------------------------


@app.command("delete")
def delete_setting_cmd(
    ctx: typer.Context,
    setting_id: str = typer.Option(..., "--id", "-i", help="条目 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
    permanent: bool = typer.Option(False, "--permanent", "-p", help="硬删除（物理删除）"),
) -> None:
    """删除世界观条目（默认软删除；--permanent 物理删除）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, setting_id, "世界观条目不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        label = "永久删除" if permanent else "删除"
        if not typer.confirm(f"确定要{label}条目 #{setting_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = WorldService(repository=SQLiteWorldRepository(session))
            return await svc.delete_setting(setting_id=sid, force=permanent)

    ok = _run(cli_ctx, _impl)
    if ok:
        label = "已永久删除" if permanent else "已删除"
        if cli_ctx.json_output:
            print_result(cli_ctx, {"id": str(sid), "deleted": True})
        else:
            typer.echo(f"✅ 条目 #{setting_id} {label}")
    else:
        print_error(cli_ctx, "NOT_FOUND", "世界观条目不存在")


# ---------------------------------------------------------------------------
# restore  —  inkflow world restore --id <uuid>
# ---------------------------------------------------------------------------


@app.command("restore")
def restore_setting_cmd(
    ctx: typer.Context,
    setting_id: str = typer.Option(..., "--id", "-i", help="条目 ID (UUID)"),
) -> None:
    """恢复已删除的世界观条目"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, setting_id, "世界观条目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = WorldService(repository=SQLiteWorldRepository(session))
            return await svc.restore_setting(setting_id=sid)

    setting = _run(cli_ctx, _impl)
    if setting is None:
        print_error(cli_ctx, "NOT_FOUND", "世界观条目不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _setting_to_dict(setting))
    else:
        typer.echo(f"✅ 条目已恢复: [{setting.name}]")


# ---------------------------------------------------------------------------
# extract  —  inkflow world extract --project-id <uuid> --text|--text-file
# ---------------------------------------------------------------------------


@app.command("extract")
def extract_settings_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    text: str = typer.Option("", "--text", help="待提取文本（与 --text-file 互斥）"),
    text_file: str | None = typer.Option(
        None, "--text-file", help="待提取文本文件路径（与 --text 互斥）"
    ),
    model: str | None = typer.Option(
        None, "--model", help="覆盖项目默认模型 (provider/model_name)"
    ),
) -> None:
    """AI 提取世界观条目（spec §5）"""
    cli_ctx: CliContext = ctx.obj
    if text and text_file is not None:
        typer.echo("❌ --text 与 --text-file 不能同时使用", err=True)
        raise typer.Exit(code=2)
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        extract_text = text
        if text_file is not None:
            extract_text = Path(text_file).read_text(encoding="utf-8")
        request = WorldExtractRequest(project_id=pid, text=extract_text, model=model)
        await create_tables()
        async with async_session_factory() as session:
            repo = SQLiteWorldRepository(session)
            svc = WorldService(
                repository=repo,
                extractor=WorldExtractor(
                    llm_client=LangChainLLMClient(),
                    prompt_manager=LangChainPromptManager(),
                    repository=repo,
                ),
                project_repo=SQLiteProjectRepository(session),
            )
            return await svc.extract(request)

    result: WorldExtractionResult = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, result.model_dump(mode="json"))
    else:
        n_created = len(result.created)
        n_updated = len(result.updated)
        n_warnings = len(result.warnings)
        typer.echo(
            f"✅ 提取完成: 新增 {n_created} 个条目, 更新 {n_updated} 个条目, "
            f"警告 {n_warnings} 条"
        )
        if n_warnings:
            typer.echo(f"⚠️ 提取完成但有警告: {'; '.join(result.warnings[:3])}")
