"""F10 世界观管理 CLI 命令 — `inkflow world <action>`.

薄层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() +
InkFlowHTTPClient 调内核 REST API（spec §4；Issue #169 CLI 恒经 HTTP）。
遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130；删除类命令二次确认 + --force；
--json + 无 --force 的删除 → VALIDATION_ERROR。

错误码映射（spec §4/§7）:
- HttpApiError：404 → NOT_FOUND、422 → VALIDATION_ERROR、
  401 → CONFIG_ERROR、500 + LLM_ERROR 头 → LLM_ERROR、其余 → INTERNAL_ERROR
- KernelStartupError → KERNEL_ERROR
- pydantic ValidationError / 文本文件缺失 → VALIDATION_ERROR
- 其余异常 → DB_ERROR

依据: specs/f10-world-settings/spec.md §4/§4.2。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
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

app = typer.Typer(name="world", help="世界观管理", no_args_is_help=True)


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
    except FileNotFoundError as e:
        print_error(cli_ctx, "VALIDATION_ERROR", f"文本文件不存在: {e.filename}")
    except Exception as e:
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


# ---------------------------------------------------------------------------
# create  —  inkflow world create --project-id <uuid> --name <str> ...
# ---------------------------------------------------------------------------


@app.command("create")
@instrument(caller_type="cli")
def create_setting_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    name: str = typer.Option(..., "--name", "-n", help="条目名"),
    category: str = typer.Option("", "--category", "-c", help="类别（空串 = 未分类）"),
    content: str = typer.Option("", "--content", help="条目内容"),
    parent: str | None = typer.Option(None, "--parent", help="父地点 ID (UUID)；缺省 = 顶层"),
) -> None:
    """创建世界观条目（F35: --parent 指定父地点，缺省顶层）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        body: dict[str, Any] = {"name": name, "category": category, "content": content}
        if parent is not None:
            body["parent_id"] = parent  # 契约定死: 无 --parent 时 body 不含 parent_id 键
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                f"/projects/{pid}/world-settings",
                json=body,
            )

    setting = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, setting)
    elif setting["category"]:
        typer.echo(f"✅ 世界观条目创建成功: [{setting['name']}] ({setting['category']})")
    else:
        typer.echo(f"✅ 世界观条目创建成功: [{setting['name']}]")


# ---------------------------------------------------------------------------
# list  —  inkflow world list --project-id <uuid> [--search] [--category] ...
# ---------------------------------------------------------------------------


@app.command("list")
@instrument(caller_type="cli")
def list_settings_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    search: str | None = typer.Option(None, "--search", "-s", help="按条目名搜索"),
    category: str | None = typer.Option(None, "--category", "-c", help="按类别过滤"),
    sort: str = typer.Option(
        "updated_at", "--sort", help="排序字段 (name / category / updated_at / created_at)"
    ),
    sort_desc: bool = typer.Option(
        True, "--sort-desc/--no-sort-desc", help="按排序字段降序（默认开启）"
    ),
    offset: int = typer.Option(0, "--offset", help="分页偏移"),
    limit: int = typer.Option(50, "--limit", help="每页数量"),
) -> None:
    """列出项目内世界观条目"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(
                f"/projects/{pid}/world-settings",
                params={
                    "search": search,
                    "category": category,
                    "sort_by": sort,
                    "sort_desc": sort_desc,
                    "offset": offset,
                    "limit": limit,
                },
            )

    data = _run(cli_ctx, _impl)
    settings = data.get("items", [])
    total = data.get("total", 0)
    if not settings and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无条目")
        return
    if not cli_ctx.json_output and total:
        print_result(cli_ctx, f"共 {total} 个条目")
    print_result(cli_ctx, settings)


# ---------------------------------------------------------------------------
# categories  —  inkflow world categories --project-id <uuid>
# ---------------------------------------------------------------------------


@app.command("categories")
@instrument(caller_type="cli")
def list_categories_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
) -> None:
    """类别汇总（含条目数）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/projects/{pid}/world-settings/categories")

    data = _run(cli_ctx, _impl)
    categories = data.get("items", [])
    if not categories and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无类别")
        return
    if cli_ctx.json_output:
        print_result(cli_ctx, categories)
    else:
        for item in categories:
            typer.echo(f"  {item['category']}: {item['count']} 条")


