"""F22 全文搜索 CLI 命令 — `inkflow search`（F38 恒经 HTTP 轨）.

分层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() + InkFlowHTTPClient
调用内核 REST API（spec §4；Issue #169 CLI 恒经 HTTP，ADR-030/F38）。遵循 F7 §5
全局约定：--json 统一信封 {"ok": true, "data": ...} / {"ok": false,
"error": {"code", "message"}}；退出码 0/1/2。

错误码映射（F38 map_http_error，spec §4）：
- HttpApiError：404 → NOT_FOUND、422 → VALIDATION_ERROR、401 → CONFIG_ERROR、
  500 + X-InkFlow-Error-Code: LLM_ERROR → LLM_ERROR、其余 → INTERNAL_ERROR
- KernelStartupError → KERNEL_ERROR
- pydantic ValidationError → VALIDATION_ERROR
- 其余异常 → DB_ERROR

人类可读输出（spec §4 示例）：每命中一行 `[类型徽标] 项目名 · 标题` + snippet
单独行（`<mark>` → `[ ]` 方括号替换，终端无 HTML 语义）；项目名经 GET
/api/v1/projects 列表映射；--json 时 data = SearchResponse 原样、snippet 保留
`<mark>`（消费端自行渲染）。--rebuild 人类输出重建完成提示。

依据: specs/f22-search/spec.md §4/§9。
"""

from __future__ import annotations

import asyncio
import uuid

import typer
from pydantic import ValidationError

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel
from inkflow.logging import instrument

app = typer.Typer(
    name="search",
    help="全文搜索（FTS5 词法 + AI 语义）",
    no_args_is_help=True,
)


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


async def _resolve_projects(
    cli_ctx: CliContext,
    client: InkFlowHTTPClient,
    values: list[str],
) -> tuple[list[str], dict[str, str]]:
    """--project 列表：UUID 直传；项目名 → GET /api/v1/projects 匹配 name → id（spec §4）."""
    resolved: list[str] = []
    pending_names: list[str] = []
    for value in values:
        try:
            uuid.UUID(value)
        except ValueError:
            pending_names.append(value)
        else:
            resolved.append(value)
    name_map: dict[str, str] = {}
    if not pending_names:
        return resolved, name_map
    data = await client.get("/projects", params={"offset": 0, "limit": 50})
    items = data.get("items", [])
    name_map = {item["id"]: item["name"] for item in items}
    by_name = {item["name"]: item["id"] for item in items}
    for name in pending_names:
        pid = by_name.get(name)
        if pid is None:
            print_error(cli_ctx, "NOT_FOUND", f"项目不存在: {name}")
            raise typer.Exit(1) from None  # print_error 已退出，此行不可达（静态分析用）
        resolved.append(pid)
    return resolved, name_map


async def _fetch_projects(client: InkFlowHTTPClient) -> dict[str, str]:
    """GET /api/v1/projects 列表 → {id: name} 映射（人类输出项目名展示，spec §4）."""
    data = await client.get("/projects", params={"offset": 0, "limit": 50})
    return {item["id"]: item["name"] for item in data.get("items", [])}


def _snippet_human(snippet: str) -> str:
    """snippet 高亮标记：<mark>/</mark> → [ ] 方括号（终端无 HTML 语义，spec §4）."""
    return snippet.replace("<mark>", "[").replace("</mark>", "]")


def _print_human(data: dict, name_map: dict[str, str]) -> None:
    """人类可读命中列表：`[类型徽标] 项目名 · 标题` + snippet 单独行（spec §4 示例）."""
    hits = data.get("hits", [])
    if not hits:
        typer.echo("📭 无结果")
        return
    for hit in hits:
        pid = str(hit.get("project_id", ""))
        project_name = name_map.get(pid, pid)
        typer.echo(f"[{hit['entity_type']}] {project_name} · {hit['title']}")
        typer.echo(f"   {_snippet_human(hit.get('snippet', ''))}")


def _print_rebuild_human(data: dict) -> None:
    """--rebuild 人类输出：project_ids 非空 → 计数；否则全部项目（spec §4）."""
    pids = data.get("project_ids")
    if pids:
        typer.echo(f"✅ 索引重建完成 ({len(pids)} 个项目)")
    else:
        typer.echo("✅ 索引重建完成 (全部项目)")


@app.command()
@instrument(caller_type="cli")
def search_cmd(
    ctx: typer.Context,
    query: str | None = typer.Argument(None, help="查询词（1-100 字符；--rebuild 模式不适用）"),
    project: list[str] = typer.Option(
        [], "--project", "-p", help="项目名称或 ID（可重复，必填 ≥1）"
    ),
    type_: list[str] = typer.Option([], "--type", "-t", help="可搜索类型（可重复）"),
    mode: str = typer.Option("keyword", "--mode", help="检索模式（keyword/semantic）"),
    limit: int = typer.Option(20, "--limit", help="默认 20，最大 100"),
    offset: int = typer.Option(0, "--offset", help="默认 0"),
    rebuild: bool = typer.Option(False, "--rebuild", help="手动全量重建索引"),
    json_output: bool = typer.Option(False, "--json", help="输出 JSON 信封格式"),
) -> None:
    """全文搜索（FTS5 词法 + AI 语义）；--rebuild 手动全量重建索引"""
    cli_ctx: CliContext = ctx.obj
    if not rebuild and (query is None or not query.strip()):
        raise typer.Exit(code=2)

    async def _impl() -> tuple[dict, dict[str, str]]:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            project_ids, name_map = await _resolve_projects(cli_ctx, client, project)
            if rebuild:
                params: dict[str, str] = {}
                if project_ids:
                    params["project_ids"] = ",".join(project_ids)
                return (
                    await client.post("/search/rebuild", params=params or None),
                    name_map,
                )
            params = {
                "q": query or "",
                "project_ids": ",".join(project_ids),
                "mode": mode,
                "limit": str(limit),
                "offset": str(offset),
            }
            if type_:
                params["types"] = ",".join(type_)
            data = await client.get("/search", params=params)
            if not (cli_ctx.json_output or json_output) and data.get("hits"):
                name_map = await _fetch_projects(client)
            return data, name_map

    data, name_map = _run(cli_ctx, _impl)
    if cli_ctx.json_output or json_output:
        print_result(cli_ctx, data)
    elif rebuild:
        _print_rebuild_human(data)
    else:
        _print_human(data, name_map)
