"""#981 chat 一次性命令 — `inkflow chat <prompt> [--project] ...`（SSE 消费 + AgentRun 回读）.

薄层设计：仅做参数解析/校验与帧消费，业务经 ensure_kernel() + InkFlowHTTPClient
调内核 REST API（Issue #169 CLI 恒经 HTTP）。--agent（默认）端点
/chat/agent/stream（#597 type 键帧表；#615 done 后回读 GET /agent/runs/{run_id}
填充 --json data）；--plain 端点 /chat/stream（legacy 无 type 键帧，--json data
仅 delta 拼接 content）。错误码映射与异常处理照抄 world.py。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import typer
from pydantic import ValidationError

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
    except ValidationError as e:
        messages = "; ".join(str(err.get("msg", "")) for err in e.errors())
        print_error(cli_ctx, "VALIDATION_ERROR", messages or "参数校验失败")
    except Exception as e:
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


async def _consume_agent_stream(
    cli_ctx: CliContext,
    events: AsyncIterator[dict],
    client: InkFlowHTTPClient,
) -> dict[str, Any]:
    """消费 agent SSE 帧流并回读 AgentRun（#597 帧表 + #615 run 回读）.

    成功返回 --json data dict（steps/tool_calls/final_content/token_usage_total）；
    流中 error 终帧返回 {"__llm_error__": <msg>} 标记，由调用方映射 LLM_ERROR。
    """
    run_id: str | None = None
    parts: list[str] = []
    human = not cli_ctx.json_output
    async for ev in events:
        ev_type = ev.get("type")
        if ev_type == "run_started":
            run_id = ev.get("id") or run_id
        elif ev_type == "delta":
            parts.append(str(ev["delta"]))
            if human:
                typer.echo(str(ev["delta"]), nl=False)
        elif ev_type in ("tool_call", "tool_result"):
            if human:
                typer.echo(f"🔧 {ev.get('name', '')}")
        elif ev_type == "interrupt":
            if human:
                typer.echo(f"\n⚠️ 对话中断，需要确认: {ev.get('payload')}")
        elif ev_type == "error":
            return {"__llm_error__": str(ev.get("error", ""))}
        elif ev_type == "done" and ev.get("run_id"):
            run_id = ev["run_id"]
    fallback_content = "".join(parts)
    if run_id is None:
        return {
            "run_id": "",
            "steps": [],
            "tool_calls": [],
            "final_content": fallback_content,
            "token_usage_total": None,
        }
    try:
        run: dict | None = await client.get(f"/agent/runs/{run_id}")
    except HttpApiError:
        run = None
    if run is None:
        data: dict[str, Any] = {
            "run_id": run_id,
            "steps": [],
            "tool_calls": [],
            "final_content": fallback_content,
            "token_usage_total": None,
        }
    else:
        steps = run["steps"]
        tool_calls = [tc for s in steps for tc in (s.get("tool_calls") or [])]
        data = {
            "run_id": run_id,
            "steps": steps,
            "tool_calls": tool_calls,
            "final_content": run["final_content"],
            "token_usage_total": run.get("token_usage_total"),
        }
        if human:
            typer.echo()
            typer.echo(f"步骤: {len(run['steps'])} · tokens: {run.get('token_usage_total')}")
    return data


async def _consume_plain_stream(
    cli_ctx: CliContext,
    events: AsyncIterator[dict],
) -> dict[str, Any]:
    """消费 legacy plain SSE 帧流（无 type 键：delta / done / error）."""
    parts: list[str] = []
    human = not cli_ctx.json_output
    async for ev in events:
        if ev.get("error"):
            return {"__llm_error__": str(ev["error"])}
        delta = ev.get("delta")
        if delta is not None:
            parts.append(str(delta))
            if human:
                typer.echo(str(delta), nl=False)
    return {"content": "".join(parts)}


@instrument(caller_type="cli")
def chat_cmd(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="对话提示词"),
    project: str = typer.Option(..., "--project", help="项目 ID (UUID)"),
    chapter: str | None = typer.Option(None, "--chapter", help="章节 ID (UUID)"),
    conversation: str | None = typer.Option(None, "--conversation", help="会话 ID (UUID)"),
    agent_mode: bool = typer.Option(
        True, "--agent/--plain", help="对话模式：--agent 系统级 Agent（默认）| --plain 普通流式"
    ),
    timeout: float = typer.Option(
        LLM_TASK_TIMEOUT, "--timeout", help="per-request 超时（秒），默认 300"
    ),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """与 AI 对话（--agent: SSE 帧 + AgentRun 回读；--plain: legacy 流式帧）"""
    cli_ctx: CliContext = ctx.obj if isinstance(ctx.obj, CliContext) else CliContext()
    if json_output:
        cli_ctx.json_output = True
    if not prompt.strip():
        print_error(cli_ctx, "VALIDATION_ERROR", "chat 需要非空 prompt")

    async def _impl() -> dict[str, Any]:
        body: dict[str, Any] = {"project_id": project, "prompt": prompt}
        if chapter is not None:
            body["chapter_id"] = chapter
        if conversation is not None:
            body["conversation_id"] = conversation
        path = "/chat/agent/stream" if agent_mode else "/chat/stream"
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            events = client.stream_sse(path, json=body, timeout=timeout)
            if agent_mode:
                return await _consume_agent_stream(cli_ctx, events, client)
            return await _consume_plain_stream(cli_ctx, events)

    result = _run(cli_ctx, _impl)
    if result is None:
        return
    if result.get("__llm_error__") is not None:
        print_error(cli_ctx, "LLM_ERROR", result["__llm_error__"])
    if cli_ctx.json_output:
        print_result(cli_ctx, result)
