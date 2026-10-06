"""F34 章节审计 CLI 命令 — `inkflow audit chapter`（spec §4/§7）。

分层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() +
InkFlowHTTPClient 调用内核 REST API（Issue #169 CLI 恒经 HTTP）。遵循
F7 §5 全局约定：--json 统一信封 {"ok": true, "data": ...} /
{"ok": false, "error": {"code", "message"}}；退出码 0/1/2。

命令形态（spec §4）：
- 触发审计:  inkflow audit chapter <章节> -p <项目> [--include-static] [--wait|--no-wait]
             （#1425 异步：POST 只受理 202 {log_id, status}；默认 --wait 轮询至终态后
             取回记录明细并打印报告——人类输出与同步版一致；--no-wait 立即返回 log_id）
- 审计+确认:  ... --confirm accept|reject [--note TEXT]
- 查记录:    inkflow audit chapter --history -p <项目>
- 查明细:    inkflow audit chapter --log <审计记录 ID>（#1420，可省略 -p）

错误码映射（spec §7）：
- HttpApiError 经 map_http_error：404 → NOT_FOUND、422 → VALIDATION_ERROR、
  其余 → INTERNAL_ERROR；均退出 1
- 后台任务失败（run_status=failed）→ INTERNAL_ERROR + 退出 1（#1425）
- 轮询超总预算 → TIMEOUT + 退出 1（#1425）
- KernelStartupError → KERNEL_ERROR；其余异常 → DB_ERROR
- 用法错误（--note 无 --confirm / --confirm 非法 / --confirm 与 --history
  互斥 / 无 chapter 且无 --history）→ 退出 2

依据: specs/f34-chapter-audit/spec.md §4/§7/§9。
"""

from __future__ import annotations

import asyncio
import time
import uuid

import typer

from inkflow.cli._time import format_local
from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.infrastructure.http import (
    LLM_TASK_TIMEOUT,
    HttpApiError,
    InkFlowHTTPClient,
    map_http_error,
)
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel
from inkflow.logging import instrument

app = typer.Typer(
    name="chapter",
    help="章节审计（字数/人设/设定/静态一致性）",
    no_args_is_help=True,
)


@app.callback()
def _chapter_callback() -> None:
    """chapter 组回调——保持命令组形态（Typer 单命令提升规避，F15 先例）."""


# 名称解析分页循环页大小（spec §4 章节名 → id；F15 `_load_all` 同款模式）.
_PAGE_SIZE = 50

# #1425 异步语义：--wait 轮询节奏与总预算（spec §4 v1.5）.
_POLL_INTERVAL = 1.0
"""轮询间隔秒（测试可 monkeypatch 归零）."""

_POLL_TOTAL_TIMEOUT = 900.0
"""轮询总预算秒（超时 → 退出 1 + `--log <id>` 恢复指引）."""

