"""Book CLI 命令 - `inkflow book <action>`.

薄层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() +
InkFlowHTTPClient 调用内核 REST API（spec 4，F38 恒经 HTTP）。
错误映射（F38 5.3）：HttpApiError 404/422 等 -> stderr"✗ {detail}"、退出码 1；
KernelStartupError -> "✗ 内核启动失败: ..."、退出码 1。
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

app = typer.Typer(name="book", help="书级编排管理", no_args_is_help=True)
plan_app = typer.Typer(name="plan", help="访谈式 Planner", no_args_is_help=True)
app.add_typer(plan_app)


def _run_async(coro):
    return asyncio.run(coro)


def _run_ctx(cli_ctx: CliContext, coro_fn):
    """执行内核调用并映射 HTTP 异常 -> print_error 信封（退出码 1）。"""
    try:
        return _run_async(coro_fn())
    except HttpApiError as exc:
        code, message = map_http_error(exc.status_code, exc.detail, exc.code)
        print_error(cli_ctx, code, message)
    except KernelStartupError as exc:
        print_error(cli_ctx, "KERNEL_ERROR", f"内核启动失败: {exc}")


def _print_json(data) -> None:
    """--json 信封输出：{"ok": true, "data": <API 响应>}。"""
    json.dump({"ok": True, "data": data}, sys.stdout, ensure_ascii=False, indent=2)
    print()


def _human_or_json(
    cli_ctx: CliContext,
    json_output: bool,
    data,
    human_render: Callable[[dict], None],
) -> None:
    """命令级 --json 或全局 --json 输出信封 JSON；否则走人类可读渲染。"""
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
    elif json_output:
        _print_json(data)
    else:
        human_render(data)


def _render_questions(data: dict) -> None:
    """打印每轮问题（- {text}）。"""
    for question in data.get("questions") or []:
        typer.echo(f"- {question.get('text', '')}")


def _parse_limits(raw: str | None) -> dict[str, int] | None:
    """解析 --limits 逗号分隔 k=v 串 → dict（"max_chapters=5,max_tokens=200000" → {...}）。"""
    if not raw:
        return None
    result: dict[str, int] = {}
    for item in raw.split(","):
        if "=" not in item:
            continue
        key, _, value = item.partition("=")
        key = key.strip()
        if key:
            result[key] = int(value.strip())
    return result


@plan_app.command("start")
def plan_start(
    ctx: typer.Context,
    one_liner: str = typer.Argument(..., help="一句话故事构思"),
    project_id: str = typer.Option(..., "--project", help="项目 ID（UUID）"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """启动访谈会话（POST /planner -> 打印第一轮问题）。"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                "/agent/books/planner",
                json={"project_id": project_id, "one_liner": one_liner},
            )

    data = _run_ctx(cli_ctx, _impl)
    _human_or_json(cli_ctx, json_output, data, _render_questions)