# ---------------------------------------------------------------------------
# get  —  inkflow world get --id <uuid>
# ---------------------------------------------------------------------------


@app.command("get")
@instrument(caller_type="cli")
def get_setting_cmd(
    ctx: typer.Context,
    setting_id: str = typer.Option(..., "--id", "-i", help="条目 ID (UUID)"),
) -> None:
    """查看世界观条目详情"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, setting_id, "世界观条目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/world-settings/{sid}")

    setting = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, setting)
    else:
        typer.echo(f"ID:         {setting['id']}")
        typer.echo(f"名称:       {setting['name']}")
        typer.echo(f"类别:       {setting['category']}")
        typer.echo(f"内容:       {setting['content']}")
        typer.echo(f"创建时间:   {setting['created_at']}")
        typer.echo(f"更新时间:   {setting['updated_at']}")


# ---------------------------------------------------------------------------
# ancestors  —  inkflow world ancestors --id <uuid>
# ---------------------------------------------------------------------------


@app.command("ancestors")
@instrument(caller_type="cli")
def ancestors_cmd(
    ctx: typer.Context,
    setting_id: str = typer.Argument(..., help="条目 ID (UUID)"),
) -> None:
    """查看祖先链（含自身，自身在前，面包屑）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, setting_id, "世界观条目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/world-settings/{sid}/ancestors")

    data = _run(cli_ctx, _impl)
    items = data.get("items", [])
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
    elif not items:
        print_result(cli_ctx, "📭 暂无祖先链")
    else:
        print_result(cli_ctx, " → ".join(s["name"] for s in items))


# ---------------------------------------------------------------------------
# descendants  —  inkflow world descendants --id <uuid>
# ---------------------------------------------------------------------------


@app.command("descendants")
@instrument(caller_type="cli")
def descendants_cmd(
    ctx: typer.Context,
    setting_id: str = typer.Argument(..., help="条目 ID (UUID)"),
) -> None:
    """查看子树（含自身，层序）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, setting_id, "世界观条目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/world-settings/{sid}/descendants")

    data = _run(cli_ctx, _impl)
    items = data.get("items", [])
    if cli_ctx.json_output:
        print_result(cli_ctx, data)
    elif not items:
        print_result(cli_ctx, "📭 暂无子地点")
    else:
        for s in items:
            depth = s.get("depth", 0)  # 若无 depth 字段则平铺输出
            indent = "  " * depth
            typer.echo(f"{indent}- {s['name']}")


# ---------------------------------------------------------------------------
# copy  —  inkflow world copy <source_project_id> <target_project_id> [--root <uuid>]
# ---------------------------------------------------------------------------


@app.command("copy")
@instrument(caller_type="cli")
def copy_world_cmd(
    ctx: typer.Context,
    source_project_id: str = typer.Argument(..., help="源项目 ID (UUID)"),
    target_project_id: str = typer.Argument(..., help="目标项目 ID (UUID)"),
    root: str | None = typer.Option(None, "--root", help="复制起点条目 ID (UUID)；缺省 = 整棵"),
) -> None:
    """复制源项目世界观到目标项目（跨书复用；同名冲突跳过 + warning）"""
    cli_ctx: CliContext = ctx.obj
    src = _parse_uuid(cli_ctx, source_project_id, "源项目不存在")
    tgt = _parse_uuid(cli_ctx, target_project_id, "项目不存在")

    async def _impl() -> dict:
        body: dict[str, Any] = {"source_project_id": str(src)}
        if root is not None:
            body["root_setting_id"] = root  # 契约定死: 无 --root 时 body 不含 root_setting_id 键
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(f"/projects/{tgt}/world-settings/copy", json=body)

    result = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, result)
        return
    created_n = len(result.get("created", []))
    maps_n = len(result.get("maps_created", []))
    pins_n = result.get("pins_created", 0)
    typer.echo(f"✅ 复制完成: {created_n} 条世界观条目, {maps_n} 张地图, {pins_n} 个 pin")
    skipped = result.get("skipped", [])
    if skipped:
        typer.echo(f"⚠️ 跳过同名条目: {', '.join(skipped)}")
    for w in result.get("warnings", []):
        typer.echo(f"⚠️ {w}")


# ---------------------------------------------------------------------------
# update  —  inkflow world update --id <uuid> [--name] [--category ""] ...
# ---------------------------------------------------------------------------


@app.command("update")
@instrument(caller_type="cli")
def update_setting_cmd(
    ctx: typer.Context,
    setting_id: str = typer.Option(..., "--id", "-i", help="条目 ID (UUID)"),
    name: str | None = typer.Option(None, "--name", "-n", help="新条目名"),
    category: str | None = typer.Option(
        None, "--category", "-c", help='新类别；传空字符串 "" 表示清除类别（置为未分类）'
    ),
    content: str | None = typer.Option(None, "--content", help="新条目内容"),
    parent: str | None = typer.Option(None, "--parent", help="新父地点 ID (UUID)"),
) -> None:
    """更新世界观条目（仅更新传入的字段；--parent 传新父 ID）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, setting_id, "世界观条目不存在")

    async def _impl() -> dict:
        update_fields: dict[str, Any] = {}
        if name is not None:
            update_fields["name"] = name
        if category is not None:
            update_fields["category"] = category
        if content is not None:
            update_fields["content"] = content
        if parent is not None:
            update_fields["parent_id"] = parent
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch(f"/world-settings/{sid}", json=update_fields)

    setting = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, setting)
    else:
        typer.echo(f"✅ 条目已更新: [{setting['name']}]")


