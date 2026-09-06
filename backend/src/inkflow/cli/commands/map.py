"""F36 地图管理 CLI 命令 — `inkflow map <action>`.

薄层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() +
InkFlowHTTPClient 调内核 REST API（spec §4；Issue #169 CLI 恒经 HTTP）。
遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130；地图删除类命令二次确认 + --force；
--json + 无 --force 的地图删除 → VALIDATION_ERROR。

错误码映射（spec §4/§7）:
- HttpApiError：404 → NOT_FOUND、422 → VALIDATION_ERROR、
  401 → CONFIG_ERROR、500 + LLM_ERROR 头 → LLM_ERROR、其余 → INTERNAL_ERROR
- KernelStartupError → KERNEL_ERROR
- pydantic ValidationError / 图片文件缺失 → VALIDATION_ERROR
- 其余异常 → DB_ERROR

依据: specs/f36-world-map/spec.md §4。
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

app = typer.Typer(name="map", help="地图管理", no_args_is_help=True)
pin_app = typer.Typer(name="pin", help="地图 pin 管理", no_args_is_help=True)
app.add_typer(pin_app, name="pin")


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


def _read_image(cli_ctx: CliContext, image_path: str) -> tuple[str, bytes]:
    """读本地图片（扩展名白名单 png/jpg/jpeg/webp；文件缺失/类型不支持 → VALIDATION_ERROR）."""
    path = Path(image_path)
    if path.suffix.lower().lstrip(".") not in {"png", "jpg", "jpeg", "webp"}:
        print_error(cli_ctx, "VALIDATION_ERROR", f"图片类型不支持: {path.suffix or '（无扩展名）'}")
    content = path.read_bytes()  # FileNotFoundError 由 _run 兜底 → VALIDATION_ERROR
    return path.name, content


# ---------------------------------------------------------------------------
# create  —  inkflow map create --project-id <uuid> --name <str> --image <path> [--parent-map]
# ---------------------------------------------------------------------------


@app.command("create")
@instrument(caller_type="cli")
def create_map_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    name: str = typer.Option(..., "--name", "-n", help="地图名"),
    image: str = typer.Option(..., "--image", help="本地图片路径 (png/jpg/jpeg/webp)"),
    root_location: str | None = typer.Option(
        None, "--root-location", help="父地点 ID (UUID)；缺省 = 全局图"
    ),
    parent_map: str | None = typer.Option(
        None, "--parent-map", help="父地图 ID (UUID)；缺省 = 根图"
    ),
    description: str = typer.Option("", "--description", help="地图描述"),
) -> None:
    """创建地图（上传本地图片建图，spec §4）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        filename, content = _read_image(cli_ctx, image)
        data: dict[str, Any] = {"name": name, "description": description}
        if root_location is not None:
            data["root_location_id"] = root_location
        if parent_map is not None:
            data["parent_map_id"] = parent_map
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post_file(
                f"/projects/{pid}/maps",
                data=data,
                filename=filename,
                content=content,
            )

    wm = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, wm)
    else:
        typer.echo(f"✅ 地图创建成功: [{wm['name']}]")


# ---------------------------------------------------------------------------
# list  —  inkflow map list --project-id <uuid> [--root-location <uuid>|none]
# ---------------------------------------------------------------------------


@app.command("list")
@instrument(caller_type="cli")
def list_maps_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    root_location: str | None = typer.Option(
        None, "--root-location", help="UUID 或 none（全局图）"
    ),
) -> None:
    """列出项目地图（--root-location none = 全局图过滤）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        params: dict[str, str] = {}
        if root_location is not None:
            params["root_location_id"] = root_location  # none 字符串原样传——API 侧解析
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/projects/{pid}/maps", params=params or None)

    data = _run(cli_ctx, _impl)
    items = data.get("items", [])
    total = data.get("total", 0)
    result = {"items": items, "total": total}
    if cli_ctx.json_output:
        print_result(cli_ctx, result)
    else:
        print_result(cli_ctx, result)


# ---------------------------------------------------------------------------
# get  —  inkflow map get <map_id> [--image-output <path>]
# ---------------------------------------------------------------------------


@app.command("get")
@instrument(caller_type="cli")
def get_map_cmd(
    ctx: typer.Context,
    map_id: str = typer.Argument(..., help="地图 ID (UUID)"),
    image_output: str | None = typer.Option(
        None, "--image-output", help="同时下载地图图片到该路径"
    ),
) -> None:
    """查看地图详情（可选 --image-output 下载图片）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, map_id, "地图不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            wm = await client.get(f"/maps/{sid}")
            if image_output is not None:
                content = await client.get_bytes(f"/maps/{sid}/image")
                Path(image_output).write_bytes(content)
            return wm

    wm = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, wm)
    else:
        typer.echo(f"✅ 地图: [{wm['name']}]")
        if image_output is not None:
            typer.echo(f"✅ 图片已保存: {image_output}")


