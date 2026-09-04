"""F48 知识图谱 CLI 命令 — `inkflow knowledge <action>`.

薄层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() +
InkFlowHTTPClient 调内核 REST API（spec §4；Issue #169 CLI 恒经 HTTP）。
遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2；删除类命令二次确认 + --force；
--json + 无 --force 的删除 → VALIDATION_ERROR。

错误码映射（spec §4/§7）:
- HttpApiError：404 → NOT_FOUND、422 → VALIDATION_ERROR、
  401 → CONFIG_ERROR、500 + LLM_ERROR 头 → LLM_ERROR、其余 → INTERNAL_ERROR
- KernelStartupError → KERNEL_ERROR
- pydantic ValidationError → VALIDATION_ERROR
- 其余异常 → DB_ERROR

依据: specs/f48-knowledge-graph/spec.md §4。
"""

from __future__ import annotations

import asyncio
import uuid

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

app = typer.Typer(name="knowledge", help="知识图谱管理", no_args_is_help=True)
relation_app = typer.Typer(name="relation", help="关系管理", no_args_is_help=True)
app.add_typer(relation_app, name="relation")


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


# ---------------------------------------------------------------------------
# graph — inkflow knowledge graph <project_id> [--json]
# ---------------------------------------------------------------------------


@app.command("graph")
@instrument(caller_type="cli")
def graph_cmd(
    ctx: typer.Context,
    project_id: str = typer.Argument(..., help="项目 ID (UUID)"),
) -> None:
    """查询项目知识图谱聚合（nodes + edges）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/projects/{pid}/knowledge-graph")

    data = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
        return
    name_by_id = {node["id"]: node["name"] for node in data.get("nodes", [])}
    for edge in data.get("edges", []):
        source = name_by_id.get(edge["source"], edge["source"])
        target = name_by_id.get(edge["target"], edge["target"])
        typer.echo(f"{source} --{edge['label']}--> {target}")


# ---------------------------------------------------------------------------
# extract — inkflow knowledge extract --project <uuid> [--method rule|ai|both]
# ---------------------------------------------------------------------------


@app.command("extract")
@instrument(caller_type="cli")
def extract_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project", help="项目 ID (UUID)"),
    method: str | None = typer.Option(
        None, "--method", help="提取方式 rule/ai/both（缺省跟随设置）"
    ),
) -> None:
    """手动触发知识图谱关系提取"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        body: dict[str, str] = {"project_id": str(pid)}
        if method is not None:
            body["method"] = method
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                "/knowledge/extract", json=body, timeout=LLM_TASK_TIMEOUT
            )

    data = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
    else:
        typer.echo(f"✅ 提取完成: 新增 {data.get('created', 0)} 条关系（{data.get('status', '')}）")


# ---------------------------------------------------------------------------
# relation list — inkflow knowledge relation list <project_id> [--source-type]
#                 [--target-type] [--relation-type]
# ---------------------------------------------------------------------------


@relation_app.command("list")
@instrument(caller_type="cli")
def list_relations_cmd(
    ctx: typer.Context,
    project_id: str = typer.Argument(..., help="项目 ID (UUID)"),
    source_type: str | None = typer.Option(None, "--source-type", help="起点实体类型过滤"),
    target_type: str | None = typer.Option(None, "--target-type", help="终点实体类型过滤"),
    relation_type: str | None = typer.Option(None, "--relation-type", help="关系类型过滤"),
) -> None:
    """列出项目内图谱关系（可过滤）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        params: dict[str, str] = {}
        if source_type is not None:
            params["source_type"] = source_type
        if target_type is not None:
            params["target_type"] = target_type
        if relation_type is not None:
            params["relation_type"] = relation_type
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(
                f"/projects/{pid}/knowledge-relations",
                params=params or None,
            )

    data = _run(cli_ctx, _impl)
    items = data.get("items", [])
    total = data.get("total", 0)
    print_result(cli_ctx, {"items": items, "total": total})


# ---------------------------------------------------------------------------
# relation add — inkflow knowledge relation add <project_id> --source-type ...
# ---------------------------------------------------------------------------


@relation_app.command("add")
@instrument(caller_type="cli")
def add_relation_cmd(
    ctx: typer.Context,
    project_id: str = typer.Argument(..., help="项目 ID (UUID)"),
    source_type: str = typer.Option(..., "--source-type", help="起点实体类型"),
    source_id: str = typer.Option(..., "--source-id", help="起点实体 ID (UUID)"),
    target_type: str = typer.Option(..., "--target-type", help="终点实体类型"),
    target_id: str = typer.Option(..., "--target-id", help="终点实体 ID (UUID)"),
    relation_type: str = typer.Option(..., "--relation-type", help="关系类型"),
    description: str | None = typer.Option(None, "--description", help="关系说明"),
) -> None:
    """创建图谱关系（六元组 + 可选描述）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        body: dict[str, str] = {
            "source_type": source_type,
            "source_id": source_id,
            "target_type": target_type,
            "target_id": target_id,
            "relation_type": relation_type,
        }
        if description is not None:
            body["description"] = description
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                f"/projects/{pid}/knowledge-relations",
                json=body,
            )

    relation = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, relation)
    else:
        typer.echo(f"✅ 关系已创建: [{relation['relation_type']}]")


