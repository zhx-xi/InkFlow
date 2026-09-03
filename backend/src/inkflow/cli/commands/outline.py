"""F11 大纲管理 CLI 命令 — `inkflow outline <action>` + `outline point <action>`
+ `outline arc <action>` + `outline generate`.

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

依据: specs/f11-outline/spec.md §4/§4.5/§7。
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
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel
from inkflow.logging import instrument

app = typer.Typer(name="outline", help="大纲管理", no_args_is_help=True)

point_app = typer.Typer(name="point", help="情节点管理", no_args_is_help=True)

arc_app = typer.Typer(name="arc", help="故事弧线管理", no_args_is_help=True)


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
# create  —  inkflow outline create --project-id <uuid> --name <str> ...
# ---------------------------------------------------------------------------


@app.command("create")
@instrument(caller_type="cli")
def create_outline_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    name: str = typer.Option(..., "--name", "-n", help="大纲名"),
    description: str = typer.Option("", "--description", "-d", help="大纲总体描述"),
    sort_order: int = typer.Option(0, "--sort-order", help="排序权重（小者在前）"),
    level: str = typer.Option("overall", "--level", help="大纲层级 (overall/volume/chapter)"),
    parent_id: str | None = typer.Option(
        None, "--parent-id", help="父大纲 ID (UUID；volume 挂 overall、chapter 挂 volume，必填)"
    ),
) -> None:
    """创建大纲（#835 强制树形：level=chapter 须挂 volume，否则 422）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")
    parent_uuid = _parse_uuid(cli_ctx, parent_id, "父大纲不存在") if parent_id else None

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            body: dict = {
                "name": name,
                "description": description,
                "sort_order": sort_order,
                "level": level,
            }
            if parent_uuid is not None:
                body["parent_id"] = str(parent_uuid)
            return await client.post(
                f"/projects/{pid}/outlines",
                json=body,
            )

    outline = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, outline)
    else:
        typer.echo(f"✅ 大纲创建成功: [{outline['name']}]")


# ---------------------------------------------------------------------------
# list  —  inkflow outline list --project-id <uuid> [--search] ...
# ---------------------------------------------------------------------------