@plan_app.command("respond")
def plan_respond(
    ctx: typer.Context,
    session_id: str = typer.Argument(..., help="访谈会话 ID"),
    answer: str = typer.Argument(..., help="回答文本"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """回复当前问题（POST /planner/{session}/respond -> 下一轮问题或完成）。"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                f"/agent/books/planner/{session_id}/respond",
                json={"answers": {"answer": answer}, "auto": False},
            )

    data = _run_ctx(cli_ctx, _impl)

    def _render(data: dict) -> None:
        if data.get("completed"):
            typer.echo("✓ 访谈完成。")
            writing_plan = data.get("writing_plan") or {}
            typer.echo(
                f"writing_plan: {writing_plan.get('id', '-')} "
                f"(status={writing_plan.get('status', '-')})"
            )
            return
        _render_questions(data)

    _human_or_json(cli_ctx, json_output, data, _render)


@plan_app.command("auto")
def plan_auto(
    ctx: typer.Context,
    one_liner: str = typer.Argument(..., help="一句话故事构思"),
    project_id: str = typer.Option(..., "--project", help="项目 ID（UUID）"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """全部你决定：跳过访谈直接自动生成（POST /planner + respond auto=true）。"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            started = await client.post(
                "/agent/books/planner",
                json={"project_id": project_id, "one_liner": one_liner},
            )
            session_id = started["session_id"]
            return await client.post(
                f"/agent/books/planner/{session_id}/respond",
                json={"answers": {}, "auto": True},
            )

    data = _run_ctx(cli_ctx, _impl)

    def _render(data: dict) -> None:
        writing_plan = data.get("writing_plan") or {}
        status = writing_plan.get("status", data.get("status", "?"))
        typer.echo(f"WritingPlan 已生成 (status={status})")

    _human_or_json(cli_ctx, json_output, data, _render)


@plan_app.command("show")
def plan_show(
    ctx: typer.Context,
    session_id: str = typer.Argument(..., help="访谈会话 ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """查看访谈会话状态（GET /planner/{session}）。"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/agent/books/planner/{session_id}")

    data = _run_ctx(cli_ctx, _impl)

    def _render(data: dict) -> None:
        questions = data.get("asked_questions") or []
        answers = data.get("answers") or {}
        typer.echo(f"会话: {data.get('id')}")
        typer.echo(f"项目: {data.get('project_id')}")
        typer.echo(f"状态: {data.get('status')}")
        typer.echo(f"一句话: {data.get('one_liner')}")
        typer.echo(f"轮次: {data.get('round')}")
        typer.echo(f"已问问题: {len(questions)}")
        typer.echo(f"回答数: {len(answers)}")
        for question in questions:
            typer.echo(f"- {question.get('text', '')}")
        confirmed_items = data.get("confirmed_items") or []
        for item in confirmed_items:
            typer.echo(f"{item.get('key', '')}: {item.get('value', '')}")

    _human_or_json(cli_ctx, json_output, data, _render)


@plan_app.command("confirm")
def plan_confirm(
    ctx: typer.Context,
    session_id: str = typer.Argument(..., help="访谈会话 ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """末尾总体确认通过（v1.2 #475：confirming=true 后列出全部确定项再确认）。"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                f"/agent/books/planner/{session_id}/respond",
                json={"answers": {}, "confirm": True},
            )

    data = _run_ctx(cli_ctx, _impl)

    def _render(data: dict) -> None:
        if data.get("completed"):
            typer.echo("✓ 访谈完成。")
            writing_plan = data.get("writing_plan") or {}
            typer.echo(
                f"writing_plan: {writing_plan.get('id', '-')} "
                f"(status={writing_plan.get('status', '-')})"
            )
            return
        _render_questions(data)

    _human_or_json(cli_ctx, json_output, data, _render)


@plan_app.command("run")
def plan_run(
    ctx: typer.Context,
    plan_id: str = typer.Argument(..., help="WritingPlan ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """委托一键写作（POST /runs -> run_id/status）。"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                "/agent/books/runs",
                json={"writing_plan_id": plan_id},
            )

    data = _run_ctx(cli_ctx, _impl)

    def _render(data: dict) -> None:
        typer.echo(f"✓ 已启动 run_id={data.get('run_id')}")

    _human_or_json(cli_ctx, json_output, data, _render)


@app.command("run")
def book_run(
    ctx: typer.Context,
    plan_id: str = typer.Argument(..., help="WritingPlan ID"),
    limits: str | None = typer.Option(
        None,
        "--limits",
        help="上限 k=v 逗号分隔，如 max_chapters=5,max_tokens=200000",
    ),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """启动书级运行（POST /runs -> run_id/status；阶段 2 顺序派发）。"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        body: dict = {"writing_plan_id": plan_id}
        parsed = _parse_limits(limits)
        if parsed:
            body["limits"] = parsed
        async with client:
            return await client.post("/agent/books/runs", json=body)

    data = _run_ctx(cli_ctx, _impl)

    def _render(data: dict) -> None:
        typer.echo(f"✓ 已启动 run_id={data.get('run_id')}")

    _human_or_json(cli_ctx, json_output, data, _render)


@app.command("status")
def book_status(
    ctx: typer.Context,
    run_id: str = typer.Argument(..., help="书级运行 ID"),
    density: str = typer.Option("dashboard", "--density", help="performance|dashboard|silent"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """查看书级运行状态（GET /runs/{run_id} -> 进度树 + 计数器）。"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/agent/books/runs/{run_id}")

    data = _run_ctx(cli_ctx, _impl)

    def _render(data: dict) -> None:
        typer.echo(f"run_id: {data.get('run_id')}")
        typer.echo(f"status: {data.get('status')}")
        typer.echo("进度:")
        for key, value in (data.get("progress") or {}).items():
            typer.echo(f"  {key}: {value}")
        typer.echo("计数器:")
        for key, value in (data.get("counters") or {}).items():
            typer.echo(f"  {key}: {value}")

    _human_or_json(cli_ctx, json_output, data, _render)


@app.command("confirm")
def book_confirm(
    ctx: typer.Context,
    run_id: str = typer.Argument(..., help="书级运行 ID"),
    approved: bool = typer.Option(False, "--approved", help="确认继续"),
    reject: bool = typer.Option(False, "--reject", help="拒绝/中止"),
    decision: str = typer.Option(
        "", "--decision", help="决策文本（卷级失败时 continue/abort/supervisor）"
    ),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """卷级 HITL 确认（POST /runs/{run_id}/confirm）。"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                f"/agent/books/runs/{run_id}/confirm",
                json={"approved": approved or not reject, "decision": decision},
            )

    data = _run_ctx(cli_ctx, _impl)

    def _render(data: dict) -> None:
        status = data.get("status", "?")
        typer.echo(f"✓ 已确认，继续下一卷（run_id={data.get('run_id')}，status={status}）")

    _human_or_json(cli_ctx, json_output, data, _render)


_REDIRECT_LABELS: dict[str, str] = {
    "skip": "跳过",
    "retry": "重试",
    "mark_failed": "标记失败",
}


@app.command("intervene")
def book_intervene(
    ctx: typer.Context,
    run_id: str = typer.Argument(..., help="书级运行 ID"),
    action: str = typer.Option(..., "--action", help="pause|resume|redirect|edit"),
    target: str | None = typer.Option(None, "--target", help="outline_id（redirect/edit）"),
    to: str | None = typer.Option(None, "--to", help="skip|retry|mark_failed（redirect）"),
    brief: str | None = typer.Option(None, "--brief", help="新章 brief（edit）"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """书级运行干预（POST /runs/{run_id}/intervene，§3.2）。"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        body: dict = {
            "action": action,
            "target": target,
            "to": to,
            "payload": {"brief": brief} if brief else None,
        }
        async with client:
            return await client.post(
                f"/agent/books/runs/{run_id}/intervene",
                json=body,
            )

    data = _run_ctx(cli_ctx, _impl)

    def _render(data: dict) -> None:
        run_id_out = data.get("run_id")
        if action == "pause":
            typer.echo(f"✓ 已暂停 run_id={run_id_out}")
        elif action == "resume":
            typer.echo(f"✓ 已恢复 run_id={run_id_out}")
        elif action == "redirect":
            label = _REDIRECT_LABELS.get(to or "", to or "")
            typer.echo(f"✓ 已{label}章 {target}")
        elif action == "edit":
            diff = data.get("diff") or {}
            typer.echo(f"✓ 已编辑章 {target} brief")
            before = diff.get("before")
            after = diff.get("after")
            if before is not None:
                typer.echo(f"  before: {before}")
            if after is not None:
                typer.echo(f"  after: {after}")

    _human_or_json(cli_ctx, json_output, data, _render)


@app.command("summary")
def book_summary(
    ctx: typer.Context,
    run_id: str = typer.Argument(..., help="书级运行 ID"),
    export: str | None = typer.Option(None, "--export", help="导出摘要 JSON 到文件"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """书级运行回归摘要（GET /runs/{run_id}/summary，§3.3）。"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/agent/books/runs/{run_id}/summary")

    data = _run_ctx(cli_ctx, _impl)

    if export:
        with open(export, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

    def _render(data: dict) -> None:
        typer.echo(f"run_id: {data.get('run_id')}")
        typer.echo(f"status: {data.get('status')}")
        typer.echo("进度:")
        for key, value in (data.get("progress") or {}).items():
            typer.echo(f"  {key}: {value}")
        typer.echo("计数器:")
        for key, value in (data.get("counters") or {}).items():
            typer.echo(f"  {key}: {value}")
        steps = data.get("steps") or []
        typer.echo(f"步骤: {len(steps)}")
        for step in steps:
            typer.echo(f"  [{step.get('index')}] {step.get('outline_id')}: {step.get('status')}")
        next_state = data.get("next") or {}
        typer.echo(f"next: {next_state}")

    _human_or_json(cli_ctx, json_output, data, _render)