# ---------------------------------------------------------------------------
# update  —  inkflow map update <map_id> [--name] [--description]
#       [--root-location] [--parent-map] [--clear-parent]
# ---------------------------------------------------------------------------


@app.command("update")
@instrument(caller_type="cli")
def update_map_cmd(
    ctx: typer.Context,
    map_id: str = typer.Argument(..., help="地图 ID (UUID)"),
    name: str | None = typer.Option(None, "--name", "-n", help="新地图名"),
    description: str | None = typer.Option(None, "--description", help="新描述"),
    root_location: str | None = typer.Option(
        None, "--root-location", help="新父地点 ID (UUID)；none = 改全局图"
    ),
    parent_map: str | None = typer.Option(
        None, "--parent-map", help="新父地图 ID (UUID)；改挂为其子图"
    ),
    clear_parent: bool = typer.Option(False, "--clear-parent", help="改回根图（body 显式 null）"),
) -> None:
    """更新地图（仅更新传入字段；--parent-map = 改挂父图，--clear-parent = 显式 null 改回根图）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, map_id, "地图不存在")
    if parent_map is not None and clear_parent:
        print_error(
            cli_ctx,
            "VALIDATION_ERROR",
            "--parent-map 与 --clear-parent 互斥；改回根图请用 --clear-parent",
        )

    async def _impl() -> dict:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if root_location is not None:
            body["root_location_id"] = None if root_location == "none" else root_location
        if parent_map is not None:
            body["parent_map_id"] = parent_map
        elif clear_parent:
            body["parent_map_id"] = None
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch(f"/maps/{sid}", json=body)

    wm = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, wm)
    else:
        typer.echo(f"✅ 地图已更新: [{wm['name']}]")


# ---------------------------------------------------------------------------
# image  —  inkflow map image <map_id> --image <path>
# ---------------------------------------------------------------------------


@app.command("image")
@instrument(caller_type="cli")
def image_map_cmd(
    ctx: typer.Context,
    map_id: str = typer.Argument(..., help="地图 ID (UUID)"),
    image: str = typer.Option(..., "--image", help="本地图片路径 (png/jpg/jpeg/webp)"),
) -> None:
    """更换地图图片（put_file 换图）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, map_id, "地图不存在")

    async def _impl() -> dict:
        filename, content = _read_image(cli_ctx, image)
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.put_file(
                f"/maps/{sid}/image",
                data={},
                filename=filename,
                content=content,
            )

    wm = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, wm)
    else:
        typer.echo(f"✅ 图片已更换: [{wm['name']}]")


# ---------------------------------------------------------------------------
# delete  —  inkflow map delete <map_id> [--force] [--cascade] [--reparent-to]
# ---------------------------------------------------------------------------


@app.command("delete")
@instrument(caller_type="cli")
def delete_map_cmd(
    ctx: typer.Context,
    map_id: str = typer.Argument(..., help="地图 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
    cascade: bool = typer.Option(False, "--cascade", help="级联真删整棵地图子树"),
    reparent_to: str | None = typer.Option(None, "--reparent-to", help="子地图改挂新父后删除自身"),
) -> None:
    """删除地图（真删；有子地图需 --cascade 或 --reparent-to）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, map_id, "地图不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        if not typer.confirm(f"确定要删除地图 #{map_id} 吗？"):
            typer.echo("已取消")
            return

    async def _impl() -> None:
        params: dict[str, str] = {}
        if cascade:
            params["cascade"] = "true"
        if reparent_to is not None:
            params["reparent_to"] = reparent_to
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            await client.delete(f"/maps/{sid}", params=params)

    _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, {"deleted": True, "id": map_id})
    else:
        typer.echo(f"✅ 地图已删除: {map_id}")


# ---------------------------------------------------------------------------
# children  —  inkflow map children <map_id>
# ---------------------------------------------------------------------------


@app.command("children")
@instrument(caller_type="cli")
def children_map_cmd(
    ctx: typer.Context,
    map_id: str = typer.Argument(..., help="地图 ID (UUID)"),
) -> None:
    """列出地图的子地图（drill-down 导航）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, map_id, "地图不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/maps/{sid}/children")

    data = _run(cli_ctx, _impl)
    items = data.get("items", [])
    total = data.get("total", 0)
    result = {"items": items, "total": total}
    if cli_ctx.json_output:
        print_result(cli_ctx, result)
    else:
        print_result(cli_ctx, result)


