"""F13 伏笔管理 CLI 命令 — `inkflow foreshadowing <action>`.

薄层设计：仅做参数解析/校验与结果格式化，全部业务委托 ForeshadowingService
（spec §4）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130；删除类命令二次确认 + --force；
--json + 无 --force 的删除 → VALIDATION_ERROR。

错误码映射（spec §4/§7）:
- ForeshadowingServiceError（含同名冲突/事件校验）→ VALIDATION_ERROR
- ForeshadowingNotFoundError / ProjectNotFoundError / 无效 UUID → NOT_FOUND
- 其余异常 → DB_ERROR（F13 无 LLM，无 LLM_ERROR）

状态机命令（spec §2.4）: resolve（open→resolved）/ reopen（resolved→open），
均为幂等操作；软删除伏笔对其执行 → NOT_FOUND。
update 的 --event-id "" 表示解除事件挂接（置为 None，spec §2.5）。

依据: specs/f13-foreshadowing-service/spec.md §4/§7。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import typer
from pydantic import ValidationError

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.core.database import async_session_factory, create_tables
from inkflow.domain.models.foreshadowing import (
    Foreshadowing,
    ForeshadowingCreate,
    ForeshadowingStatus,
    ForeshadowingUpdate,
)
from inkflow.domain.ports.foreshadowing_errors import (
    ForeshadowingNotFoundError,
    ForeshadowingServiceError,
    ProjectNotFoundError,
)
from inkflow.domain.services.foreshadowing_service import ForeshadowingService
from inkflow.infrastructure.database.repositories.foreshadowing_repo import (
    SQLiteForeshadowingRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.database.repositories.timeline_repo import (
    SQLiteTimelineRepository,
)

app = typer.Typer(name="foreshadowing", help="伏笔管理", no_args_is_help=True)


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
    except (ForeshadowingNotFoundError, ProjectNotFoundError) as e:
        print_error(cli_ctx, "NOT_FOUND", str(e))
    except ForeshadowingServiceError as e:
        print_error(cli_ctx, "VALIDATION_ERROR", str(e))
    except ValidationError as e:
        messages = "; ".join(str(err.get("msg", "")) for err in e.errors())
        print_error(cli_ctx, "VALIDATION_ERROR", messages or "参数校验失败")
    except Exception as e:  # noqa: BLE001
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


def _to_dict(foreshadowing: Foreshadowing) -> dict:
    """伏笔领域模型 → JSON-safe dict."""
    return foreshadowing.model_dump(mode="json")


def _status_label(foreshadowing: Foreshadowing) -> str:
    """伏笔状态的人类可读表达（open = 未回收，resolved = 已回收）."""
    if foreshadowing.status == ForeshadowingStatus.RESOLVED:
        return "已回收"
    return "未回收"


def _item_label(foreshadowing: Foreshadowing) -> str:
    """伏笔列表条目的人类可读表达（spec §4.2）."""
    if foreshadowing.status == ForeshadowingStatus.RESOLVED:
        if foreshadowing.resolved_at is not None:
            return f"[{foreshadowing.title}] (回收于 {foreshadowing.resolved_at.date()})"
        return f"[{foreshadowing.title}] (已回收)"
    loc = f", {foreshadowing.location}" if foreshadowing.location else ""
    return f"[{foreshadowing.title}] (优先级 {foreshadowing.priority}{loc})"


def _make_service(session) -> ForeshadowingService:
    """构造注入完整依赖的 ForeshadowingService（ADR-015）."""
    return ForeshadowingService(
        repository=SQLiteForeshadowingRepository(session),
        project_repo=SQLiteProjectRepository(session),
        timeline_repo=SQLiteTimelineRepository(session),
    )


# ---------------------------------------------------------------------------
# create  —  inkflow foreshadowing create --project-id <uuid> --title <str> ...
# ---------------------------------------------------------------------------


@app.command("create")
def create_foreshadowing_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    title: str = typer.Option(..., "--title", "-t", help="伏笔名（1-100 字符）"),
    description: str = typer.Option("", "--description", "-d", help="伏笔详情"),
    priority: int = typer.Option(50, "--priority", help="注入优先级（0-100，默认 50）"),
    location: str = typer.Option("", "--location", help="埋设位置自由文本"),
    event_id: str | None = typer.Option(
        None, "--event-id", help="F12 时间线事件锚点 (UUID，缺省 = 不挂接)"
    ),
) -> None:
    """创建伏笔（status 固定为 open，即创建即埋设）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")
    parsed_event_id: uuid.UUID | None = None
    if event_id is not None:
        parsed_event_id = _parse_uuid(cli_ctx, event_id, "事件不存在")
    data = ForeshadowingCreate(
        project_id=pid,
        title=title,
        description=description,
        priority=priority,
        location=location,
        event_id=parsed_event_id,
    )

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).create(data=data)

    foreshadowing = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _to_dict(foreshadowing))
    else:
        typer.echo(
            f"✅ 伏笔创建成功: [{foreshadowing.title}]"
            f"（优先级 {foreshadowing.priority}，{_status_label(foreshadowing)}）"
        )


