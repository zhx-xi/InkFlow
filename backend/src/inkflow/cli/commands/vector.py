"""F14 RAG 向量 CLI 命令 — `inkflow vector <action>`.

分层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() + InkFlowHTTPClient
调用内核 REST API（spec §4.2；Issue #169 CLI 恒经 HTTP）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130。

错误码映射（spec §4/§7）：
- HttpApiError：404 → NOT_FOUND、422 → VALIDATION_ERROR、401 → CONFIG_ERROR、
  500 + LLM_ERROR 头 → LLM_ERROR、其余 → INTERNAL_ERROR（spec §5.3；
  RAG/DB 错误在 HTTP 后均折叠为 INTERNAL_ERROR）
- KernelStartupError → KERNEL_ERROR
- 其余异常 → DB_ERROR

reindex 缺席 --type = 全部 5 种实体类型（服务层展开）；--type 可重复指定；
retrieve 结果按 relevance_score 降序输出（spec §4.2）。--type 非法值由
Typer Choice 校验 → 退出码 2；retrieve 缺 --query → 退出码 2（spec §7）。

依据: specs/f14-extraction/spec.md §4.2/§4.3/§7/§9。
"""

from __future__ import annotations

import asyncio
import uuid

import typer
from pydantic import ValidationError

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.domain.ports.vector_store import EntityType
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel
from inkflow.logging import instrument

app = typer.Typer(name="vector", help="RAG 向量索引与检索", no_args_is_help=True)


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


def _reindex_summary(result: dict) -> str:
    """重建索引结果的人类可读表达（spec §4.3）."""
    types_label = "/".join(result["entity_types"])
    return f"✅ 索引完成: {types_label} 共 {result['indexed']} 条"


def _retrieved_label(entity: dict, index: int) -> str:
    """检索结果条目的人类可读表达（spec §4.3）."""
    metadata = entity.get("metadata") or {}
    name = metadata.get("name", entity["entity_id"])
    content = entity.get("content") or ""
    first_line = content.splitlines()[0] if content else ""
    snippet = first_line if len(first_line) <= 50 else f"{first_line[:50]}……"
    return (
        f"  {index}. [{entity['entity_type']}] {name} — {entity['relevance_score']:.2f}\n"
        f"      （{snippet}）"
    )


def _reason_label(reason: str | None) -> str:
    """status reason 码 → 人类可读文案（#276；spec §3.1）."""
    if reason is None or reason == "fresh":
        return ""
    return {
        "unknown": "无索引指纹",
        "model_changed": "模型已变更",
        "chunking_changed": "切片参数已变更",
        "schema_old": "数据版本过旧",
        "no_embedding": "未配置 embedding 模型",
    }.get(reason, "")


def _status_label(data: dict) -> str:
    """vector status 的人类可读表达（#276；spec §3.1）."""
    if data.get("stale") is True:
        return f"⚠️ 索引可能过期（{_reason_label(data.get('reason'))}），向量库与当前配置不一致"
    if data.get("reason") == "no_embedding":
        return "ℹ️ 未配置 embedding 模型"
    model_id = data.get("configured_fp", {}).get("embedding", {}).get("model_id", "")
    return f"✅ 向量库状态: 与当前配置一致（模型: {model_id}）"


# ---------------------------------------------------------------------------
# status  — inkflow vector status --project-id <uuid>
# ---------------------------------------------------------------------------


@app.command("status")
@instrument(caller_type="cli")
def vector_status_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
) -> None:
    """查询向量索引状态（fresh/stale + reason，spec §3.1）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/projects/{pid}/vector/status")

    data = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
    else:
        typer.echo(_status_label(data))


# ---------------------------------------------------------------------------
# reindex  — inkflow vector reindex --project-id <uuid> [--type <type>]...
# ---------------------------------------------------------------------------


@app.command("reindex")
@instrument(caller_type="cli")
def vector_reindex_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    entity_types: list[EntityType] | None = typer.Option(
        None,
        "--type",
        help="实体类型（可重复指定；缺席 = 全部 5 种）",
    ),
) -> None:
    """全量重建项目向量索引（幂等 upsert，spec §5.6）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            status: dict | None = None
            try:
                status = await client.get(f"/projects/{pid}/vector/status")
            except Exception:
                status = None
            # 仅 dict 响应参与 stale 判定; 查询失败/异常形态不阻断（严格 is True）
            if isinstance(status, dict) and status.get("stale") is True:
                typer.echo(
                    f"⚠️ 索引可能过期（{_reason_label(status.get('reason'))}），正在使用当前配置重建"
                )
            return await client.post(
                f"/projects/{pid}/vector/reindex",
                json={"entity_types": ([t.value for t in entity_types] if entity_types else None)},
            )

    result = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, result)
    else:
        typer.echo(_reindex_summary(result))


# ---------------------------------------------------------------------------
# retrieve  — inkflow vector retrieve --project-id <uuid> --query <str>
#             [--type] [--top-k] [--min-score]
# ---------------------------------------------------------------------------


@app.command("retrieve")
@instrument(caller_type="cli")
def vector_retrieve_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    query: str = typer.Option(..., "--query", help="检索查询文本"),
    entity_types: list[EntityType] | None = typer.Option(
        None, "--type", help="限定实体类型（可重复指定）"
    ),
    top_k: int = typer.Option(10, "--top-k", help="返回结果数量上限（默认 10）"),
    min_score: float = typer.Option(0.0, "--min-score", help="最低相关度阈值（0-1，默认 0.0）"),
) -> None:
    """语义检索项目向量库（结果按相关度降序，spec §5.6）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            status: dict | None = None
            try:
                status = await client.get(f"/projects/{pid}/vector/status")
            except Exception:
                status = None
            # 仅 dict 响应参与 stale 判定; 查询失败/异常形态不阻断（严格 is True）
            if isinstance(status, dict) and status.get("stale") is True:
                typer.echo(
                    f"⚠️ 索引可能过期（{_reason_label(status.get('reason'))}），检索结果可能异常"
                )
            return await client.post(
                f"/projects/{pid}/vector/retrieve",
                json={
                    "query": query,
                    "entity_types": ([t.value for t in entity_types] if entity_types else None),
                    "top_k": top_k,
                    "min_score": min_score,
                },
            )

    data = _run(cli_ctx, _impl)
    items = sorted(
        data.get("items", []),
        key=lambda e: e["relevance_score"],
        reverse=True,
    )
    if cli_ctx.json_output:
        print_result(cli_ctx, {"items": items})
        return
    if not items:
        typer.echo("🔍 未找到相关结果")
        return
    typer.echo(f"🔍 检索结果 (query: {query}, top {top_k}):")
    for i, entity in enumerate(items, 1):
        typer.echo(_retrieved_label(entity, i))
