"""F24 会话管理 CLI 命令 — `inkflow session <action>` + `session log <action>`.

薄层设计：仅做参数解析/校验与结果格式化，全部业务委托 SessionService
（spec §4）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2。

错误码映射（spec §4/§7）:
- SessionServiceError（含 SessionTransitionError）/ pydantic ValidationError
  → VALIDATION_ERROR
- SessionNotFoundError / ProjectNotFoundError / 无效 UUID → NOT_FOUND
- 其余异常 → DB_ERROR（"内部错误: ..."）；typer 参数解析错误（非法枚举、
  --context-json/--context-file 互斥等）→ 退出码 2

状态机命令（spec §2.4）：pause（active→paused）/ resume（paused→active）/
complete（active|paused→completed）/ fail（active|paused→failed）。
删除为两级语义（spec §2.5）：默认归档（force=False）、--force 直删。

依据: specs/f24-session-service/spec.md §4/§7。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from pydantic import BaseModel, ValidationError

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.core.database import async_session_factory, create_tables
from inkflow.domain.models.session import (
    LogLevel,
    Session,
    SessionComplete,
    SessionCreate,
    SessionFail,
    SessionLogCreate,
    SessionLogEntry,
    SessionStatus,
    SessionType,
    SessionUpdate,
    SessionView,
)
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.session_errors import (
    SessionNotFoundError,
    SessionServiceError,
)
from inkflow.domain.services.session_service import SessionService
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.database.repositories.session_repo import (
    SQLiteSessionRepository,
)

app = typer.Typer(name="session", help="会话管理", no_args_is_help=True)

log_app = typer.Typer(name="log", help="会话履历日志", no_args_is_help=True)


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
    except (SessionNotFoundError, ProjectNotFoundError) as e:
        print_error(cli_ctx, "NOT_FOUND", str(e))
    except SessionServiceError as e:
        print_error(cli_ctx, "VALIDATION_ERROR", str(e))
    except ValidationError as e:
        messages = "; ".join(str(err.get("msg", "")) for err in e.errors())
        print_error(cli_ctx, "VALIDATION_ERROR", messages or "参数校验失败")
    except Exception as e:
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


def _utc_aware(value: Any) -> Any:
    """递归将 naive datetime 归一为 UTC aware（aware 值原样保留）."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, dict):
        return {k: _utc_aware(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_utc_aware(v) for v in value]
    return value


def _dump(model: BaseModel) -> dict[str, Any]:
    """序列化模型为 JSON dict（datetime 统一 UTC，spec §3.2 响应 Z 后缀）."""
    data = _utc_aware(model.model_dump(mode="python"))
    return type(model).model_validate(data).model_dump(mode="json")


def _session_to_dict(session: Session) -> dict:
    """会话领域模型 → JSON-safe dict."""
    return _dump(session)


def _view_to_dict(view: SessionView) -> dict:
    """会话视图（含履历摘要）→ JSON-safe dict."""
    return _dump(view)


def _log_to_dict(entry: SessionLogEntry) -> dict:
    """日志条目领域模型 → JSON-safe dict."""
    return _dump(entry)


def _require_enum(value: str | None, allowed: tuple[str, ...], flag: str) -> None:
    """校验枚举选项值；非法值 → 退出码 2（F7 §7 非法枚举值语义）."""
    if value is not None and value not in allowed:
        typer.echo(f"❌ {flag} 必须是 {'/'.join(allowed)} 之一", err=True)
        raise typer.Exit(code=2)


def _parse_json_value(raw: str, flag: str) -> dict[str, Any]:
    """解析 JSON 参数；非法 JSON 或非对象 → 退出码 2（typer 用法错误语义）."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        typer.echo(f"❌ {flag} 不是合法 JSON: {e}", err=True)
        raise typer.Exit(code=2) from None
    if not isinstance(parsed, dict):
        typer.echo(f"❌ {flag} 必须是 JSON 对象", err=True)
        raise typer.Exit(code=2) from None
    return parsed


def _resolve_context(context_json: str | None, context_file: str | None) -> dict[str, Any]:
    """解析上下文快照：--context-json / --context-file 双通道（互斥，同 F9）."""
    if context_json is not None and context_file is not None:
        typer.echo("❌ --context-json 与 --context-file 不能同时使用", err=True)
        raise typer.Exit(code=2)
    if context_file is not None:
        try:
            raw = Path(context_file).read_text(encoding="utf-8")
        except OSError as e:
            typer.echo(f"❌ 上下文文件读取失败: {e}", err=True)
            raise typer.Exit(code=2) from None
        return _parse_json_value(raw, "--context-file")
    if context_json is not None:
        return _parse_json_value(context_json, "--context-json")
    return {}


def _make_service(session) -> SessionService:
    """构造注入完整依赖的 SessionService（ADR-015）."""
    return SessionService(
        repository=SQLiteSessionRepository(session),
        project_repo=SQLiteProjectRepository(session),
    )


# ---------------------------------------------------------------------------
# create  —  inkflow session create --type <writing|task> [--project-id] ...
# ---------------------------------------------------------------------------


@app.command("create")
def create_session_cmd(
    ctx: typer.Context,
    session_type: str = typer.Option(..., "--type", help="会话类型 (writing / task)"),
    project_id: str | None = typer.Option(
        None, "--project-id", help="项目 ID (UUID；缺省 = 全局会话)"
    ),
    title: str = typer.Option(..., "--title", "-t", help="会话标题（1-100 字符）"),
    description: str = typer.Option("", "--description", "-d", help="会话描述"),
    context_json: str | None = typer.Option(
        None, "--context-json", help="上下文快照 JSON（与 --context-file 互斥）"
    ),
    context_file: str | None = typer.Option(
        None, "--context-file", help="上下文快照 JSON 文件路径（与 --context-json 互斥）"
    ),
) -> None:
    """创建会话（创建即 active；project_id 可空）"""
    cli_ctx: CliContext = ctx.obj
    _require_enum(session_type, ("writing", "task"), "--type")
    context = _resolve_context(context_json, context_file)
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在") if project_id is not None else None
    data = SessionCreate(
        session_type=SessionType(session_type),
        project_id=pid,
        title=title,
        description=description,
        context=context,
    )

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).create(data=data)

    view = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _view_to_dict(view))
    else:
        typer.echo(f"✅ 会话创建成功: [{view.session.title}]")


# ---------------------------------------------------------------------------
# list  —  inkflow session list [--type] [--status] [--project-id] ...
# ---------------------------------------------------------------------------


@app.command("list")
def list_sessions_cmd(
    ctx: typer.Context,
    session_type: str | None = typer.Option(None, "--type", help="会话类型过滤 (writing / task)"),
    status: str | None = typer.Option(
        None, "--status", help="状态过滤 (active / paused / completed / failed)"
    ),
    project_id: str | None = typer.Option(None, "--project-id", help="项目 ID 过滤 (UUID)"),
    search: str | None = typer.Option(None, "--search", "-s", help="按标题搜索"),
    limit: int = typer.Option(50, "--limit", help="每页数量"),
    offset: int = typer.Option(0, "--offset", help="分页偏移"),
) -> None:
    """列出活动会话（履历查询；归档会话不显示）"""
    cli_ctx: CliContext = ctx.obj
    _require_enum(session_type, ("writing", "task"), "--type")
    _require_enum(status, ("active", "paused", "completed", "failed"), "--status")
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在") if project_id is not None else None

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).list(
                session_type=SessionType(session_type) if session_type else None,
                status=SessionStatus(status) if status else None,
                project_id=pid,
                search=search,
                limit=limit,
                offset=offset,
            )

    items, total = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(
            cli_ctx,
            {
                "items": [_view_to_dict(v) for v in items],
                "total": total,
                "offset": offset,
                "limit": limit,
            },
        )
        return
    if not items:
        typer.echo("📭 暂无会话")
        return
    for v in items:
        typer.echo(
            f"[{v.session.id}] {v.session.title} "
            f"({v.session.session_type.value}/{v.session.status.value}) — 日志 {v.log_count} 条"
        )
    typer.echo(f"共 {total} 个会话")


# ---------------------------------------------------------------------------
# get  —  inkflow session get --id <uuid>
# ---------------------------------------------------------------------------


@app.command("get")
def get_session_cmd(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--id", "-i", help="会话 ID (UUID)"),
) -> None:
    """查看会话详情（含履历摘要与日志条数）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, session_id, "会话不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).get(session_id=sid)

    view = _run(cli_ctx, _impl)
    if view is None:
        print_error(cli_ctx, "NOT_FOUND", "会话不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _view_to_dict(view))
    else:
        typer.echo(
            f"会话: {view.session.title} "
            f"({view.session.session_type.value}/{view.session.status.value})"
        )
        typer.echo(f"项目: {view.session.project_id}")
        typer.echo(f"开始: {view.session.started_at} | 日志: {view.log_count} 条")
        typer.echo(f"上下文: {view.session.context}")


# ---------------------------------------------------------------------------
# update  —  inkflow session update --id <uuid> [--title] [--description] ...
# ---------------------------------------------------------------------------


@app.command("update")
def update_session_cmd(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--id", "-i", help="会话 ID (UUID)"),
    title: str | None = typer.Option(None, "--title", "-t", help="新会话标题"),
    description: str | None = typer.Option(None, "--description", "-d", help="新会话描述"),
    context_json: str | None = typer.Option(None, "--context-json", help="新上下文快照 JSON"),
) -> None:
    """更新会话（仅更新传入的字段；status 不可直接修改）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, session_id, "会话不存在")

    update_fields: dict[str, Any] = {}
    if title is not None:
        update_fields["title"] = title
    if description is not None:
        update_fields["description"] = description
    if context_json is not None:
        update_fields["context"] = _parse_json_value(context_json, "--context-json")
    data = SessionUpdate(**update_fields)

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).update(session_id=sid, data=data)

    updated = _run(cli_ctx, _impl)
    if updated is None:
        print_error(cli_ctx, "NOT_FOUND", "会话不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _session_to_dict(updated))
    else:
        typer.echo(f"✅ 会话已更新: [{updated.title}]")


# ---------------------------------------------------------------------------
# 状态机动作  —  pause / resume / complete / fail
# ---------------------------------------------------------------------------


@app.command("pause")
def pause_session_cmd(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--id", "-i", help="会话 ID (UUID)"),
) -> None:
    """暂停会话（active→paused）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, session_id, "会话不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).pause(session_id=sid)

    session = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _session_to_dict(session))
    else:
        typer.echo(f"✅ 会话已暂停: [{session.title}]")


@app.command("resume")
def resume_session_cmd(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--id", "-i", help="会话 ID (UUID)"),
) -> None:
    """恢复会话（paused→active；清空 paused_at）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, session_id, "会话不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).resume(session_id=sid)

    session = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _session_to_dict(session))
    else:
        typer.echo(f"✅ 会话已恢复: [{session.title}]")


@app.command("complete")
def complete_session_cmd(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--id", "-i", help="会话 ID (UUID)"),
    result_json: str | None = typer.Option(None, "--result-json", help="完成结果 JSON"),
) -> None:
    """完成会话（active|paused→completed）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, session_id, "会话不存在")
    result = _parse_json_value(result_json, "--result-json") if result_json is not None else {}
    data = SessionComplete(result=result)

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).complete(session_id=sid, data=data)

    session = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _session_to_dict(session))
    else:
        typer.echo(f"✅ 会话已完成: [{session.title}]")