# ---------------------------------------------------------------------------
# list  —  inkflow foreshadowing list --project-id <uuid> [--status] [--search] ...
# ---------------------------------------------------------------------------


@app.command("list")
def list_foreshadowings_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    status: str | None = typer.Option(None, "--status", help="状态过滤 (open / resolved)"),
    search: str | None = typer.Option(None, "--search", "-s", help="按伏笔名搜索"),
    sort: str = typer.Option(
        "priority",
        "--sort",
        help="排序字段 (priority / title / status / updated_at / created_at)",
    ),
    sort_desc: bool = typer.Option(
        False, "--sort-desc/--no-sort-desc", help="按排序字段降序（默认升序）"
    ),
) -> None:
    """列出项目内伏笔（默认全部活动伏笔；--status 过滤）"""
    cli_ctx: CliContext = ctx.obj
    if status is not None and status not in ("open", "resolved"):
        typer.echo("❌ --status 必须是 open 或 resolved", err=True)
        raise typer.Exit(code=2)
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).list(
                project_id=pid,
                search=search,
                status=status,
                sort_by=sort,
                sort_desc=sort_desc,
            )

    items, total = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, [_to_dict(f) for f in items])
        return
    if not items:
        typer.echo("📭 暂无伏笔")
        return
    open_items = [f for f in items if f.status == ForeshadowingStatus.OPEN]
    resolved_items = [f for f in items if f.status == ForeshadowingStatus.RESOLVED]
    if open_items:
        parts = " ".join(f"{i}. {_item_label(f)}" for i, f in enumerate(open_items, 1))
        typer.echo(f"📋 未回收伏笔 {len(open_items)} 条: {parts}")
    if resolved_items:
        parts = ", ".join(_item_label(f) for f in resolved_items)
        typer.echo(f"🔍 已回收伏笔 {len(resolved_items)} 条: {parts}")


# ---------------------------------------------------------------------------
# get  —  inkflow foreshadowing get --id <uuid>
# ---------------------------------------------------------------------------


