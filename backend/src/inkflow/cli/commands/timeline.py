"""F12 时间线管理 CLI 命令 — `inkflow timeline <action>`.

薄层设计：仅做参数解析/校验与结果格式化，全部业务委托 TimelineService
（spec §4）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130；删除类命令二次确认 + --force；
--json + 无 --force 的删除 → VALIDATION_ERROR。

错误码映射（spec §4/§7）:
- TimelineServiceError → VALIDATION_ERROR
- TimelineNotFoundError / ProjectNotFoundError / 无效 UUID → NOT_FOUND
- 其余异常 → DB_ERROR（F12 无 LLM，无 LLM_ERROR）

依据: specs/f12-timeline-service/spec.md §4/§7。
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
from inkflow.domain.models.timeline import TimelineEvent, TimelineEventUpdate
from inkflow.domain.ports.timeline_errors import (
    ProjectNotFoundError,
    TimelineNotFoundError,
    TimelineServiceError,
)
from inkflow.domain.services.timeline_service import TimelineService
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.database.repositories.timeline_repo import (
    SQLiteTimelineRepository,
)

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
    """执行服务调用并统一映射领域异常为 F7 错误信封（退出码 1）."""
    try:
        return _run_async(coro_fn())
    except typer.Exit:
        raise
    except (TimelineNotFoundError, ProjectNotFoundError) as e:
        print_error(cli_ctx, "NOT_FOUND", str(e))
    except TimelineServiceError as e:
        print_error(cli_ctx, "VALIDATION_ERROR", str(e))
    except ValidationError as e:
        messages = "; ".join(str(err.get("msg", "")) for err in e.errors())
        print_error(cli_ctx, "VALIDATION_ERROR", messages or "参数校验失败")
    except Exception as e:
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


def _event_to_dict(event: TimelineEvent) -> dict:
    """时间线事件领域模型 → JSON-safe dict."""
    return event.model_dump(mode="json")


def _time_label(event: TimelineEvent) -> str:
    """事件时间的人类可读表达（time_display 优先，缺失回退数值；未知 = 时间未知）."""
    if event.time_value is None and not event.time_display:
        return "时间未知"
    return event.time_display or str(event.time_value)


# ---------------------------------------------------------------------------
# create  —  inkflow timeline create --project-id <uuid> --title <str> ...
# ---------------------------------------------------------------------------


@app.command("create")
def create_event_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    title: str = typer.Option(..., "--title", "-t", help="事件标题（1-100 字符）"),
    description: str = typer.Option("", "--description", "-d", help="事件描述"),
    time_value: float | None = typer.Option(
        None, "--time-value", help="世界内时间数值键（缺省 = 时间未知）"
    ),
    time_unit: str = typer.Option("", "--time-unit", help="时间单位标签（仅语义）"),
    time_display: str = typer.Option(
        "", "--time-display", help="原始时间表达（如「青元历 317 年秋」）"
    ),
    narrative_position: int | None = typer.Option(
        None, "--narrative-position", help="叙事位置（缺省 = 叙事末尾追加）"
    ),
    timeline_flag: str = typer.Option(
        "", "--timeline-flag", help="时间线标记（flashback / flashforward）"
    ),
) -> None:
    """创建时间线事件"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = TimelineService(
                repository=SQLiteTimelineRepository(session),
                project_repo=SQLiteProjectRepository(session),
            )
            return await svc.create_event(
                project_id=pid,
                title=title,
                description=description,
                time_value=time_value,
                time_unit=time_unit,
                time_display=time_display,
                narrative_position=narrative_position,
                timeline_flag=timeline_flag,
            )

    event = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _event_to_dict(event))
    else:
        typer.echo(
            f"✅ 事件创建成功: [{event.title}]"
            f"（{_time_label(event)}，叙事第 {event.narrative_position} 位）"
        )


# ---------------------------------------------------------------------------
# list  —  inkflow timeline list --project-id <uuid> [--search] [--sort] ...
# ---------------------------------------------------------------------------


@app.command("list")
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

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = TimelineService(
                repository=SQLiteTimelineRepository(session),
                project_repo=SQLiteProjectRepository(session),
            )
            return await svc.list_events(
                project_id=pid,
                search=search,
                sort_by=sort,
                sort_desc=sort_desc,
            )

    events, total = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, [_event_to_dict(e) for e in events])
        return
    if not events:
        typer.echo("📭 暂无事件")
        return
    typer.echo(f"共 {total} 个事件")
    for e in events:
        typer.echo(f"  #{e.narrative_position} [{e.title}]（{_time_label(e)}）")


# ---------------------------------------------------------------------------
# view  —  inkflow timeline view --project-id <uuid> [--json]
# ---------------------------------------------------------------------------


