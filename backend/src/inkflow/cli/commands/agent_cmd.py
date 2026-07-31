"""Agent CLI commands — `inkflow agent <action>`."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid

import typer

from inkflow.core.database import async_session_factory, create_tables
from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest, RoleOverride
from inkflow.domain.services.agent_service import AgentService, AgentServiceError
from inkflow.infrastructure.agent.langgraph_pipeline import LangGraphAgentPipeline
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

app = typer.Typer(name="agent", help="Agent 管线管理", no_args_is_help=True)


def _run_async(coro):
    return asyncio.run(coro)


def _print_json(data) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    print()


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

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            pipeline_engine = LangGraphAgentPipeline(llm_client=LangChainLLMClient())
            svc = AgentService(pipeline=pipeline_engine, db_session=session)
            request = PipelineExecuteRequest(
                project_id=uuid.UUID(project_id),
                pipeline=pipeline,
                chapter_id=uuid.UUID(chapter_id) if chapter_id else None,
                variables=variables,
                role_overrides=role_overrides if role_overrides else None,
            )
            return await svc.execute(request)

    try:
        result = _run_async(_impl())
    except AgentServiceError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(code=1)

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

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            pipeline_engine = LangGraphAgentPipeline(llm_client=LangChainLLMClient())
            svc = AgentService(pipeline=pipeline_engine, db_session=session)
            return await svc.get_status(run_id)

    result = _run_async(_impl())
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

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            pipeline_engine = LangGraphAgentPipeline(llm_client=LangChainLLMClient())
            svc = AgentService(pipeline=pipeline_engine, db_session=session)
            return svc.list_templates()

    result = _run_async(_impl())
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
