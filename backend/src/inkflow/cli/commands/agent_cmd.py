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

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
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


def _run_ctx(cli_ctx: CliContext, coro_fn):
    """执行内核调用并映射 HTTP 异常 → print_error 信封（供 JSON 断言命令使用）."""
    try:
        return _run_async(coro_fn())
    except HttpApiError as exc:
        code, message = map_http_error(exc.status_code, exc.detail, exc.code)
        print_error(cli_ctx, code, message)
    except KernelStartupError as exc:
        print_error(cli_ctx, "KERNEL_ERROR", f"内核启动失败: {exc}")


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


template_app = typer.Typer(name="template", help="Agent 模板管理", no_args_is_help=True)


@template_app.command("pipelines")
def template_pipelines(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """列出内置管线模板（#251：template 升级为管理组后迁移至此）"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get("/agent/pipelines/templates")

    result = _run(_impl)
    if json_output:
        _print_json(result)
    elif cli_ctx.json_output:
        print_result(cli_ctx, result)
    else:
        if not result["items"]:
            typer.echo("📭 暂无可用的管线模板")
        else:
            typer.echo("内置管线模板:\n")
            for tpl in result["items"]:
                typer.echo(f"  [{tpl['id']}] {tpl['name']}")
                typer.echo(f"      阶段: {' → '.join(tpl['stages'])}")


@template_app.command("list")
def template_list(ctx: typer.Context) -> None:
    """列出 Agent 模板"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get("/agent-templates")

    data = _run_ctx(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
        return
    items = data.get("items") or []
    if not items:
        typer.echo("📭 暂无模板")
        return
    for t in items:
        typer.echo(f"  [{t['id']}] {t['name']}  {'⭐ 默认' if t.get('is_default') else ''}")


@template_app.command("get")
def template_get(
    ctx: typer.Context,
    template_id: str = typer.Option(..., "--id", help="模板 ID"),
) -> None:
    """查看 Agent 模板"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/agent-templates/{template_id}")

    data = _run_ctx(cli_ctx, _impl)
    print_result(cli_ctx, data)


@template_app.command("create")
def template_create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="模板名称"),
    description: str | None = typer.Option(None, "--description"),
    main_model: str | None = typer.Option(None, "--main-model"),
    default_temperature: float | None = typer.Option(None, "--default-temperature"),
    roles_json: str | None = typer.Option(None, "--roles-json", help="roles 四键 JSON"),
    default_words: int | None = typer.Option(None, "--default-words"),
) -> None:
    """创建 Agent 模板"""
    cli_ctx: CliContext = ctx.obj
    body: dict = {"name": name}
    if description is not None:
        body["description"] = description
    if main_model is not None:
        body["main_model"] = main_model
    if default_temperature is not None:
        body["default_temperature"] = default_temperature
    if default_words is not None:
        body["default_words"] = default_words
    if roles_json is not None:
        try:
            body["roles"] = json.loads(roles_json)
        except json.JSONDecodeError:
            print_error(cli_ctx, "VALIDATION_ERROR", f"--roles-json 不是合法 JSON: {roles_json}")
            return

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post("/agent-templates", json=body)

    data = _run_ctx(cli_ctx, _impl)
    print_result(cli_ctx, data)


@template_app.command("update")
def template_update(
    ctx: typer.Context,
    template_id: str = typer.Option(..., "--id", help="模板 ID"),
    name: str | None = typer.Option(None, "--name", help="模板名称"),
    description: str | None = typer.Option(None, "--description"),
    main_model: str | None = typer.Option(None, "--main-model"),
    default_temperature: float | None = typer.Option(None, "--default-temperature"),
    roles_json: str | None = typer.Option(None, "--roles-json", help="roles 四键 JSON"),
    default_words: int | None = typer.Option(None, "--default-words"),
    is_default: bool | None = typer.Option(None, "--is-default"),
) -> None:
    """更新 Agent 模板"""
    cli_ctx: CliContext = ctx.obj
    body: dict = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if main_model is not None:
        body["main_model"] = main_model
    if default_temperature is not None:
        body["default_temperature"] = default_temperature
    if default_words is not None:
        body["default_words"] = default_words
    if is_default is not None:
        body["is_default"] = is_default
    if roles_json is not None:
        try:
            body["roles"] = json.loads(roles_json)
        except json.JSONDecodeError:
            print_error(cli_ctx, "VALIDATION_ERROR", f"--roles-json 不是合法 JSON: {roles_json}")
            return

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch(f"/agent-templates/{template_id}", json=body)

    data = _run_ctx(cli_ctx, _impl)
    print_result(cli_ctx, data)


@template_app.command("delete")
def template_delete(
    ctx: typer.Context,
    template_id: str = typer.Option(..., "--id", help="模板 ID"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
) -> None:
    """删除 Agent 模板"""
    cli_ctx: CliContext = ctx.obj
    if cli_ctx.json_output and not force:
        print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        return
    if not force and not typer.confirm(f"确定删除模板 #{template_id} 吗？"):
        typer.echo("已取消")
        raise typer.Exit()

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.delete(f"/agent-templates/{template_id}")

    _run_ctx(cli_ctx, _impl)
    print_result(cli_ctx, {"deleted": True})


@template_app.command("duplicate")
def template_duplicate(
    ctx: typer.Context,
    template_id: str = typer.Option(..., "--id", help="模板 ID"),
) -> None:
    """复制 Agent 模板"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(f"/agent-templates/{template_id}/duplicate")

    data = _run_ctx(cli_ctx, _impl)
    print_result(cli_ctx, data)


@template_app.command("set-default")
def template_set_default(
    ctx: typer.Context,
    template_id: str = typer.Option(..., "--id", help="模板 ID"),
) -> None:
    """设为默认模板"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch("/agent-templates/default", json={"id": template_id})

    data = _run_ctx(cli_ctx, _impl)
    print_result(cli_ctx, data)


@template_app.command("get-default")
def template_get_default(ctx: typer.Context) -> None:
    """查看默认模板"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get("/agent-templates/default")

    data = _run_ctx(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
        return
    template = data.get("template")
    if template is None:
        typer.echo("📭 未设置默认模板")
        return
    typer.echo(f"⭐ 默认模板: [{template['id']}] {template['name']}")


# ── F26: Agent 只读工具诊断（本地静态枚举，F38 恒 HTTP 的豁免命令） ──

tools_app = typer.Typer(name="tools", help="工具诊断", no_args_is_help=True)
app.add_typer(tools_app)


@tools_app.command("list")
def tools_list_cmd(
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """列出已注册的 Agent 只读工具（本地静态枚举）"""
    try:
        from inkflow.infrastructure.agent.tools import TOOL_REGISTRY
    except Exception as exc:
        typer.echo(f"❌ 工具注册表加载失败: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        _print_json(
            {
                "ok": True,
                "data": {
                    "items": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "input_schema": t.input_schema,
                        }
                        for t in TOOL_REGISTRY
                    ]
                },
            }
        )
    else:
        for t in TOOL_REGISTRY:
            typer.echo(f"{t.name}: {t.description}")


# ── F27: Agent 运行记录查询 + 草稿确认流（拍板 A：复数 runs，REST /agent/runs 命名一致） ──


def _tool_sequence(steps: list[dict]) -> str:
    """steps 中 tool_calls 的 tool_name 去重顺序连接（a → b）."""
    seen: set[str] = set()
    names: list[str] = []
    for step in steps:
        for tool_call in step.get("tool_calls") or []:
            name = tool_call.get("tool_name")
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return " → ".join(names)


def _print_json_envelope(data) -> None:
    """--json 信封输出（F27 契约: {"ok": true, "data": <API 响应原样>}）."""
    json.dump({"ok": True, "data": data}, sys.stdout, ensure_ascii=False, indent=2)
    print()


runs_app = typer.Typer(name="runs", help="Agent 运行记录查询", no_args_is_help=True)
draft_app = typer.Typer(name="draft", help="草稿管理", no_args_is_help=True)
app.add_typer(runs_app)
app.add_typer(draft_app)
app.add_typer(template_app)


@runs_app.command("list")
def runs_list(
    project_id: str = typer.Option(..., "--project-id", help="项目 ID（UUID）"),
    limit: int = typer.Option(20, "--limit", help="条数上限"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """列出项目的 Agent 运行记录（倒序，分页）"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(
                "/agent/runs", params={"project_id": project_id, "limit": limit}
            )

    data = _run(_impl)
    if data is None:
        return
    if json_output:
        _print_json_envelope(data)
        return
    items = data.get("items") or []
    typer.echo(f"共 {data.get('total', len(items))} 条运行记录")
    for run in items:
        typer.echo(
            f"{run['id']}  {run['status']}  {run.get('terminated_by') or '-'}  "
            f"{run.get('token_usage_total')} tokens"
        )


@runs_app.command("show")
def runs_show(
    run_id: str = typer.Argument(..., help="运行记录 ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """查看单次运行决策轨迹"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/agent/runs/{run_id}")

    data = _run(_impl)
    if data is None:
        return
    if json_output:
        _print_json_envelope(data)
        return
    typer.echo(f"运行 {data['id']} (status={data['status']})")
    steps = data.get("steps") or []
    typer.echo(f"步骤: {len(steps)}")
    typer.echo(f"工具: {_tool_sequence(steps)}")
    typer.echo(f"tokens: {data.get('token_usage_total')}")
    typer.echo(f"终止: {data.get('terminated_by') or '-'}")


@draft_app.command("list")
def draft_list(
    project_id: str = typer.Option(..., "--project-id", help="项目 ID（UUID）"),
    status: str | None = typer.Option(None, "--status", help="过滤: draft|confirmed|rejected"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """列出项目的草稿（用户确认入口）"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            params: dict[str, object] = {"project_id": project_id}
            if status:
                params["status"] = status
            return await client.get("/agent/drafts", params=params)

    data = _run(_impl)
    if data is None:
        return
    if json_output:
        _print_json_envelope(data)
        return
    items = data.get("items") or []
    typer.echo(f"共 {data.get('total', len(items))} 条草稿")
    for draft in items:
        typer.echo(f"{draft['id']}  {draft['status']}  {draft.get('summary') or '-'}")


@draft_app.command("confirm")
def draft_confirm(
    draft_id: str = typer.Argument(..., help="草稿 ID"),
    chapter_id: str | None = typer.Option(None, "--chapter-id", help="目标章节 ID（草稿未绑定）"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """确认草稿 → 写入正式章节"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            body: dict[str, object] = {}
            if chapter_id:
                body["chapter_id"] = chapter_id
            return await client.post(f"/agent/drafts/{draft_id}/confirm", json=body)

    data = _run(_impl)
    if data is None:
        return
    if json_output:
        _print_json_envelope(data)
        return
    content = data.get("final_content") or ""
    typer.echo(f"✅ 章节已更新 (status=final, 字数 {len(content)})")


@draft_app.command("reject")
def draft_reject(
    draft_id: str = typer.Argument(..., help="草稿 ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """拒绝草稿（保留记录）"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(f"/agent/drafts/{draft_id}/reject", json={})

    data = _run(_impl)
    if data is None:
        return
    if json_output:
        _print_json_envelope(data)
        return
    typer.echo("✅ 草稿已拒绝（保留记录）")


@draft_app.command("prune-orphans")
def draft_prune_orphans(
    dry_run: bool = typer.Option(False, "--dry-run", help="只统计不删除（预览）"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """清理孤儿草稿（project_id=全零 UUID，#275 缺陷数据）"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post("/agent/drafts/prune-orphans", json={"dry_run": dry_run})

    data = _run(_impl)
    if data is None:
        return
    if json_output:
        _print_json_envelope(data)
        return
    deleted = data.get("deleted", 0)
    suffix = "（dry-run，未实际删除）" if dry_run else ""
    typer.echo(f"✅ 已删除 {deleted} 条孤儿草稿{suffix}")