@app.command("fail")
def fail_session_cmd(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--id", "-i", help="会话 ID (UUID)"),
    error: str = typer.Option(..., "--error", help="失败原因"),
) -> None:
    """失败会话（active|paused→failed）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, session_id, "会话不存在")
    data = SessionFail(error=error)

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).fail(session_id=sid, data=data)

    session = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _session_to_dict(session))
    else:
        typer.echo(f"✅ 会话已失败: [{session.title}]")


# ---------------------------------------------------------------------------
# logs  —  inkflow session logs --id <uuid> [--limit] [--offset]
# ---------------------------------------------------------------------------


@app.command("logs")
def list_logs_cmd(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--id", "-i", help="会话 ID (UUID)"),
    limit: int = typer.Option(50, "--limit", help="每页数量"),
    offset: int = typer.Option(0, "--offset", help="分页偏移"),
) -> None:
    """查看会话履历日志（seq ASC）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, session_id, "会话不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).list_logs(
                session_id=sid, limit=limit, offset=offset
            )

    items, total = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(
            cli_ctx,
            {
                "items": [_log_to_dict(entry) for entry in items],
                "total": total,
                "offset": offset,
                "limit": limit,
            },
        )
        return
    if not items:
        typer.echo("📭 暂无日志")
        return
    for entry in items:
        typer.echo(f"#{entry.seq} [{entry.level.value}] {entry.message}")
    typer.echo(f"共 {total} 条日志")