# ---------------------------------------------------------------------------
# pin add  —  inkflow map pin add <map_id> --x <float> --y <float> --label <str>
# ---------------------------------------------------------------------------


@pin_app.command("add")
@instrument(caller_type="cli")
def add_pin_cmd(
    ctx: typer.Context,
    map_id: str = typer.Argument(..., help="地图 ID (UUID)"),
    x: float = typer.Option(..., "--x", help="X 坐标（相对宽度百分比 0-100）"),
    y: float = typer.Option(..., "--y", help="Y 坐标（相对高度百分比 0-100）"),
    label: str = typer.Option(..., "--label", help="pin 显示文本"),
    location: str | None = typer.Option(None, "--location", help="关联地点 ID (UUID)"),
) -> None:
    """添加地图 pin（--location 缺省 = 纯注释 pin）"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, map_id, "地图不存在")

    async def _impl() -> dict:
        body: dict[str, Any] = {"x": x, "y": y, "label": label}
        if location is not None:
            body["location_id"] = location
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(f"/maps/{sid}/pins", json=body)

    pin = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, pin)
    else:
        typer.echo(f"✅ pin 已添加: [{pin['label']}]")


# ---------------------------------------------------------------------------
# pin list  —  inkflow map pin list <map_id>
# ---------------------------------------------------------------------------


@pin_app.command("list")
@instrument(caller_type="cli")
def list_pins_cmd(
    ctx: typer.Context,
    map_id: str = typer.Argument(..., help="地图 ID (UUID)"),
) -> None:
    """列出地图上的 pin"""
    cli_ctx: CliContext = ctx.obj
    sid = _parse_uuid(cli_ctx, map_id, "地图不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/maps/{sid}/pins")

    data = _run(cli_ctx, _impl)
    items = data.get("items", [])
    total = data.get("total", 0)
    result = {"items": items, "total": total}
    if cli_ctx.json_output:
        print_result(cli_ctx, result)
    else:
        print_result(cli_ctx, result)


# ---------------------------------------------------------------------------
# pin update  —  inkflow map pin update <pin_id> [--x] [--y] [--label] [--location]
# ---------------------------------------------------------------------------


@pin_app.command("update")
@instrument(caller_type="cli")
def update_pin_cmd(
    ctx: typer.Context,
    pin_id: str = typer.Argument(..., help="pin ID (UUID)"),
    x: float | None = typer.Option(None, "--x", help="X 坐标（相对宽度百分比 0-100）"),
    y: float | None = typer.Option(None, "--y", help="Y 坐标（相对高度百分比 0-100）"),
    label: str | None = typer.Option(None, "--label", help="pin 显示文本"),
    location: str | None = typer.Option(
        None, "--location", help="新关联地点 ID (UUID)；none = 取消关联"
    ),
) -> None:
    """更新 pin（仅更新传入字段；--location none → 显式 null = 取消关联）"""
    cli_ctx: CliContext = ctx.obj
    pin_uuid = _parse_uuid(cli_ctx, pin_id, "pin 不存在")

    async def _impl() -> dict:
        body: dict[str, Any] = {}
        if x is not None:
            body["x"] = x
        if y is not None:
            body["y"] = y
        if label is not None:
            body["label"] = label
        if location is not None:
            body["location_id"] = None if location == "none" else location
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.patch(f"/map-pins/{pin_uuid}", json=body)

    pin = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, pin)
    else:
        typer.echo(f"✅ pin 已更新: [{pin['label']}]")


# ---------------------------------------------------------------------------
# pin delete  —  inkflow map pin delete <pin_id>
# ---------------------------------------------------------------------------


@pin_app.command("delete")
@instrument(caller_type="cli")
def delete_pin_cmd(
    ctx: typer.Context,
    pin_id: str = typer.Argument(..., help="pin ID (UUID)"),
) -> None:
    """删除 pin（真删单行，无级联）"""
    cli_ctx: CliContext = ctx.obj
    pin_uuid = _parse_uuid(cli_ctx, pin_id, "pin 不存在")

    async def _impl() -> None:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            await client.delete(f"/map-pins/{pin_uuid}")

    _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, {"deleted": True, "id": pin_id})
    else:
        typer.echo(f"✅ pin 已删除: {pin_id}")
