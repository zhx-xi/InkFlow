"""F15 一致性审计 CLI 命令 — `inkflow audit check`（spec §4）.

分层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() + InkFlowHTTPClient
调用内核 REST API（spec §4；Issue #169 CLI 恒经 HTTP）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130。

错误码映射（spec §4/§7）：
- HttpApiError：404 → NOT_FOUND、422 → VALIDATION_ERROR、401 → CONFIG_ERROR、
  500 + LLM_ERROR 头 → LLM_ERROR、其余 → INTERNAL_ERROR（spec §5.3；
  DB 错误在 HTTP 后折叠为 INTERNAL_ERROR）
- KernelStartupError → KERNEL_ERROR
- 其余异常 → DB_ERROR

人类可读摘要（spec §4.2）：第一行 consistent 结论 + 三级计数；
error/warning 逐条（[级别] 维度: 消息），info 只计数不逐条，
有 findings 时末尾提示 --json 完整报告。发现不一致是「结果」而非
「执行错误」——退出码恒 0（spec §4.1 Q1 拍板 A）。

依据: specs/f15-consistency-audit/spec.md §4/§7。
"""

from __future__ import annotations

import asyncio
import uuid

import typer

from inkflow.cli.commands.audit_chapter import app as audit_chapter_app
from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel
from inkflow.logging import instrument

app = typer.Typer(
    name="audit",
    help="一致性审计（角色/时间线/世界/伏笔/跨维度）",
    no_args_is_help=True,
)


@app.callback()
def _audit_callback() -> None:
    """audit 组回调——保持命令组形态（Typer 单命令提升规避，spec §4 命令树）."""


# F34 章节审计子组（spec §4: inkflow audit chapter ...，v1.1 --confirm/--history）
app.add_typer(audit_chapter_app)


# 维度枚举 → 人类可读中文标签（spec §4.2 人类可读摘要）.
_DIMENSION_LABELS: dict[str, str] = {
    "character": "角色",
    "timeline": "时间线",
    "world": "世界",
    "foreshadowing": "伏笔",
    "cross": "跨维度",
}

# counts 键 → 人类可读中文标签（spec §4.2 档案规模观测行）.
_COUNT_LABELS: dict[str, str] = {
    "characters": "角色",
    "relations": "关系",
    "groups": "分组",
    "world_settings": "条目",
    "events": "事件",
    "foreshadowings": "伏笔",
    "chapters": "章节",
    "extraction_runs": "提取",
}


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
    except Exception as e:
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


def _dimension_label(finding: dict) -> str:
    """维度枚举 → 人类可读中文标签（spec §4.2 `[级别] 维度: 消息`）."""
    dim = finding.get("dimension")
    return _DIMENSION_LABELS.get(dim, dim) if isinstance(dim, str) else str(dim)


def _counts_line(report: dict) -> str:
    """档案规模观测行（spec §4.2: 角色 3 · 关系 2 · 事件 6 · 伏笔 2 · 条目 4 · 章节 3）."""
    return "  · ".join(
        f"{_COUNT_LABELS.get(k, k)} {v}" for k, v in report["summary"]["counts"].items()
    )


def _print_human(report: dict) -> None:
    """人类可读摘要（spec §4.2）：error/warning 逐条、info 只计数不逐条."""
    findings = report["findings"]
    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    infos = [f for f in findings if f["severity"] == "info"]

    if report["summary"]["consistent"]:
        typer.echo(
            f"✅ 审计通过 (project {report['project_id']}): "
            f"{len(errors)} error / {len(warnings)} warning / {len(infos)} info"
            f"（{_counts_line(report)}）"
        )
    else:
        typer.echo(
            f"📊 审计完成 (project {report['project_id']}): ❌ 不一致"
            f"（{len(errors)} error / {len(warnings)} warning / {len(infos)} info）"
        )
    for finding in errors + warnings:
        typer.echo(f"  [{finding['severity']}] {_dimension_label(finding)}: {finding['message']}")
    if findings:
        typer.echo(f"（共 {len(findings)} 条发现；完整报告见 inkflow audit check --json）")


# ---------------------------------------------------------------------------
# check  — inkflow audit check --project-id <uuid> [--json]
# ---------------------------------------------------------------------------


@app.command("check")
@instrument(caller_type="cli")
def check_audit_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
) -> None:
    """4 维度一致性审计（只读幂等，无副作用）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get(f"/projects/{pid}/audit")

    report = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, report)
    else:
        _print_human(report)