@app.command("view")
def view_timeline_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
) -> None:
    """双线总览（事件时间线 + 叙事顺序）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = TimelineService(
                repository=SQLiteTimelineRepository(session),
                project_repo=SQLiteProjectRepository(session),
            )
            return await svc.get_timeline_view(project_id=pid)

    view = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, view.model_dump(mode="json"))
    else:
        if view.total == 0:
            typer.echo("📋 双线总览: 共 0 个事件（暂无事件）")
            return
        etl = " ".join(
            f"{i}. {e.title}({_time_label(e)})" for i, e in enumerate(view.event_timeline, 1)
        )
        nol = " ".join(f"{i}. {e.title}" for i, e in enumerate(view.narrative_order, 1))
        typer.echo(
            f"📋 双线总览: 共 {view.total} 个事件 — "
            f"事件时间线（世界内时间升序）: {etl}；叙事顺序: {nol}"
        )


# ---------------------------------------------------------------------------
# check  —  inkflow timeline check --project-id <uuid> [--include-flashbacks/--no-...]
# ---------------------------------------------------------------------------


@app.command("check")
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

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = TimelineService(
                repository=SQLiteTimelineRepository(session),
                project_repo=SQLiteProjectRepository(session),
            )
            return await svc.check_consistency(
                project_id=pid, include_flashbacks=include_flashbacks
            )

    report = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, report.model_dump(mode="json"))
    else:
        if report.consistent:
            typer.echo(
                f"🔍 一致性检查: ✅ 一致（检查 {report.checked} 个事件，"
                f"跳过 {report.skipped} 个时间未知）"
            )
        else:
            typer.echo(
                f"🔍 一致性检查: ⚠️ 发现 {len(report.conflicts)} 个冲突"
                f"（检查 {report.checked} 个事件，跳过 {report.skipped} 个）"
            )
            for conflict in report.conflicts:
                typer.echo(f"   [冲突] {conflict.message}")
        if report.flashbacks:
            typer.echo(
                f"🔍 一致性检查: 💡 {len(report.flashbacks)} 个已声明倒叙/插叙" "（不视为冲突）:"
            )
            for fb in report.flashbacks:
                typer.echo(f"   [倒叙] {fb.message}")


# ---------------------------------------------------------------------------
# get  —  inkflow timeline get --id <uuid>
# ---------------------------------------------------------------------------


@app.command("get")
def get_event_cmd(
    ctx: typer.Context,
    event_id: str = typer.Option(..., "--id", "-i", help="事件 ID (UUID)"),
) -> None:
    """查看时间线事件详情"""
    cli_ctx: CliContext = ctx.obj
    eid = _parse_uuid(cli_ctx, event_id, "事件不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = TimelineService(
                repository=SQLiteTimelineRepository(session),
                project_repo=SQLiteProjectRepository(session),
            )
            return await svc.get_event(event_id=eid)

    event = _run(cli_ctx, _impl)
    if event is None:
        print_error(cli_ctx, "NOT_FOUND", "事件不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _event_to_dict(event))
    else:
        typer.echo(f"ID:           {event.id}")
        typer.echo(f"标题:         {event.title}")
        typer.echo(f"描述:         {event.description}")
        typer.echo(f"世界内时间:   {_time_label(event)}")
        typer.echo(f"时间单位:     {event.time_unit}")
        typer.echo(f"原始时间表达: {event.time_display}")
        typer.echo(f"叙事位置:     {event.narrative_position}")
        typer.echo(f"时间线标记:   {event.timeline_flag or '（正叙）'}")
        typer.echo(f"创建时间:     {event.created_at}")
        typer.echo(f"更新时间:     {event.updated_at}")


# ---------------------------------------------------------------------------
# update  —  inkflow timeline update --id <uuid> [--title] [--time-value ""] ...
# ---------------------------------------------------------------------------


@app.command("update")
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

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = TimelineService(
                repository=SQLiteTimelineRepository(session),
                project_repo=SQLiteProjectRepository(session),
            )
            return await svc.update_event(event_id=eid, update=update)

    event = _run(cli_ctx, _impl)
    if event is None:
        print_error(cli_ctx, "NOT_FOUND", "事件不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _event_to_dict(event))
    else:
        typer.echo(f"✅ 事件已更新: [{event.title}]")


# ---------------------------------------------------------------------------
# delete  —  inkflow timeline delete --id <uuid> [--force] [--permanent]
# ---------------------------------------------------------------------------


@app.command("delete")
def delete_event_cmd(
    ctx: typer.Context,
    event_id: str = typer.Option(..., "--id", "-i", help="事件 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
    permanent: bool = typer.Option(False, "--permanent", "-p", help="硬删除（物理删除）"),
) -> None:
    """删除时间线事件（默认软删除；--permanent 物理删除）"""
    cli_ctx: CliContext = ctx.obj
    eid = _parse_uuid(cli_ctx, event_id, "事件不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        label = "永久删除" if permanent else "删除"
        if not typer.confirm(f"确定要{label}事件 #{event_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = TimelineService(
                repository=SQLiteTimelineRepository(session),
                project_repo=SQLiteProjectRepository(session),
            )
            if permanent:
                return await svc.hard_delete_event(event_id=eid)
            return await svc.soft_delete_event(event_id=eid)

    ok = _run(cli_ctx, _impl)
    if ok:
        label = "已永久删除" if permanent else "已删除"
        if cli_ctx.json_output:
            print_result(cli_ctx, {"id": str(eid), "deleted": True})
        else:
            typer.echo(f"✅ 事件 #{event_id} {label}")
    else:
        print_error(cli_ctx, "NOT_FOUND", "事件不存在")


# ---------------------------------------------------------------------------
# restore  —  inkflow timeline restore --id <uuid>
# ---------------------------------------------------------------------------


@app.command("restore")
def restore_event_cmd(
    ctx: typer.Context,
    event_id: str = typer.Option(..., "--id", "-i", help="事件 ID (UUID)"),
) -> None:
    """恢复已删除的时间线事件"""
    cli_ctx: CliContext = ctx.obj
    eid = _parse_uuid(cli_ctx, event_id, "事件不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = TimelineService(
                repository=SQLiteTimelineRepository(session),
                project_repo=SQLiteProjectRepository(session),
            )
            return await svc.restore_event(event_id=eid)

    event = _run(cli_ctx, _impl)
    if event is None:
        print_error(cli_ctx, "NOT_FOUND", "事件不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _event_to_dict(event))
    else:
        typer.echo(f"✅ 事件已恢复: [{event.title}]")
