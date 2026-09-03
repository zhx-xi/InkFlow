"""F12 时间线管理 CLI 命令 — `inkflow timeline <action>`.

分层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() + InkFlowHTTPClient
调用内核 REST API（spec §4；Issue #169 CLI 恒经 HTTP）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130；删除类命令二次确认 + --force；
--json + 无 --force 的删除 → VALIDATION_ERROR。

错误码映射（spec §4/§7）：
- HttpApiError：404 → NOT_FOUND、422 → VALIDATION_ERROR、401 → CONFIG_ERROR、
  500 + LLM_ERROR 头 → LLM_ERROR、其余 → INTERNAL_ERROR（spec §5.3）
- KernelStartupError → KERNEL_ERROR
- pydantic ValidationError / 非法数值 → VALIDATION_ERROR
- 其余异常 → DB_ERROR（F12 无 LLM，无 LLM_ERROR）

依据: specs/f12-timeline/spec.md §4/§7。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import typer
from pydantic import ValidationError

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.domain.models.timeline import TimelineEventUpdate
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel
from inkflow.logging import instrument

app = typer.Typer(name="timeline", help="时间线管理", no_args_is_help=True)


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


def _time_label(event: dict) -> str:
    """事件时间的人类可读表达（time_display 优先，缺失回退数值；未知 = 时间未知）."""
    if event.get("time_value") is None and not event.get("time_display"):
        return "时间未知"
    return event.get("time_display") or str(event.get("time_value"))


# ---------------------------------------------------------------------------
# create  — inkflow timeline create --project-id <uuid> --title <str> ...
# ---------------------------------------------------------------------------


@app.command("create")
@instrument(caller_type="cli")
def create_event_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    title: str = typer.Option(..., "--title", "-t", help="事件标题（1-100 字符）"),
    description: str = typer.Option("", "--description", "-d", help="事件描述"),
    time_value: float | None = typer.Option(
        None, "--time-value", help="世界内时间数值键（缺席 = 时间未知）"
    ),
    time_unit: str = typer.Option("", "--time-unit", help="时间单位标签（仅语义）"),
    time_display: str = typer.Option(
        "", "--time-display", help="原始时间表达（如「青元历 317 年初」）"
    ),
    narrative_position: int | None = typer.Option(
        None, "--narrative-position", help="叙事位置（缺席 = 叙事末尾追加）"
    ),
    timeline_flag: str = typer.Option(
        "", "--timeline-flag", help="时间线标记（flashback / flashforward）"
    ),
) -> None:
    """创建时间线事件"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                f"/projects/{pid}/timeline/events",
                json={
                    "title": title,
                    "description": description,
                    "time_value": time_value,
                    "time_unit": time_unit,
                    "time_display": time_display,
                    "narrative_position": narrative_position,
                    "timeline_flag": timeline_flag,
                },
            )

    event = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, event)
    else:
        typer.echo(
            f"✅ 事件创建成功: [{event['title']}]"
            f"（{_time_label(event)}，叙事第 {event['narrative_position']} 位）"
        )


# ---------------------------------------------------------------------------
# list  — inkflow timeline list --project-id <uuid> [--search] [--sort] ...
# ---------------------------------------------------------------------------


@app.command("list")
@instrument(caller_type="cli")
def list_events_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    search: str | None = typer.Option(None, "--search", "-s", help="按事件标题搜索"),
    sort: str = typer.Option(
        "narrative_position",
        "--sort",
        help="排序字段 (narrative_position / time_value / title / updated_at / created_at)",
    ),
    sort_desc: bool = typer.Option(
        False, "--sort-desc/--no-sort-desc", help="按排序字段降序（默认升序）"
    ),
) -> None:
    """列出项目内时间线事件"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(
                f"/projects/{pid}/timeline/events",
                params={"search": search, "sort_by": sort, "sort_desc": sort_desc},
            )

    data = _run(cli_ctx, _impl)
    events = data.get("items", [])
    total = data.get("total", 0)
    if cli_ctx.json_output:
        print_result(cli_ctx, events)
        return
    if not events:
        typer.echo("📥 暂无事件")
        return
    typer.echo(f"共 {total} 个事件")
    for e in events:
        typer.echo(f"  #{e['narrative_position']} [{e['title']}]（{_time_label(e)}）")


# ---------------------------------------------------------------------------
# view  — inkflow timeline view --project-id <uuid> [--json]
# ---------------------------------------------------------------------------


@app.command("view")
@instrument(caller_type="cli")
def view_timeline_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
) -> None:
    """双线总览（事件时间线 + 叙事顺序）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/projects/{pid}/timeline")

    view = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, view)
    else:
        if view["total"] == 0:
            typer.echo("📈 双线总览: 共 0 个事件（暂无事件）")
            return
        etl = " ".join(
            f"{i}. {e['title']}({_time_label(e)})" for i, e in enumerate(view["event_timeline"], 1)
        )
        nol = " ".join(f"{i}. {e['title']}" for i, e in enumerate(view["narrative_order"], 1))
        typer.echo(
            f"📈 双线总览: 共 {view['total']} 个事件 —— "
            f"事件时间线（世界内时间升序）: {etl}；叙事顺序: {nol}"
        )


# ---------------------------------------------------------------------------
# check  — inkflow timeline check --project-id <uuid> [--include-flashbacks/--no-...]
# ---------------------------------------------------------------------------