# ---------------------------------------------------------------------------
# log add  —  inkflow session log add --id <uuid> [--level] --message <str> ...
# ---------------------------------------------------------------------------


@log_app.command("add")
def add_log_cmd(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--id", "-i", help="会话 ID (UUID)"),
    level: str = typer.Option("info", "--level", help="日志级别 (info / warning / error)"),
    message: str = typer.Option(..., "--message", "-m", help="日志消息"),
    payload_json: str | None = typer.Option(None, "--payload-json", help="结构化负载 JSON"),
) -> None:
    """追加会话履历日志（seq 自动递增；终态也可补记）"""
    cli_ctx: CliContext = ctx.obj
    _require_enum(level, ("info", "warning", "error"), "--level")
    sid = _parse_uuid(cli_ctx, session_id, "会话不存在")
    payload = _parse_json_value(payload_json, "--payload-json") if payload_json is not None else {}
    data = SessionLogCreate(level=LogLevel(level), message=message, payload=payload)

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).add_log(session_id=sid, data=data)

    entry = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _log_to_dict(entry))
    else:
        typer.echo(f"✅ 日志已添加: #{entry.seq} [{entry.level.value}] {entry.message}")


# ---------------------------------------------------------------------------
# delete / restore  —  两级删除（归档 → 真实删除）+ 解除归档
# ---------------------------------------------------------------------------


@app.command("delete")
def delete_session_cmd(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--id", "-i", help="会话 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="直接真实删除（跳过归档）"),
) -> None:
    """删除会话（两级：首次归档可恢复；--force 直删）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, session_id, "会话不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).delete(session_id=sid, force=force)

    ok = _run(cli_ctx, _impl)
    if ok:
        if cli_ctx.json_output:
            print_result(cli_ctx, {"id": str(sid), "deleted": True})
        else:
            typer.echo(f"✅ 会话已删除: {session_id}")
    else:
        print_error(cli_ctx, "NOT_FOUND", "会话不存在")


@app.command("restore")
def restore_session_cmd(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--id", "-i", help="会话 ID (UUID)"),
) -> None:
    """恢复已归档的会话"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, session_id, "会话不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).restore(session_id=sid)

    restored = _run(cli_ctx, _impl)
    if restored is None:
        print_error(cli_ctx, "NOT_FOUND", "会话不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _session_to_dict(restored))
    else:
        typer.echo(f"✅ 会话已恢复: [{restored.title}]")


# ── 注册 log 子组 ──

app.add_typer(log_app, name="log")