# ---------------------------------------------------------------------------
# relation get — inkflow knowledge relation get <relation_id>
# ---------------------------------------------------------------------------


@relation_app.command("get")
@instrument(caller_type="cli")
def get_relation_cmd(
    ctx: typer.Context,
    relation_id: str = typer.Argument(..., help="关系 ID (UUID)"),
) -> None:
    """查看图谱关系详情"""
    cli_ctx: CliContext = ctx.obj
    rid = _parse_uuid(cli_ctx, relation_id, "关系不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/knowledge-relations/{rid}")

    relation = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, relation)
    else:
        typer.echo(f"✅ 关系: [{relation['relation_type']}]")


# ---------------------------------------------------------------------------
# relation update — inkflow knowledge relation update <relation_id> [--...]
# ---------------------------------------------------------------------------


@relation_app.command("update")
@instrument(caller_type="cli")
def update_relation_cmd(
    ctx: typer.Context,
    relation_id: str = typer.Argument(..., help="关系 ID (UUID)"),
    source_type: str | None = typer.Option(None, "--source-type", help="新起点实体类型"),
    source_id: str | None = typer.Option(None, "--source-id", help="新起点实体 ID (UUID)"),
    target_type: str | None = typer.Option(None, "--target-type", help="新终点实体类型"),
    target_id: str | None = typer.Option(None, "--target-id", help="新终点实体 ID (UUID)"),
    relation_type: str | None = typer.Option(None, "--relation-type", help="新关系类型"),
    description: str | None = typer.Option(None, "--description", help="新关系说明"),
) -> None:
    """更新图谱关系（仅更新传入字段）"""
    cli_ctx: CliContext = ctx.obj
    rid = _parse_uuid(cli_ctx, relation_id, "关系不存在")

    async def _impl() -> dict:
        body: dict[str, str] = {}
        if source_type is not None:
            body["source_type"] = source_type
        if source_id is not None:
            body["source_id"] = source_id
        if target_type is not None:
            body["target_type"] = target_type
        if target_id is not None:
            body["target_id"] = target_id
        if relation_type is not None:
            body["relation_type"] = relation_type
        if description is not None:
            body["description"] = description
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch(f"/knowledge-relations/{rid}", json=body)

    relation = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, relation)
    else:
        typer.echo(f"✅ 关系已更新: [{relation['relation_type']}]")


# ---------------------------------------------------------------------------
# relation delete — inkflow knowledge relation delete <relation_id> [--force]
# ---------------------------------------------------------------------------


@relation_app.command("delete")
@instrument(caller_type="cli")
def delete_relation_cmd(
    ctx: typer.Context,
    relation_id: str = typer.Argument(..., help="关系 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
) -> None:
    """删除图谱关系（真删，不可恢复）"""
    cli_ctx: CliContext = ctx.obj
    rid = _parse_uuid(cli_ctx, relation_id, "关系不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        if not typer.confirm(f"确定要删除关系 #{relation_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl() -> None:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            await client.delete(f"/knowledge-relations/{rid}")

    _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, {"deleted": True, "id": relation_id})
    else:
        typer.echo(f"✅ 关系已删除: {relation_id}")
