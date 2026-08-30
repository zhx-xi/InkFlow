"""F21 导出服务 CLI 命令 — `inkflow export`（spec §4）.

分层设计：仅做参数解析/校验、下载 TXT 与落盘，业务经 ensure_kernel() +
InkFlowHTTPClient 调用内核 REST API（Issue #169 CLI 恒经 HTTP；spec §4
「直接消费 service 不经 HTTP」为未同步 F38 的陈旧措辞，按 HTTP 模式实现）。
遵循 F7 §5 全局约定：--json 统一信封 {"ok": true, "data": ...} /
{"ok": false, "error": {"code", "message"}}；退出码 0/1/2/130。

错误码映射（spec §4/§5.3 表 + F7）：
- HttpApiError：404 → NOT_FOUND、其余（含 500 无头）→ INTERNAL_ERROR
  （detail 原样透传）
- KernelStartupError → KERNEL_ERROR
- 写文件失败（OSError 系）在 _impl 内捕获 → DB_ERROR
- 其余异常 → DB_ERROR

项目解析（F1 约定）：数字 / 形如 UUID → 直接当 project_id（GET
/projects/{pid} 取项目名）；否则视为名称 → GET /projects?search= 精确
匹配 items[].name（多个同名取首个），无匹配 → NOT_FOUND 退出 1。

人类可读成功（码点精确，见测试设计假设 7）：
`✅ 导出成功: {name} → {path} ({bytes:,} bytes)`。

依据: specs/f21-export/spec.md §4/§7/§9.1。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.domain.models.output import ExportFormat
from inkflow.domain.services._export_filename import suggest_filename
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

app = typer.Typer(
    name="export",
    help="导出项目（TXT）",
    no_args_is_help=True,
)


@app.callback()
def _export_callback() -> None:
    """export 组回调——保持命令组形态（Typer 单命令提升规避，镜像 audit）."""


def _run_async(coro):
    """同步运行协程（CLI 命令内 asyncio.run）."""
    return asyncio.run(coro)


def _run(cli_ctx: CliContext, coro_fn):
    """执行内核调用并统一映射异常为 F7 错误信封（退出码 1）."""
    try:
        return _run_async(coro_fn())
    except typer.Exit:
        raise
    except HttpApiError as exc:
        code, message = map_http_error(exc.status_code, exc.detail, exc.code)
        print_error(cli_ctx, code, message)
    except KernelStartupError as exc:
        print_error(cli_ctx, "KERNEL_ERROR", f"内核启动失败: {exc}")
    except Exception as e:
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


async def _resolve_project(
    cli_ctx: CliContext,
    client: InkFlowHTTPClient,
    project: str,
) -> tuple[str, str]:
    """解析项目参数为 (project_id 字符串, 项目名)（F1 约定：数字按 ID、名称精确匹配）."""
    if project.isdigit():
        project_obj = await client.get(f"/projects/{int(project)}")
        return str(int(project)), str(project_obj["name"])
    try:
        uuid.UUID(project)
    except ValueError:
        pass
    else:
        pid = uuid.UUID(project)
        project_obj = await client.get(f"/projects/{pid}")
        return str(pid), str(project_obj["name"])
    data = await client.get("/projects", params={"search": project})
    for item in data.get("items", []):
        if item.get("name") == project:
            return str(item["id"]), project
    print_error(cli_ctx, "NOT_FOUND", f"项目不存在: {project}")
    raise typer.Exit(1) from None  # print_error 已退出，此行不可达（静态分析用）


def _resolve_output_path(output: str | None, filename: str) -> Path:
    """输出路径语义（spec §4）：已存在目录 → 目录/文件名；其他 → 文件路径；缺省 → cwd."""
    if output is None:
        return Path.cwd() / filename
    path = Path(output)
    if path.is_dir():
        return path / filename
    return path


@app.command("export")
def export_cmd(
    ctx: typer.Context,
    project: str = typer.Argument(..., help="项目名称或 ID"),
    include_settings: bool = typer.Option(
        False, "--include-settings", help="包含设定档案附录（默认不含）"
    ),
    output: str | None = typer.Option(
        None, "--output", "-o", help="输出路径（目录或文件）；默认当前目录"
    ),
) -> None:
    """导出项目为 TXT 文件。"""
    cli_ctx: CliContext = ctx.obj

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            pid, project_name = await _resolve_project(cli_ctx, client, project)
            txt = await client.get_raw(
                f"/projects/{pid}/export",
                params={"include_settings": "true"} if include_settings else None,
            )
            filename = suggest_filename(project_name, ExportFormat.TXT)
            path = _resolve_output_path(output, filename)
            txt_bytes = txt.encode("utf-8")
            try:
                path.write_bytes(txt_bytes)
            except OSError as exc:
                print_error(cli_ctx, "DB_ERROR", f"写文件失败: {exc}")
                raise typer.Exit(1) from None  # print_error 已退出，此行不可达
            result = {
                "format": ExportFormat.TXT.value,
                "filename": filename,
                "bytes": len(txt_bytes),
                "path": str(path),
            }
            if not cli_ctx.json_output:
                typer.echo(f"✅ 导出成功: {project_name} → {path} ({len(txt_bytes):,} bytes)")
            return result

    result = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, result)
