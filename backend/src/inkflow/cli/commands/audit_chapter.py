"""F34 章节审计 CLI 命令 — `inkflow audit chapter`（spec §4/§7）。

分层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() +
InkFlowHTTPClient 调用内核 REST API（Issue #169 CLI 恒经 HTTP）。遵循
F7 §5 全局约定：--json 统一信封 {"ok": true, "data": ...} /
{"ok": false, "error": {"code", "message"}}；退出码 0/1/2。

命令形态（spec §4）：
- 触发审计:  inkflow audit chapter <章节> -p <项目> [--include-static]
- 审计+确认:  ... --confirm accept|reject [--note TEXT]
- 查记录:    inkflow audit chapter --history -p <项目>

错误码映射（spec §7）：
- HttpApiError 经 map_http_error：404 → NOT_FOUND、422 → VALIDATION_ERROR、
  其余 → INTERNAL_ERROR；均退出 1
- KernelStartupError → KERNEL_ERROR；其余异常 → DB_ERROR
- 用法错误（--note 无 --confirm / --confirm 非法 / --confirm 与 --history
  互斥 / 无 chapter 且无 --history）→ 退出 2

依据: specs/f34-chapter-audit/spec.md §4/§7/§9。
"""

from __future__ import annotations

import asyncio
import uuid

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
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


def _print_human_report(report: dict) -> None:
    """人类可读审计报告（spec §4）：findings 按 severity 逐条（error 在前）."""
    typer.echo(
        f"📋 章节审计: {report.get('chapter_title', '')} (status: {report.get('status', '')})"
    )
    findings = sorted(
        report.get("findings", []),
        key=lambda f: _SEVERITY_ORDER.get(str(f.get("severity", "info")), 99),
    )
    for finding in findings:
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
    if report.get("degraded"):
        typer.echo("⚠️ 本次审计为降级模式：部分检查项未完整执行")
    typer.echo(f"   摘要: {report.get('summary', '')}（完整报告见 inkflow audit chapter --json）")


def _print_human_confirm(data: dict) -> None:
    """人类可读确认结果（spec §4）：已接受/已拒绝 + confirmed_at 原样透传."""
    label = "已接受" if data.get("status") == "accepted" else "已拒绝"
    typer.echo(f"✅ {label} (confirmed_at: {data.get('confirmed_at', '')})")


def _print_human_history(data: dict) -> None:
    """人类可读审计记录列表（spec §4）：章名/状态/摘要/时间逐条."""
    logs = data.get("logs", [])
    if not logs:
        typer.echo("（暂无审计记录）")
        return
    for log in logs:
        line = (
            f"  {log.get('chapter_title', '')} [{log.get('status', '')}] "
            f"{log.get('severity_summary', '')} {log.get('created_at', '')}"
        )
        if log.get("confirmed_at"):
            line += f" 确认于 {log['confirmed_at']}"
        typer.echo(line)


# ---------------------------------------------------------------------------
# chapter  — inkflow audit chapter <chapter> -p <project> [--confirm|--history]
# ---------------------------------------------------------------------------


@app.command("chapter")
@instrument(caller_type="cli")
def chapter_audit_cmd(
    ctx: typer.Context,
    chapter: str | None = typer.Argument(None, help="章节名称或 ID（--history 模式下可省略）"),
    project: str = typer.Option(..., "--project", "-p", help="项目名称或 ID"),
    include_static: bool = typer.Option(
        True,
        "--include-static/--no-include-static",
        help="包含 F15 静态一致性委托（默认含）",
    ),
    confirm: str | None = typer.Option(None, "--confirm", help="确认动作: accept / reject"),
    note: str = typer.Option("", "--note", "-n", help="确认备注（与 --confirm 搭配使用）"),
    history: bool = typer.Option(False, "--history", help="查询审计记录列表"),
) -> None:
    """触发章节审计 / 确认 / 查询审计记录（spec §4 三种用法）"""
    cli_ctx: CliContext = ctx.obj
    if note and confirm is None:
        typer.echo("⚠️ --note 仅与 --confirm 搭配使用", err=True)
        raise typer.Exit(code=2)
    if confirm is not None and confirm not in {"accept", "reject"}:
        typer.echo(f"⚠️ --confirm 取值必须为 accept 或 reject，收到: {confirm}", err=True)
        raise typer.Exit(code=2)
    if confirm is not None and history:
        typer.echo("⚠️ --confirm 与 --history 不能同时使用", err=True)
        raise typer.Exit(code=2)
    if chapter is None and not history:
        typer.echo("⚠️ 缺少章节（仅 --history 模式可省略章节参数）", err=True)
        raise typer.Exit(code=2)

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
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
            return await client.post(
                f"/projects/{pid}/chapters/{cid}/audit",
                json={"include_static": include_static},
            )

    data = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
    elif history:
        _print_human_history(data)
    elif confirm is not None:
        _print_human_confirm(data)
    else:
        _print_human_report(data)
