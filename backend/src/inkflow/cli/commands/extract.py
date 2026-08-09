"""F14 统一提取 CLI 命令 — `inkflow extract <action>`.

分层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() + InkFlowHTTPClient
调用内核 REST API（spec §4.1；Issue #169 CLI 恒经 HTTP）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130。

错误码映射（spec §4/§7）：
- HttpApiError：404 → NOT_FOUND、422 → VALIDATION_ERROR、401 → CONFIG_ERROR、
  500 + X-InkFlow-Error-Code: LLM_ERROR → LLM_ERROR、其余 → INTERNAL_ERROR（spec §5.3）
- KernelStartupError → KERNEL_ERROR
- pydantic ValidationError / 文本文件缺失 → VALIDATION_ERROR
- 其余异常 → DB_ERROR

run 的 --text/--text-file/--chapters 三选一互斥（同 F9 character extract
先例）；--type 非法值由 Typer Choice 校验 → 退出码 2（spec §7）。

依据: specs/f14-extraction-service/spec.md §4.1/§4.3/§7/§9。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import typer
from pydantic import ValidationError

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.domain.models.extraction import (
    ExtractionRequest,
    ExtractionStatus,
    ExtractionType,
)
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

app = typer.Typer(name="extract", help="统一提取入口（6 种类型）", no_args_is_help=True)


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


def _summarize(result: dict) -> str:
    """提取结果的人类可读摘要（spec §4.3）."""
    if result["status"] == ExtractionStatus.SKIPPED.value:
        reason = result.get("skipped_reason") or "内容未变更"
        return f"⏭ 提取跳过: {result['type']} {reason}，未调用 LLM"
    summary = (
        f"{result['type']} 处理 {result['processed_sources']} 个源"
        f"（跳过 {result['skipped_sources']}），新增 {result['created']} 更新 {result['updated']}"
    )
    if result.get("warnings"):
        summary += f"，警告 {len(result['warnings'])} 条"
    return f"✅ 提取完成: {summary}"


def _status_line(run: dict) -> str:
    """单条 run 记录的人类可读表达（spec §4.3）."""
    if run["status"] == ExtractionStatus.SUCCESS.value:
        tail = f"新增 {run['created_count']} 更新 {run['updated_count']}"
        if run["indexed"]:
            tail += ", 已索引"
        run_at = str(run["run_at"])[:16].replace("T", " ")
        return f"[{run['type']}] {run['source_key']} — ✅ success ({run_at}, {tail})"
    if run["status"] == ExtractionStatus.SKIPPED.value:
        return f"[{run['type']}] {run['source_key']} — ⏭ skipped (内容未变更)"
    return f"[{run['type']}] {run['source_key']} — ❌ error ({run.get('error') or '提取失败'})"


# ---------------------------------------------------------------------------
# run  — inkflow extract run --project-id <uuid> --type <type> [--text|--text-file|--chapters] ...
# ---------------------------------------------------------------------------


@app.command("run")
def extract_run_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    type: ExtractionType = typer.Option(
        ...,
        "--type",
        help="提取类型（character/setting/outline/timeline/foreshadowing/style）",
    ),
    text: str = typer.Option("", "--text", help="待提取文本（与 --text-file/--chapters 互斥）"),
    text_file: str | None = typer.Option(
        None, "--text-file", help="待提取文本文件路径（与 --text 互斥；长文本推荐）"
    ),
    chapters: str | None = typer.Option(
        None,
        "--chapters",
        help="章节 ID 列表（逗号分隔 UUID；与 --text/--text-file 互斥）",
    ),
    prompt: str | None = typer.Option(None, "--prompt", help="outline 生成约束（透传 F11）"),
    num_chapters: int | None = typer.Option(
        None, "--num-chapters", help="outline 规划章节数（1-100）"
    ),
    save: bool = typer.Option(
        True, "--save/--no-save", help="outline 落库开关（--no-save = 仅预览不落库）"
    ),
    auto_extract: bool | None = typer.Option(
        None,
        "--auto-extract/--no-auto-extract",
        help="timeline 设置项覆盖（缺席跟随项目配置 timeline_auto_extract）",
    ),
    model: str | None = typer.Option(
        None, "--model", help="覆盖项目默认模型 (provider/model_name)"
    ),
    index: bool = typer.Option(False, "--index", help="提取成功后自动索引本次产物（RAG）"),
    force: bool = typer.Option(False, "--force", help="忽略增量 skip 强制重跑"),
) -> None:
    """执行统一提取（6 种类型；--text/--text-file/--chapters 三选一）"""
    cli_ctx: CliContext = ctx.obj
    if text and text_file is not None:
        typer.echo("⚠️ --text 与 --text-file 不能同时使用", err=True)
        raise typer.Exit(code=2)
    if text and chapters is not None:
        typer.echo("⚠️ --text 与 --chapters 不能同时使用", err=True)
        raise typer.Exit(code=2)
    if text_file is not None and chapters is not None:
        typer.echo("⚠️ --text-file 与 --chapters 不能同时使用", err=True)
        raise typer.Exit(code=2)
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")
    chapter_ids: list[uuid.UUID] | None = None
    if chapters is not None:
        chapter_ids = [
            _parse_uuid(cli_ctx, part, "章节不存在")
            for part in (p.strip() for p in chapters.split(","))
            if part.strip()
        ]

    async def _impl() -> dict:
        extract_text = text if text else None
        if text_file is not None:
            extract_text = Path(text_file).read_text(encoding="utf-8")
        request = ExtractionRequest(
            project_id=pid,
            type=type,
            text=extract_text,
            chapter_ids=chapter_ids,
            prompt=prompt,
            num_chapters=num_chapters,
            save=save,
            auto_extract=auto_extract,
            model=model,
            index=index,
            force=force,
        )
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post("/extract", json=request.model_dump(mode="json"))

    result = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, result)
    else:
        typer.echo(_summarize(result))


# ---------------------------------------------------------------------------
# status  — inkflow extract status --project-id <uuid> [--type <type>]
# ---------------------------------------------------------------------------


@app.command("status")
def extract_status_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    type: ExtractionType | None = typer.Option(None, "--type", help="按提取类型过滤"),
) -> None:
    """列出项目内各 (type, 源) 的最近一次提取状态（spec §2.3）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(
                f"/projects/{pid}/extractions/runs",
                params={"type": type.value if type else None},
            )

    data = _run(cli_ctx, _impl)
    runs = data.get("items", [])
    total = data.get("total", 0)
    if cli_ctx.json_output:
        print_result(cli_ctx, {"items": runs, "total": total})
        return
    if not runs:
        typer.echo("📥 暂无提取记录")
        return
    typer.echo(f"📋 提取状态（project {pid}）:")
    for run in runs:
        typer.echo(f"  {_status_line(run)}")
