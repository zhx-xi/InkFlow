"""Skill CLI commands — `inkflow skill <action>`（F39 #258 spec §4）.

薄层设计：仅做参数解析/结果格式化，业务经 ensure_kernel() + InkFlowHTTPClient
调用内核 REST API（F38 恒经 HTTP，路径相对 base_url——/skills 不含 /api/v1
前缀，#246 教训）。命名区分：单数 `skill` = F39 Skill 实体域（文件系统
真源 data_dir/skills/，ADR-039 #522）；F19-skills 复数 `skills` = 文件系统
导入域（共用 data_dir/skills/ 目录）。

错误映射（F38 §5.3）：HttpApiError 404/422 等 → NOT_FOUND/VALIDATION_ERROR/
其余 INTERNAL_ERROR；KernelStartupError → KERNEL_ERROR；exit 1。--json
信封由命令级选项驱动（obj.json_output 在本组不可测，根 app invoke 恒 False）。
"""

from __future__ import annotations

import asyncio
import json
import sys

import typer

from inkflow.cli.context import CliContext
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel
from inkflow.logging import instrument

app = typer.Typer(name="skill", help="Skill 管理", no_args_is_help=True)


def _run_async(coro):
    return asyncio.run(coro)


def _print_json(data) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    print()


def _print_json_error(code: str, message: str) -> None:
    """--json 错误信封（命令级选项驱动，obj.json_output 在本组恒 False）."""
    _print_json({"ok": False, "error": {"code": code, "message": message}})


def _run_ctx(cli_ctx: CliContext, coro_fn, *, json_output: bool):
    """执行内核调用并映射错误 → 信封（--json）/ stderr（人类），exit 1."""
    try:
        return _run_async(coro_fn())
    except HttpApiError as exc:
        code, message = map_http_error(exc.status_code, exc.detail, exc.code)
        if json_output:
            _print_json_error(code, message)
        else:
            typer.echo(f"❌ {message}", err=True)
        raise typer.Exit(code=1) from exc
    except KernelStartupError as exc:
        if json_output:
            _print_json_error("KERNEL_ERROR", f"内核启动失败: {exc}")
        else:
            typer.echo(f"❌ 内核启动失败: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("list")
@instrument(caller_type="cli")
def skill_list(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """列出全部 Skill（name + source + 被引用 Agent 数，spec §4）"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get("/skills")

    data = _run_ctx(cli_ctx, _impl, json_output=json_output)
    if data is None:
        return
    if json_output:
        _print_json({"ok": True, "data": data})
        return
    items = data.get("items") or []
    if not items:
        typer.echo("📭 暂无 Skill")
        return
    for skill in items:
        refs = skill.get("agent_ids") or []
        source = skill.get("source") or "-"
        typer.echo(f"[{skill['id']}] {skill['name']}  source={source}  引用 {len(refs)} 个 Agent")