@app.command("list")
@instrument(caller_type="cli")
def list_outlines_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    search: str | None = typer.Option(None, "--search", "-s", help="按名称搜索"),
    sort: str = typer.Option(
        "updated_at", "--sort", help="排序字段 (name / updated_at / created_at)"
    ),
    sort_desc: bool = typer.Option(
        True, "--sort-desc/--no-sort-desc", help="按排序字段降序（默认开启）"
    ),
    offset: int = typer.Option(0, "--offset", help="分页偏移"),
    limit: int = typer.Option(50, "--limit", help="每页数量"),
) -> None:
    """列出项目内大纲"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(
                f"/projects/{pid}/outlines",
                params={
                    "search": search,
                    "sort_by": sort,
                    "sort_desc": sort_desc,
                    "offset": offset,
                    "limit": limit,
                },
            )

    data = _run(cli_ctx, _impl)
    outlines = data.get("items", [])
    total = data.get("total", 0)
    if not outlines and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无大纲")
        return
    if not cli_ctx.json_output and total:
        print_result(cli_ctx, f"共 {total} 个大纲")
    print_result(cli_ctx, outlines)


# ---------------------------------------------------------------------------
# get  —  inkflow outline get --id <uuid>
# ---------------------------------------------------------------------------


@app.command("get")
@instrument(caller_type="cli")
def get_outline_cmd(
    ctx: typer.Context,
    outline_id: str = typer.Option(..., "--id", "-i", help="大纲 ID (UUID)"),
) -> None:
    """查看大纲详情"""
    cli_ctx: CliContext = ctx.obj
    oid = _parse_uuid(cli_ctx, outline_id, "大纲不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/outlines/{oid}")

    outline = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, outline)
    else:
        typer.echo(f"ID:         {outline['id']}")
        typer.echo(f"名称:       {outline['name']}")
        typer.echo(f"描述:       {outline['description']}")
        typer.echo(f"排序:       {outline['sort_order']}")
        typer.echo(f"创建时间:   {outline['created_at']}")
        typer.echo(f"更新时间:   {outline['updated_at']}")


# ---------------------------------------------------------------------------
# update  —  inkflow outline update --id <uuid> [--name] [--sort-order] ...
# ---------------------------------------------------------------------------


@app.command("update")
@instrument(caller_type="cli")
def update_outline_cmd(
    ctx: typer.Context,
    outline_id: str = typer.Option(..., "--id", "-i", help="大纲 ID (UUID)"),
    name: str | None = typer.Option(None, "--name", "-n", help="新大纲名"),
    description: str | None = typer.Option(None, "--description", "-d", help="新大纲描述"),
    sort_order: int | None = typer.Option(None, "--sort-order", help="新排序权重"),
) -> None:
    """更新大纲（仅更新传入的字段）"""
    cli_ctx: CliContext = ctx.obj
    oid = _parse_uuid(cli_ctx, outline_id, "大纲不存在")

    async def _impl() -> dict:
        update_fields: dict[str, Any] = {}
        if name is not None:
            update_fields["name"] = name
        if description is not None:
            update_fields["description"] = description
        if sort_order is not None:
            update_fields["sort_order"] = sort_order
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch(f"/outlines/{oid}", json=update_fields)

    outline = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, outline)
    else:
        typer.echo(f"✅ 大纲已更新: [{outline['name']}]")


# ---------------------------------------------------------------------------
# delete  —  inkflow outline delete --id <uuid> [--force]
# ---------------------------------------------------------------------------


@app.command("delete")
@instrument(caller_type="cli")
def delete_outline_cmd(
    ctx: typer.Context,
    outline_id: str = typer.Option(..., "--id", "-i", help="大纲 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
) -> None:
    """真删大纲（v1.1，不可恢复，情节点级联删除）"""
    cli_ctx: CliContext = ctx.obj
    oid = _parse_uuid(cli_ctx, outline_id, "大纲不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        if not typer.confirm(f"确定要删除大纲 #{outline_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl() -> None:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            await client.delete(f"/outlines/{oid}")

    _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, {"id": str(oid), "deleted": True})
    else:
        typer.echo(f"✅ 大纲 #{outline_id} 已删除")


# ---------------------------------------------------------------------------
# generate  —  inkflow outline generate --project-id <uuid> [--prompt] ...
# ---------------------------------------------------------------------------


@app.command("generate")
@instrument(caller_type="cli")
def generate_outline_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    name: str | None = typer.Option(None, "--name", "-n", help="目标大纲名（缺省「未命名大纲」）"),
    prompt: str = typer.Option("", "--prompt", help="创作约束/设定摘要（与 --prompt-file 互斥）"),
    prompt_file: str | None = typer.Option(
        None, "--prompt-file", help="创作约束文件路径（与 --prompt 互斥）"
    ),
    num_chapters: int | None = typer.Option(None, "--num-chapters", help="规划章节数提示 (1-100)"),
    save: bool = typer.Option(True, "--save/--no-save", help="生成后自动保存（默认开启）"),
    model: str | None = typer.Option(
        None, "--model", help="覆盖项目默认模型 (provider/model_name)"
    ),
) -> None:
    """AI 生成大纲（spec §5；--no-save 仅预览不落库）"""
    cli_ctx: CliContext = ctx.obj
    if prompt and prompt_file is not None:
        typer.echo("❌ --prompt 与 --prompt-file 不能同时使用", err=True)
        raise typer.Exit(code=2)
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        gen_prompt = prompt
        if prompt_file is not None:
            gen_prompt = Path(prompt_file).read_text(encoding="utf-8")
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                "/outlines/generate",
                json={
                    "project_id": str(pid),
                    "name": name,
                    "prompt": gen_prompt,
                    "num_chapters": num_chapters,
                    "save": save,
                    "model": model,
                },
            )

    result = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, result)
    else:
        if result["saved"]:
            outline_name = (
                result["outline"]["name"] if result.get("outline") else (name or "未命名大纲")
            )
            typer.echo(
                f"✅ 大纲生成并保存: [{outline_name}]，含 {len(result['plot_points'])} 个情节点、"
                f"{len(result['arcs'])} 条弧线"
            )
        else:
            preview = result.get("preview") or {}
            n_points = len(preview.get("plot_points", []))
            n_arcs = len(preview.get("arcs", []))
            typer.echo(
                f"🔍 大纲预览（未保存）: {n_points} 个情节点、{n_arcs} 条弧线 "
                "—— 使用 --save 保存后落库"
            )
        if result.get("warnings"):
            typer.echo(f"⚠️ 生成完成但有警告: {'; '.join(result['warnings'][:3])}")


# ---------------------------------------------------------------------------
# point 子组  —  inkflow outline point <list|create|update|delete>
# ---------------------------------------------------------------------------


@point_app.command("list")
@instrument(caller_type="cli")
def list_points_cmd(
    ctx: typer.Context,
    outline_id: str = typer.Option(..., "--outline-id", help="大纲 ID (UUID)"),
) -> None:
    """列出大纲内情节点（position 升序）"""
    cli_ctx: CliContext = ctx.obj
    oid = _parse_uuid(cli_ctx, outline_id, "大纲不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/outlines/{oid}/plot-points")

    data = _run(cli_ctx, _impl)
    points = data.get("items", [])
    if not points and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无情节点")
        return
    print_result(cli_ctx, points)


@point_app.command("create")
@instrument(caller_type="cli")
def create_point_cmd(
    ctx: typer.Context,
    outline_id: str = typer.Option(..., "--outline-id", help="大纲 ID (UUID)"),
    name: str = typer.Option(..., "--name", "-n", help="情节点名"),
    type: str = typer.Option("", "--type", "-t", help="情节点类型（空串 = 未分类）"),
    description: str = typer.Option("", "--description", "-d", help="情节点要点描述"),
    position: int | None = typer.Option(
        None, "--position", help="大纲内排序（缺省 = 追加到大纲末尾）"
    ),
    arc_id: str | None = typer.Option(None, "--arc-id", help="所属故事弧线 ID (UUID)"),
) -> None:
    """创建情节点"""
    cli_ctx: CliContext = ctx.obj
    oid = _parse_uuid(cli_ctx, outline_id, "大纲不存在")
    aid = _parse_uuid(cli_ctx, arc_id, "弧线不存在") if arc_id is not None else None

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                f"/outlines/{oid}/plot-points",
                json={
                    "name": name,
                    "type": type,
                    "description": description,
                    "position": position,
                    "arc_id": str(aid) if aid is not None else None,
                },
            )

    point = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, point)
    else:
        type_suffix = f" ({point['type']})" if point["type"] else ""
        typer.echo(f"✅ 情节点创建成功: [{point['name']}]{type_suffix}")


@point_app.command("update")
@instrument(caller_type="cli")
def update_point_cmd(
    ctx: typer.Context,
    point_id: str = typer.Option(..., "--id", "-i", help="情节点 ID (UUID)"),
    name: str | None = typer.Option(None, "--name", "-n", help="新情节点名"),
    type: str | None = typer.Option(None, "--type", "-t", help="新情节点类型"),
    description: str | None = typer.Option(None, "--description", "-d", help="新要点描述"),
    position: int | None = typer.Option(None, "--position", help="新排序位置"),
    arc_id: str | None = typer.Option(
        None, "--arc-id", help='新弧线 ID (UUID)；传空字符串 "" 表示清除弧线归属'
    ),
) -> None:
    """更新情节点（仅更新传入的字段）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, point_id, "情节点不存在")

    async def _impl() -> dict:
        update_fields: dict[str, Any] = {}
        if name is not None:
            update_fields["name"] = name
        if type is not None:
            update_fields["type"] = type
        if description is not None:
            update_fields["description"] = description
        if position is not None:
            update_fields["position"] = position
        if arc_id is not None:
            update_fields["arc_id"] = (
                "" if arc_id == "" else str(_parse_uuid(cli_ctx, arc_id, "弧线不存在"))
            )
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch(f"/plot-points/{pid}", json=update_fields)

    point = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, point)
    else:
        typer.echo(f"✅ 情节点已更新: [{point['name']}]")


