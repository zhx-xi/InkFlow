"""F13 伏笔管理 CLI 命令 — `inkflow foreshadowing <action>`.

分层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() + InkFlowHTTPClient
调用内核 REST API（spec §4；Issue #169 CLI 恒经 HTTP）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130；删除类命令二次确认 + --force；
--json + 无 --force 的删除 → VALIDATION_ERROR。

错误码映射（spec §4/§7）：
- HttpApiError：404 → NOT_FOUND、422 → VALIDATION_ERROR、401 → CONFIG_ERROR、
  500 + LLM_ERROR 头 → LLM_ERROR、其余 → INTERNAL_ERROR（spec §5.3）
- KernelStartupError → KERNEL_ERROR
- pydantic ValidationError → VALIDATION_ERROR
- 其余异常 → DB_ERROR（F13 无 LLM，无 LLM_ERROR）

状态机命令（spec §2.4）：resolve（open→resolved）、reopen（resolved→open），
均为幂等操作；不存在的伏笔对其执行 → NOT_FOUND。
update 的 --event-id "" 表示解除事件挂接（置为 None，spec §2.5）。

依据: specs/f13-foreshadowing/spec.md §4/§7。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import typer
from pydantic import ValidationError

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.domain.models.foreshadowing import (
    ForeshadowingCreate,
    ForeshadowingStatus,
    ForeshadowingUpdate,
)
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel
from inkflow.logging import instrument

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
    """执行内核调用并统一映射 HTTP 异常为 F7 错误信封（退出码 1）."""
    try:
        return _run_async(coro_fn())
    except typer.Exit:
        raise
    except HttpApiError as exc:
        code, message = map_http_error(exc.status_code, exc.detail, exc.code)
        print_error(cli_ctx, code, message)
    except KernelStartupError as exc:
        print_error(cli_ctx, "KERNEL_ERROR", f"内核启动失败: {exc}")
    except ValidationError as e:
        messages = "; ".join(str(err.get("msg", "")) for err in e.errors())
        print_error(cli_ctx, "VALIDATION_ERROR", messages or "参数校验失败")
    except Exception as e:
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


def _status_label(foreshadowing: dict) -> str:
    """伏笔状态的人类可读表达（open = 未回收，resolved = 已回收）."""
    return "已回收" if foreshadowing["status"] == ForeshadowingStatus.RESOLVED.value else "未回收"


def _item_label(foreshadowing: dict) -> str:
    """伏笔列表条目的人类可读表达（spec §4.2）."""
    if foreshadowing["status"] == ForeshadowingStatus.RESOLVED.value:
        if foreshadowing.get("resolved_at") is not None:
            return f"[{foreshadowing['title']}] (回收于 {foreshadowing['resolved_at'][:10]})"
        return f"[{foreshadowing['title']}] (已回收)"
    loc = f", {foreshadowing['location']}" if foreshadowing.get("location") else ""
    return f"[{foreshadowing['title']}] (优先级 {foreshadowing['priority']}{loc})"


# ---------------------------------------------------------------------------
# create  — inkflow foreshadowing create --project-id <uuid> --title <str> ...
# ---------------------------------------------------------------------------


@app.command("create")
@instrument(caller_type="cli")
def create_foreshadowing_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    title: str = typer.Option(..., "--title", "-t", help="伏笔名（1-100 字符）"),
    description: str = typer.Option("", "--description", "-d", help="伏笔详情"),
    priority: int = typer.Option(50, "--priority", help="注入优先级（0-100，默认 50）"),
    location: str = typer.Option("", "--location", help="埋设位置自由文本"),
    event_id: str | None = typer.Option(
        None, "--event-id", help="F12 时间线事件锚点 (UUID，缺席 = 不挂接)"
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

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                f"/projects/{pid}/foreshadowings",
                json={
                    "title": data.title,
                    "description": data.description,
                    "priority": data.priority,
                    "location": data.location,
                    "event_id": str(data.event_id) if data.event_id is not None else None,
                },
            )

    foreshadowing = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, foreshadowing)
    else:
        typer.echo(
            f"✅ 伏笔创建成功: [{foreshadowing['title']}]"
            f"（优先级 {foreshadowing['priority']}，{_status_label(foreshadowing)}）"
        )


# ---------------------------------------------------------------------------
# list  — inkflow foreshadowing list --project-id <uuid> [--status] [--search] ...
# ---------------------------------------------------------------------------


@app.command("list")
@instrument(caller_type="cli")
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
    """列出项目内伏笔（默认全部活动伏笔，--status 过滤）"""
    cli_ctx: CliContext = ctx.obj
    if status is not None and status not in ("open", "resolved"):
        typer.echo("⚠️ --status 必须是 open 或 resolved", err=True)
        raise typer.Exit(code=2)
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(
                f"/projects/{pid}/foreshadowings",
                params={
                    "search": search,
                    "status": status,
                    "sort_by": sort,
                    "sort_desc": sort_desc,
                },
            )

    data = _run(cli_ctx, _impl)
    items = data.get("items", [])
    if cli_ctx.json_output:
        print_result(cli_ctx, items)
        return
    if not items:
        typer.echo("📥 暂无伏笔")
        return
    open_items = [f for f in items if f["status"] == ForeshadowingStatus.OPEN.value]
    resolved_items = [f for f in items if f["status"] == ForeshadowingStatus.RESOLVED.value]
    if open_items:
        parts = " ".join(f"{i}. {_item_label(f)}" for i, f in enumerate(open_items, 1))
        typer.echo(f"📌 未回收伏笔 {len(open_items)} 条: {parts}")
    if resolved_items:
        parts = ", ".join(_item_label(f) for f in resolved_items)
        typer.echo(f"🔍 已回收伏笔 {len(resolved_items)} 条: {parts}")


# ---------------------------------------------------------------------------
# get  — inkflow foreshadowing get --id <uuid>
# ---------------------------------------------------------------------------


@app.command("get")
@instrument(caller_type="cli")
def get_foreshadowing_cmd(
    ctx: typer.Context,
    foreshadowing_id: str = typer.Option(..., "--id", "-i", help="伏笔 ID (UUID)"),
) -> None:
    """查看伏笔详情"""
    cli_ctx: CliContext = ctx.obj
    fid = _parse_uuid(cli_ctx, foreshadowing_id, "伏笔不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/foreshadowings/{fid}")

    foreshadowing = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, foreshadowing)
    else:
        typer.echo(f"ID:           {foreshadowing['id']}")
        typer.echo(f"标题:         {foreshadowing['title']}")
        typer.echo(f"描述:         {foreshadowing['description']}")
        typer.echo(f"优先级:       {foreshadowing['priority']}")
        typer.echo(f"状态:         {foreshadowing['status']}（{_status_label(foreshadowing)}）")
        typer.echo(f"埋设位置:     {foreshadowing['location'] or '（未记录）'}")
        typer.echo(f"事件锚点:     {foreshadowing['event_id'] or '（未挂接）'}")
        typer.echo(f"回收时间:     {foreshadowing['resolved_at'] or '（未回收）'}")
        typer.echo(f"创建时间:     {foreshadowing['created_at']}")
        typer.echo(f"更新时间:     {foreshadowing['updated_at']}")


# ---------------------------------------------------------------------------
# update  — inkflow foreshadowing update --id <uuid> [--title] [--event-id ""] ...
# ---------------------------------------------------------------------------


@app.command("update")
@instrument(caller_type="cli")
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

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch(
                f"/foreshadowings/{fid}",
                json=update.model_dump(exclude_unset=True, mode="json"),
            )

    foreshadowing = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, foreshadowing)
    else:
        typer.echo(f"✅ 伏笔已更新: [{foreshadowing['title']}]")


# ---------------------------------------------------------------------------
# delete  — inkflow foreshadowing delete --id <uuid> [--force]
# ---------------------------------------------------------------------------


@app.command("delete")
@instrument(caller_type="cli")
def delete_foreshadowing_cmd(
    ctx: typer.Context,
    foreshadowing_id: str = typer.Option(..., "--id", "-i", help="伏笔 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
) -> None:
    """删除伏笔（v1.1 真删，不可恢复）"""
    cli_ctx: CliContext = ctx.obj
    fid = _parse_uuid(cli_ctx, foreshadowing_id, "伏笔不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        label = "删除"
        if not typer.confirm(f"确定要{label}伏笔 #{foreshadowing_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl() -> None:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            await client.delete(f"/foreshadowings/{fid}")

    _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, {"id": str(fid), "deleted": True})
    else:
        typer.echo(f"✅ 伏笔 #{foreshadowing_id} 已删除")


# ---------------------------------------------------------------------------
# resolve  — inkflow foreshadowing resolve --id <uuid>  （open→resolved）
# ---------------------------------------------------------------------------


@app.command("resolve")
@instrument(caller_type="cli")
def resolve_foreshadowing_cmd(
    ctx: typer.Context,
    foreshadowing_id: str = typer.Option(..., "--id", "-i", help="伏笔 ID (UUID)"),
) -> None:
    """标记回收（open→resolved，自动设置回收时间；幂等）"""
    cli_ctx: CliContext = ctx.obj
    fid = _parse_uuid(cli_ctx, foreshadowing_id, "伏笔不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(f"/foreshadowings/{fid}/resolve")

    foreshadowing = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, foreshadowing)
    else:
        typer.echo(f"✅ 伏笔已回收: [{foreshadowing['title']}]")


# ---------------------------------------------------------------------------
# reopen  — inkflow foreshadowing reopen --id <uuid>  （resolved→open）
# ---------------------------------------------------------------------------


@app.command("reopen")
@instrument(caller_type="cli")
def reopen_foreshadowing_cmd(
    ctx: typer.Context,
    foreshadowing_id: str = typer.Option(..., "--id", "-i", help="伏笔 ID (UUID)"),
) -> None:
    """重新开启（resolved→open，清空回收时间；幂等）"""
    cli_ctx: CliContext = ctx.obj
    fid = _parse_uuid(cli_ctx, foreshadowing_id, "伏笔不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(f"/foreshadowings/{fid}/reopen")

    foreshadowing = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, foreshadowing)
    else:
        typer.echo(f"✅ 伏笔已重新开启: [{foreshadowing['title']}]")