@app.command("check")
@instrument(caller_type="cli")
def check_consistency_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    include_flashbacks: bool = typer.Option(
        True,
        "--include-flashbacks/--no-include-flashbacks",
        help="包含已声明的倒叙/插叙项（默认开启）",
    ),
) -> None:
    """一致性检查（对比事件时间线与叙事顺序）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(
                f"/projects/{pid}/timeline/check",
                params={"include_flashbacks": include_flashbacks},
            )

    report = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, report)
    else:
        if report["consistent"]:
            typer.echo(
                f"📊 一致性检查: ✅ 一致（检查 {report['checked']} 个事件，"
                f"跳过 {report['skipped']} 个时间未知）"
            )
        else:
            typer.echo(
                f"📊 一致性检查: ⚠️ 发现 {len(report['conflicts'])} 个冲突"
                f"（检查 {report['checked']} 个事件，跳过 {report['skipped']} 个）"
            )
            for conflict in report["conflicts"]:
                typer.echo(f"   [冲突] {conflict['message']}")
        if report["flashbacks"]:
            typer.echo(
                f"📊 一致性检查: 💡 {len(report['flashbacks'])} 个已声明倒叙/插叙" "（不视为冲突）"
            )
            for fb in report["flashbacks"]:
                typer.echo(f"   [倒叙] {fb['message']}")


# ---------------------------------------------------------------------------
# get  — inkflow timeline get --id <uuid>
# ---------------------------------------------------------------------------


@app.command("get")
@instrument(caller_type="cli")
def get_event_cmd(
    ctx: typer.Context,
    event_id: str = typer.Option(..., "--id", "-i", help="事件 ID (UUID)"),
) -> None:
    """查看时间线事件详情"""
    cli_ctx: CliContext = ctx.obj
    eid = _parse_uuid(cli_ctx, event_id, "事件不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/timeline/events/{eid}")

    event = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, event)
    else:
        typer.echo(f"ID:           {event['id']}")
        typer.echo(f"标题:         {event['title']}")
        typer.echo(f"描述:         {event['description']}")
        typer.echo(f"世界内时间:   {_time_label(event)}")
        typer.echo(f"时间单位:     {event['time_unit']}")
        typer.echo(f"原始时间表达: {event['time_display']}")
        typer.echo(f"叙事位置:     {event['narrative_position']}")
        typer.echo(f"时间线标记:   {event['timeline_flag'] or '（正叙）'}")
        typer.echo(f"创建时间:     {event['created_at']}")
        typer.echo(f"更新时间:     {event['updated_at']}")


# ---------------------------------------------------------------------------
# update  — inkflow timeline update --id <uuid> [--title] [--time-value ""] ...
# ---------------------------------------------------------------------------


@app.command("update")
@instrument(caller_type="cli")
def update_event_cmd(
    ctx: typer.Context,
    event_id: str = typer.Option(..., "--id", "-i", help="事件 ID (UUID)"),
    title: str | None = typer.Option(None, "--title", "-t", help="新事件标题"),
    description: str | None = typer.Option(None, "--description", "-d", help="新事件描述"),
    time_value: str | None = typer.Option(
        None,
        "--time-value",
        help='新世界内时间数值；传空字符串 "" 表示清除（置为未知）',
    ),
    time_unit: str | None = typer.Option(None, "--time-unit", help="新时间单位标签"),
    time_display: str | None = typer.Option(None, "--time-display", help="新原始时间表达"),
    narrative_position: int | None = typer.Option(None, "--narrative-position", help="新叙事位置"),
    timeline_flag: str | None = typer.Option(
        None,
        "--timeline-flag",
        help='新时间线标记；传空字符串 "" 表示清除标记（置为正叙）',
    ),
) -> None:
    """更新时间线事件（仅更新传入的字段）"""
    cli_ctx: CliContext = ctx.obj
    eid = _parse_uuid(cli_ctx, event_id, "事件不存在")

    update_fields: dict[str, Any] = {}
    if title is not None:
        update_fields["title"] = title
    if description is not None:
        update_fields["description"] = description
    if time_value is not None:
        if time_value == "":
            update_fields["time_value"] = ""  # "" = 清除世界内时间（spec §7）
        else:
            try:
                update_fields["time_value"] = float(time_value)
            except ValueError:
                print_error(cli_ctx, "VALIDATION_ERROR", "世界内时间必须是有限数值")
    if time_unit is not None:
        update_fields["time_unit"] = time_unit
    if time_display is not None:
        update_fields["time_display"] = time_display
    if narrative_position is not None:
        update_fields["narrative_position"] = narrative_position
    if timeline_flag is not None:
        update_fields["timeline_flag"] = timeline_flag
    update = TimelineEventUpdate(**update_fields)

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch(
                f"/timeline/events/{eid}",
                json=update.model_dump(exclude_unset=True, mode="json"),
            )

    event = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, event)
    else:
        typer.echo(f"✅ 事件已更新: [{event['title']}]")


# ---------------------------------------------------------------------------
# delete  — inkflow timeline delete --id <uuid> [--force]
# ---------------------------------------------------------------------------


@app.command("delete")
@instrument(caller_type="cli")
def delete_event_cmd(
    ctx: typer.Context,
    event_id: str = typer.Option(..., "--id", "-i", help="事件 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
) -> None:
    """真删时间线事件（v1.1，不可恢复）"""
    cli_ctx: CliContext = ctx.obj
    eid = _parse_uuid(cli_ctx, event_id, "事件不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        if not typer.confirm(f"确定要删除事件 #{event_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl() -> None:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            await client.delete(f"/timeline/events/{eid}")

    _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, {"id": str(eid), "deleted": True})
    else:
        typer.echo(f"✅ 事件 #{event_id} 已删除")