@point_app.command("delete")
@instrument(caller_type="cli")
def delete_point_cmd(
    ctx: typer.Context,
    point_id: str = typer.Option(..., "--id", "-i", help="情节点 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
) -> None:
    """删除情节点（默认软删除）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, point_id, "情节点不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        if not typer.confirm(f"确定要删除情节点 #{point_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl() -> None:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            await client.delete(f"/plot-points/{pid}")

    _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, {"id": str(pid), "deleted": True})
    else:
        typer.echo(f"✅ 情节点 #{point_id} 已删除")


@point_app.command("get")
@instrument(caller_type="cli")
def get_point_cmd(
    ctx: typer.Context,
    point_id: str = typer.Option(..., "--id", "-i", help="情节点 ID (UUID)"),
) -> None:
    """查看情节点详情"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, point_id, "情节点不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/plot-points/{pid}")

    point = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, point)
    else:
        typer.echo(f"ID:         {point['id']}")
        typer.echo(f"名称:       {point['name']}")
        typer.echo(f"类型:       {point['type']}")
        typer.echo(f"描述:       {point['description']}")


# ---------------------------------------------------------------------------
# arc 子组  —  inkflow outline arc <list|create|update|delete>
# ---------------------------------------------------------------------------


@arc_app.command("list")
@instrument(caller_type="cli")
def list_arcs_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
) -> None:
    """列出项目内故事弧线（名称升序）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/projects/{pid}/story-arcs")

    data = _run(cli_ctx, _impl)
    arcs = data.get("items", [])
    if not arcs and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无弧线")
        return
    print_result(cli_ctx, arcs)


@arc_app.command("create")
@instrument(caller_type="cli")
def create_arc_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    name: str = typer.Option(..., "--name", "-n", help="弧线名"),
    description: str = typer.Option("", "--description", "-d", help="弧线说明"),
) -> None:
    """创建故事弧线"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                f"/projects/{pid}/story-arcs",
                json={"name": name, "description": description},
            )

    arc = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, arc)
    else:
        typer.echo(f"✅ 弧线创建成功: [{arc['name']}]")