# ---------------------------------------------------------------------------
# delete  —  inkflow world delete --id <uuid> [--force]
# ---------------------------------------------------------------------------


@app.command("delete")
@instrument(caller_type="cli")
def delete_setting_cmd(
    ctx: typer.Context,
    setting_id: str = typer.Option(..., "--id", "-i", help="条目 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
    cascade: bool = typer.Option(False, "--cascade", help="级联真删子树（F35）"),
    reparent_to: str | None = typer.Option(
        None, "--reparent-to", help="子地点改挂新父后删除自身（F35）"
    ),
) -> None:
    """删除世界观条目（v1.1 真删，不可恢复；F35: --cascade / --reparent-to）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, setting_id, "世界观条目不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        label = "删除"
        if not typer.confirm(f"确定要{label}条目 #{setting_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl() -> None:
        params: dict[str, str] = {}
        if cascade:
            params["cascade"] = "true"
        if reparent_to is not None:
            params["reparent_to"] = reparent_to
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            await client.delete(
                f"/world-settings/{sid}",
                params=params,
            )

    _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, {"id": str(sid), "deleted": True})
    else:
        typer.echo(f"✅ 条目 #{setting_id} 已删除")


# ---------------------------------------------------------------------------
# extract  —  inkflow world extract --project-id <uuid> --text|--text-file
# ---------------------------------------------------------------------------


@app.command("extract")
@instrument(caller_type="cli")
def extract_settings_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    text: str = typer.Option("", "--text", help="待提取文本（与 --text-file 互斥）"),
    text_file: str | None = typer.Option(
        None, "--text-file", help="待提取文本文件路径（与 --text 互斥）"
    ),
    model: str | None = typer.Option(
        None, "--model", help="覆盖项目默认模型 (provider/model_name)"
    ),
) -> None:
    """AI 提取世界观条目（spec §5）"""
    cli_ctx: CliContext = ctx.obj
    if text and text_file is not None:
        typer.echo("❌ --text 与 --text-file 不能同时使用", err=True)
        raise typer.Exit(code=2)
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        extract_text = text
        if text_file is not None:
            extract_text = Path(text_file).read_text(encoding="utf-8")
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                "/world-settings/extract",
                json={
                    "project_id": str(pid),
                    "text": extract_text,
                    "model": model,
                },
                timeout=LLM_TASK_TIMEOUT,
            )

    result = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, result)
    else:
        n_created = len(result["created"])
        n_updated = len(result["updated"])
        n_warnings = len(result["warnings"])
        typer.echo(
            f"✅ 提取完成: 新增 {n_created} 个条目, 更新 {n_updated} 个条目, "
            f"警告 {n_warnings} 条"
        )
        if n_warnings:
            typer.echo(f"⚠️ 提取完成但有警告: {'; '.join(result['warnings'][:3])}")
