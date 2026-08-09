"""Agent CLI commands — `inkflow agent <action>`.

薄层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() + InkFlowHTTPClient
调用内核 REST API（spec §4；Issue #169 CLI 恒经 HTTP）。
错误映射（F38 §5.3）：HttpApiError 404/422 等 → stderr「❌ {detail}」+ 退出码 1；
KernelStartupError → 「❌ 内核启动失败: ...」+ 退出码 1。
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid

import typer

from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest, RoleOverride
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

app = typer.Typer(name="agent", help="Agent 管线管理", no_args_is_help=True)


def _run_async(coro):
    return asyncio.run(coro)


def _print_json(data) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    print()


def _run(coro_fn):
    """执行内核调用并映射 HTTP 异常 → stderr「❌ {detail}」+ 退出码 1."""
    try:
        return _run_async(coro_fn())
    except HttpApiError as exc:
        _, message = map_http_error(exc.status_code, exc.detail, exc.code)
        typer.echo(f"❌ {message}", err=True)
        raise typer.Exit(code=1) from exc
    except KernelStartupError as exc:
        typer.echo(f"❌ 内核启动失败: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("run")
def run_pipeline(
    project_id: str = typer.Option(..., "--project-id", help="项目 ID（UUID）"),
    chapter_id: str | None = typer.Option(None, "--chapter-id", help="章节 ID"),
    pipeline: str = typer.Option("builtin:write_chapter", "--pipeline", help="管线模板 ID"),
    var: list[str] = typer.Option([], "--var", help="Prompt 变量 key=value（可重复）"),
    override: list[str] = typer.Option(
        [], "--override", help="角色覆盖 role.field=value（可重复）"
    ),
    watch: bool = typer.Option(False, "--watch", help="阻塞轮询直到完成"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """执行 Agent 管线"""
    # 解析 --var key=value
    variables = {}
    for v in var:
        if "=" in v:
            k, val = v.split("=", 1)
            variables[k] = val

    # 解析 --override role.field=value
    role_overrides: dict[str, RoleOverride] = {}
    for o in override:
        # 格式: writer.temperature=0.9
        try:
            role_field, val = o.split("=", 1)
            role_id, field = role_field.split(".", 1)
            if role_id not in role_overrides:
                role_overrides[role_id] = RoleOverride()
            if field == "temperature":
                role_overrides[role_id].temperature = float(val)
            elif field == "model":
                role_overrides[role_id].model = val
            elif field == "prompt":
                role_overrides[role_id].prompt = val
        except (ValueError, KeyError):
            typer.echo(f"⚠️ 忽略无效覆盖: {o}", err=True)

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            request = PipelineExecuteRequest(
                project_id=uuid.UUID(project_id),
                pipeline=pipeline,
                chapter_id=uuid.UUID(chapter_id) if chapter_id else None,
                variables=variables,
                role_overrides=role_overrides if role_overrides else None,
            )
            return await client.post(
                "/agent/pipelines/execute",
                json=request.model_dump(mode="json", exclude_none=True),
            )

    result = _run(_impl)

    if json_output:
        _print_json(result)
    else:
        typer.echo(f"🚀 管线启动: {result['pipeline']}")
        typer.echo(f"  执行 ID: {result['execution_id']}")
        typer.echo(f"  状态: {result['status']}")
        if watch:
            typer.echo("  (--watch 功能将在 Phase 2 完善)")


@app.command("status")
def check_status(
    run_id: str = typer.Option(..., "--run-id", help="执行 ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """查看管线执行状态"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/agent/pipelines/executions/{run_id}")

    result = _run(_impl)
    if result is None:
        typer.echo("❌ 执行记录不存在", err=True)
        raise typer.Exit(code=1)
    if json_output:
        _print_json(result)
    else:
        typer.echo(f"执行 ID: {result['execution_id']}")
        typer.echo(f"管线: {result['pipeline']}")
        typer.echo(f"状态: {result['status']}")
        typer.echo(f"耗时: {result['total_duration_ms']}ms")
        if result["error"]:
            typer.echo(f"错误: {result['error']}")


@app.command("validate")
def validate_pipeline_config(
    file: str = typer.Option(..., "--file", "-f", help="管线 YAML 文件路径"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """校验管线配置文件"""
    # Phase 1: 仅打印提示，Phase 2 实现完整 YAML 解析
    typer.echo("⚠️ YAML 管线校验将在 Phase 2 实现")
    typer.echo(f"   文件: {file}")


@app.command("template")
def template_list(
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """列出内置管线模板"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get("/agent/pipelines/templates")

    result = _run(_impl)
    if json_output:
        _print_json(result)
    else:
        if not result["items"]:
            typer.echo("📭 暂无可用的管线模板")
        else:
            typer.echo("内置管线模板:\n")
            for tpl in result["items"]:
                typer.echo(f"  [{tpl['id']}] {tpl['name']}")
                typer.echo(f"      阶段: {' → '.join(tpl['stages'])}")