@arc_app.command("update")
@instrument(caller_type="cli")
def update_arc_cmd(
    ctx: typer.Context,
    arc_id: str = typer.Option(..., "--id", "-i", help="弧线 ID (UUID)"),
    name: str | None = typer.Option(None, "--name", "-n", help="新弧线名"),
    description: str | None = typer.Option(None, "--description", "-d", help="新弧线说明"),
) -> None:
    """更新故事弧线（仅更新传入的字段）"""
    cli_ctx: CliContext = ctx.obj
    aid = _parse_uuid(cli_ctx, arc_id, "弧线不存在")

    async def _impl() -> dict:
        update_fields: dict[str, Any] = {}
        if name is not None:
            update_fields["name"] = name
        if description is not None:
            update_fields["description"] = description
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch(f"/story-arcs/{aid}", json=update_fields)

    arc = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, arc)
    else:
        typer.echo(f"✅ 弧线已更新: [{arc['name']}]")


@arc_app.command("delete")
@instrument(caller_type="cli")
def delete_arc_cmd(
    ctx: typer.Context,
    arc_id: str = typer.Option(..., "--id", "-i", help="弧线 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
) -> None:
    """删除故事弧线（成员情节点 arc_id 置 NULL，情节点保留）"""
    cli_ctx: CliContext = ctx.obj
    aid = _parse_uuid(cli_ctx, arc_id, "弧线不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        if not typer.confirm(f"确定要删除弧线 #{arc_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl() -> None:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            await client.delete(f"/story-arcs/{aid}")

    _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, {"id": str(aid), "deleted": True})
    else:
        typer.echo(f"✅ 弧线 #{arc_id} 已删除")


@arc_app.command("get")
@instrument(caller_type="cli")
def get_arc_cmd(
    ctx: typer.Context,
    arc_id: str = typer.Option(..., "--id", "-i", help="弧线 ID (UUID)"),
) -> None:
    """查看弧线详情"""
    cli_ctx: CliContext = ctx.obj
    aid = _parse_uuid(cli_ctx, arc_id, "弧线不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/story-arcs/{aid}")

    arc = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, arc)
    else:
        typer.echo(f"ID:         {arc['id']}")
        typer.echo(f"名称:       {arc['name']}")
        typer.echo(f"描述:       {arc['description']}")


# ── 注册 point / arc 子组 ──

app.add_typer(point_app, name="point")
app.add_typer(arc_app, name="arc")