# 严重级别打印排序序（spec §6: error < warning < info）.
_SEVERITY_ORDER: dict[str, int] = {
    "error": 0,
    "warning": 1,
    "info": 2,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_async(coro):
    """同步运行协程（CLI 命令内 asyncio.run）."""
    return asyncio.run(coro)


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
    except Exception as e:
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


def _try_uuid(value: str) -> uuid.UUID | None:
    """尝试将字符串解析为 UUID；失败返回 None（名称解析走列表匹配）."""
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def _resolve_project_id(
    client: InkFlowHTTPClient, cli_ctx: CliContext, project: str
) -> uuid.UUID:
    """项目名称/ID → 项目 UUID（UUID 直传；名称 GET /projects 匹配 name）."""
    parsed = _try_uuid(project)
    if parsed is not None:
        return parsed
    data = await client.get("/projects")
    for item in data.get("items", []):
        if item.get("name") == project:
            return uuid.UUID(item["id"])
    print_error(cli_ctx, "NOT_FOUND", f"项目不存在: {project}")
    raise typer.Exit(1) from None  # print_error 已退出，此行不可达（静态分析用）


async def _load_all_chapters(client: InkFlowHTTPClient, pid: uuid.UUID) -> list[dict]:
    """分页循环拉取项目全部章节（limit=50 循环直到不足一页，F15 同款）."""
    items: list[dict] = []
    offset = 0
    while True:
        data = await client.get(
            f"/projects/{pid}/chapters",
            params={"offset": offset, "limit": _PAGE_SIZE},
        )
        page = data.get("items", [])
        items.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return items


async def _resolve_chapter_id(
    client: InkFlowHTTPClient,
    cli_ctx: CliContext,
    pid: uuid.UUID,
    chapter: str,
) -> uuid.UUID:
    """章节名称/ID → 章节 UUID（UUID 直传；名称分页匹配 title）."""
    parsed = _try_uuid(chapter)
    if parsed is not None:
        return parsed
    items = await _load_all_chapters(client, pid)
    for item in items:
        if item.get("title") == chapter:
            return uuid.UUID(item["id"])
    print_error(cli_ctx, "NOT_FOUND", f"章节不存在: {chapter}")
    raise typer.Exit(1) from None  # print_error 已退出，此行不可达（静态分析用）


def _print_findings(findings: list[dict]) -> None:
    """逐条打印 findings（severity 排序：error < warning < info）."""
    for finding in sorted(
        findings,
        key=lambda f: _SEVERITY_ORDER.get(str(f.get("severity", "info")), 99),
    ):
        severity = finding.get("severity", "info")
        check_type = finding.get("check_type", "")
        message = finding.get("message", "")
        typer.echo(f"  [{severity}] {check_type}: {message}")
        if finding.get("suggestion"):
            typer.echo(f"    建议: {finding['suggestion']}")
        if finding.get("ref_entity_name"):
            typer.echo(f"    关联: {finding['ref_entity_name']}")
        if finding.get("context"):
            typer.echo(f"    上下文: {finding['context']}")


def _print_human_report(report: dict) -> None:
    """人类可读审计报告（spec §4）：findings 按 severity 逐条（error 在前）."""
    typer.echo(
        f"📋 章节审计: {report.get('chapter_title', '')} (status: {report.get('status', '')})"
    )
    _print_findings(list(report.get("findings", [])))
    if report.get("degraded"):
        typer.echo("⚠️ 本次审计为降级模式：部分检查项未完整执行")
    typer.echo(f"   摘要: {report.get('summary', '')}（完整报告见 inkflow audit chapter --json）")


def _print_human_detail(data: dict) -> None:
    """人类可读审计明细（#1420）：记录元信息 + findings 逐条（error 在前）."""
    typer.echo(f"📋 审计记录 {data.get('id', '')}（{data.get('chapter_title', '')}）")
    typer.echo(f"   状态: {data.get('status', '')}  摘要: {data.get('severity_summary', '')}")
    typer.echo(f"   时间: {format_local(data.get('created_at'))}")
    _print_findings(list(data.get("findings", [])))
    if data.get("degraded"):
        typer.echo("⚠️ 本次审计为降级模式：部分检查项未完整执行")


def _print_human_confirm(data: dict) -> None:
    """人类可读确认结果（spec §4）：已接受/已拒绝 + 确认时间显示本地时区."""
    label = "已接受" if data.get("status") == "accepted" else "已拒绝"
    typer.echo(f"✅ {label} (confirmed_at: {format_local(data.get('confirmed_at'))})")


def _print_human_history(data: dict) -> None:
    """人类可读审计记录列表（spec §4）：章名/确认态/执行态/摘要/时间逐条.

    #1425：增补执行态 `run_status`（running/completed/failed）——「哪条对应哪次尝试」
    的可判面（失败记录另附 error 摘要）。
    """
    logs = data.get("logs", [])
    if not logs:
        typer.echo("（暂无审计记录）")
        return
    for log in logs:
        line = (
            f"  {log.get('chapter_title', '')} [{log.get('status', '')}] "
            f"{format_local(log.get('created_at'))} "
            f"执行: {log.get('run_status', 'completed')} "
            f"{log.get('severity_summary', '')}"
        )
        if log.get("error"):
            line += f" 错误: {log['error']}"
        if log.get("confirmed_at"):
            line += f" 确认于 {format_local(log['confirmed_at'])}"
        typer.echo(line)


def _print_human_submitted(data: dict) -> None:
    """人类可读受理凭证（#1425 --no-wait）：log_id + 状态 + 查询指引."""
    log_id = data.get("log_id", "")
    typer.echo(f"🚀 已受理章节审计任务: {log_id} (status: {data.get('status', '')})")
    typer.echo(f"   查询结果: inkflow audit chapter --log {log_id}")


async def _poll_until_done(client: InkFlowHTTPClient, cli_ctx: CliContext, log_id: str) -> dict:
    """轮询任务状态至终态（#1425 `--wait`）——返回终态 AuditRunInfo.

    running 继续；completed/failed 返回；超总预算 → TIMEOUT 错误信封 + 退出 1
    （附 `--log <id>` 恢复指引，spec §4 v1.5）。
    """
    deadline = time.monotonic() + _POLL_TOTAL_TIMEOUT
    while True:
        info: dict = await client.get(f"/audit-logs/{log_id}/status")
        if info.get("run_status") != "running":
            return info
        if time.monotonic() >= deadline:
            print_error(
                cli_ctx,
                "TIMEOUT",
                f"审计任务超时未完成（log_id: {log_id}）——"
                f"可用 inkflow audit chapter --log {log_id} 稍后查询结果",
            )
            raise typer.Exit(1)
        await asyncio.sleep(_POLL_INTERVAL)


# ---------------------------------------------------------------------------
# chapter  — inkflow audit chapter <chapter> -p <project> [--confirm|--history]
# ---------------------------------------------------------------------------


@app.command("chapter")
@instrument(caller_type="cli")
def chapter_audit_cmd(
    ctx: typer.Context,
    chapter: str | None = typer.Argument(None, help="章节名称或 ID（--history 模式下可省略）"),
    project: str | None = typer.Option(
        None, "--project", "-p", help="项目名称或 ID（--log 模式可省略）"
    ),
    include_static: bool = typer.Option(
        True,
        "--include-static/--no-include-static",
        help="包含 F15 静态一致性委托（默认含）",
    ),
    wait: bool = typer.Option(
        True,
        "--wait/--no-wait",
        help="触发审计时等待完成（默认等待；--no-wait 立即返回 log_id）",
    ),
    confirm: str | None = typer.Option(None, "--confirm", help="确认动作: accept / reject"),
    note: str = typer.Option("", "--note", "-n", help="确认备注（与 --confirm 搭配使用）"),
    history: bool = typer.Option(False, "--history", help="查询审计记录列表"),
    log: str | None = typer.Option(None, "--log", help="按审计记录 ID 取回明细（含 findings）"),
) -> None:
    """触发章节审计 / 确认 / 查询审计记录 / 按记录 ID 取明细（spec §4 四种用法）"""
    cli_ctx: CliContext = ctx.obj
    if note and confirm is None:
        typer.echo("⚠️ --note 仅与 --confirm 搭配使用", err=True)
        raise typer.Exit(code=2)
    if confirm is not None and confirm not in {"accept", "reject"}:
        typer.echo(f"⚠️ --confirm 取值必须为 accept 或 reject，收到: {confirm}", err=True)
        raise typer.Exit(code=2)
    if log is not None and (chapter is not None or confirm is not None or history):
        typer.echo("⚠️ --log 不能与章节 / --confirm / --history 同时使用", err=True)
        raise typer.Exit(code=2)
    if confirm is not None and history:
        typer.echo("⚠️ --confirm 与 --history 不能同时使用", err=True)
        raise typer.Exit(code=2)
    if log is None and project is None:
        typer.echo("⚠️ 缺少项目（--project；仅 --log 模式可省略）", err=True)
        raise typer.Exit(code=2)
    if chapter is None and not history and log is None:
        typer.echo("⚠️ 缺少章节（仅 --history 模式可省略章节参数）", err=True)
        raise typer.Exit(code=2)

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            if log is not None:
                return await client.get(f"/audit-logs/{log}")
            assert project is not None  # 上方校验已保证非 --log 模式必有项目
            pid = await _resolve_project_id(client, cli_ctx, project)
            if history:
                return await client.get(f"/projects/{pid}/audit-logs")
            assert chapter is not None  # 上方校验已保证非 --history 必有章节
            cid = await _resolve_chapter_id(client, cli_ctx, pid, chapter)
            if confirm is not None:
                return await client.post(
                    f"/projects/{pid}/chapters/{cid}/audit/confirm",
                    json={"action": confirm, "note": note},
                )
            # #1425 异步语义：POST 只受理（202 {log_id, status}）。
            submitted = await client.post(
                f"/projects/{pid}/chapters/{cid}/audit",
                json={"include_static": include_static},
                timeout=LLM_TASK_TIMEOUT,
            )
            if not wait:
                return submitted
            log_id = submitted.get("log_id")
            if not log_id:
                # 防御：旧内核（同步语义）直接返回报告 → 原样透出
                return submitted
            info = await _poll_until_done(client, cli_ctx, log_id)
            if info.get("run_status") == "failed":
                print_error(
                    cli_ctx,
                    "INTERNAL_ERROR",
                    f"审计任务失败（log_id: {log_id}）: {info.get('error', '')}",
                )
                raise typer.Exit(1) from None  # print_error 已退出（静态分析用）
            return await client.get(f"/audit-logs/{log_id}")

    data = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
    elif log is not None:
        _print_human_detail(data)
    elif history:
        _print_human_history(data)
    elif confirm is not None:
        _print_human_confirm(data)
    elif not wait:
        _print_human_submitted(data)
    else:
        _print_human_report(data)