@app.command("get")
def get_foreshadowing_cmd(
    ctx: typer.Context,
    foreshadowing_id: str = typer.Option(..., "--id", "-i", help="伏笔 ID (UUID)"),
) -> None:
    """查看伏笔详情"""
    cli_ctx: CliContext = ctx.obj
    fid = _parse_uuid(cli_ctx, foreshadowing_id, "伏笔不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).get(foreshadowing_id=fid)

    foreshadowing = _run(cli_ctx, _impl)
    if foreshadowing is None:
        print_error(cli_ctx, "NOT_FOUND", "伏笔不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _to_dict(foreshadowing))
    else:
        typer.echo(f"ID:           {foreshadowing.id}")
        typer.echo(f"标题:         {foreshadowing.title}")
        typer.echo(f"描述:         {foreshadowing.description}")
        typer.echo(f"优先级:       {foreshadowing.priority}")
        typer.echo(f"状态:         {foreshadowing.status.value}（{_status_label(foreshadowing)}）")
        typer.echo(f"埋设位置:     {foreshadowing.location or '（未记录）'}")
        typer.echo(f"事件锚点:     {foreshadowing.event_id or '（未挂接）'}")
        typer.echo(f"回收时间:     {foreshadowing.resolved_at or '（未回收）'}")
        typer.echo(f"创建时间:     {foreshadowing.created_at}")
        typer.echo(f"更新时间:     {foreshadowing.updated_at}")


# ---------------------------------------------------------------------------
# update  —  inkflow foreshadowing update --id <uuid> [--title] [--event-id ""] ...
# ---------------------------------------------------------------------------


@app.command("update")
def update_foreshadowing_cmd(
    ctx: typer.Context,
    foreshadowing_id: str = typer.Option(..., "--id", "-i", help="伏笔 ID (UUID)"),
    title: str | None = typer.Option(None, "--title", "-t", help="新伏笔名"),
    description: str | None = typer.Option(None, "--description", "-d", help="新伏笔详情"),
    priority: int | None = typer.Option(None, "--priority", help="新注入优先级（0-100）"),
    location: str | None = typer.Option(
        None, "--location", help='新埋设位置；传空字符串 "" 表示清除'
    ),
    event_id: str | None = typer.Option(
        None, "--event-id", help='新事件锚点 (UUID)；传空字符串 "" 表示解除挂接'
    ),
) -> None:
    """更新伏笔（仅更新传入的字段；status 不可直接修改）"""
    cli_ctx: CliContext = ctx.obj
    fid = _parse_uuid(cli_ctx, foreshadowing_id, "伏笔不存在")

    update_fields: dict[str, Any] = {}
    if title is not None:
        update_fields["title"] = title
    if description is not None:
        update_fields["description"] = description
    if priority is not None:
        update_fields["priority"] = priority
    if location is not None:
        update_fields["location"] = location
    if event_id is not None:
        if event_id == "":
            update_fields["event_id"] = ""  # "" = 解除事件挂接（spec §2.5）
        else:
            update_fields["event_id"] = _parse_uuid(cli_ctx, event_id, "事件不存在")
    update = ForeshadowingUpdate(**update_fields)

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).update(foreshadowing_id=fid, data=update)

    foreshadowing = _run(cli_ctx, _impl)
    if foreshadowing is None:
        print_error(cli_ctx, "NOT_FOUND", "伏笔不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _to_dict(foreshadowing))
    else:
        typer.echo(f"✅ 伏笔已更新: [{foreshadowing.title}]")


# ---------------------------------------------------------------------------
# delete  —  inkflow foreshadowing delete --id <uuid> [--force] [--permanent]
# ---------------------------------------------------------------------------


@app.command("delete")
def delete_foreshadowing_cmd(
    ctx: typer.Context,
    foreshadowing_id: str = typer.Option(..., "--id", "-i", help="伏笔 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
    permanent: bool = typer.Option(False, "--permanent", "-p", help="硬删除（物理删除）"),
) -> None:
    """删除伏笔（默认软删除；--permanent 物理删除）"""
    cli_ctx: CliContext = ctx.obj
    fid = _parse_uuid(cli_ctx, foreshadowing_id, "伏笔不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        label = "永久删除" if permanent else "删除"
        if not typer.confirm(f"确定要{label}伏笔 #{foreshadowing_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = _make_service(session)
            existing = await svc.get(foreshadowing_id=fid)
            if existing is None:
                return None
            if permanent:
                ok = await svc.hard_delete(foreshadowing_id=fid)
            else:
                ok = await svc.soft_delete(foreshadowing_id=fid)
            return existing, ok

    result = _run(cli_ctx, _impl)
    if result is None:
        print_error(cli_ctx, "NOT_FOUND", "伏笔不存在")
    existing, ok = result
    if not ok:
        print_error(cli_ctx, "NOT_FOUND", "伏笔不存在")
    label = "已永久删除" if permanent else "已删除"
    if cli_ctx.json_output:
        print_result(cli_ctx, {"id": str(fid), "deleted": True})
    else:
        typer.echo(f"✅ 伏笔{label}: [{existing.title}]")


# ---------------------------------------------------------------------------
# restore  —  inkflow foreshadowing restore --id <uuid>
# ---------------------------------------------------------------------------


@app.command("restore")
def restore_foreshadowing_cmd(
    ctx: typer.Context,
    foreshadowing_id: str = typer.Option(..., "--id", "-i", help="伏笔 ID (UUID)"),
) -> None:
    """恢复已删除的伏笔"""
    cli_ctx: CliContext = ctx.obj
    fid = _parse_uuid(cli_ctx, foreshadowing_id, "伏笔不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).restore(foreshadowing_id=fid)

    foreshadowing = _run(cli_ctx, _impl)
    if foreshadowing is None:
        print_error(cli_ctx, "NOT_FOUND", "伏笔不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _to_dict(foreshadowing))
    else:
        typer.echo(f"✅ 伏笔已恢复: [{foreshadowing.title}]")


# ---------------------------------------------------------------------------
# resolve  —  inkflow foreshadowing resolve --id <uuid>  （open→resolved）
# ---------------------------------------------------------------------------


@app.command("resolve")
def resolve_foreshadowing_cmd(
    ctx: typer.Context,
    foreshadowing_id: str = typer.Option(..., "--id", "-i", help="伏笔 ID (UUID)"),
) -> None:
    """标记回收（open→resolved，自动设置回收时间；幂等）"""
    cli_ctx: CliContext = ctx.obj
    fid = _parse_uuid(cli_ctx, foreshadowing_id, "伏笔不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).resolve(foreshadowing_id=fid)

    foreshadowing = _run(cli_ctx, _impl)
    if foreshadowing is None:
        print_error(cli_ctx, "NOT_FOUND", "伏笔不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _to_dict(foreshadowing))
    else:
        typer.echo(f"✅ 伏笔已回收: [{foreshadowing.title}]")


# ---------------------------------------------------------------------------
# reopen  —  inkflow foreshadowing reopen --id <uuid>  （resolved→open）
# ---------------------------------------------------------------------------


@app.command("reopen")
def reopen_foreshadowing_cmd(
    ctx: typer.Context,
    foreshadowing_id: str = typer.Option(..., "--id", "-i", help="伏笔 ID (UUID)"),
) -> None:
    """重新开启（resolved→open，清空回收时间；幂等）"""
    cli_ctx: CliContext = ctx.obj
    fid = _parse_uuid(cli_ctx, foreshadowing_id, "伏笔不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).reopen(foreshadowing_id=fid)

    foreshadowing = _run(cli_ctx, _impl)
    if foreshadowing is None:
        print_error(cli_ctx, "NOT_FOUND", "伏笔不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _to_dict(foreshadowing))
    else:
        typer.echo(f"✅ 伏笔已重新开启: [{foreshadowing.title}]")
