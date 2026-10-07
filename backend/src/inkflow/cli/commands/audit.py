"""F15 一致性审计 CLI 命令 — `inkflow audit check`（spec §4）+ `inkflow audit batch`（f34 §5.8）.

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

依据: specs/f15-consistency-audit/spec.md §4/§7；`batch` 依据 specs/f34-chapter-audit/spec.md
      §4/§5.8（v1.6 #1484——批量编排薄层：不新造执行机制，单章仍走 #1425 的 202 + 后台 + 轮询）。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import typer

from inkflow.cli.commands.audit_chapter import (
    _load_all_chapters,
    _resolve_project_id,
)
from inkflow.cli.commands.audit_chapter import (
    app as audit_chapter_app,
)
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


# ---------------------------------------------------------------------------
# batch  — inkflow audit batch --project-id <pid> [--chapters ...] [--resume]
# ---------------------------------------------------------------------------

# 批量轮询节奏与单章总预算（镜像 audit_chapter 的 #1425 语义；测试 monkeypatch 归零）.
_BATCH_POLL_INTERVAL = 1.0
"""批量轮询间隔秒（测试可 monkeypatch 归零）."""

_BATCH_POLL_TOTAL_TIMEOUT = 900.0
"""单章轮询总预算秒（超时 → 该章记失败清单，不中断整批）."""

_BATCH_LOG_PAGE_SIZE = 100
"""审计记录分页页大小（`GET /projects/{pid}/audit-logs` 端点上限 100，f34 §3.1）."""

_SEVERITIES: tuple[str, ...] = ("error", "warning", "info")
"""严重度视图键序（f34 §6：error < warning < info）."""

_CHECK_TYPES: tuple[str, ...] = (
    "word_count",
    "character_drift",
    "setting_drift",
    "static_consistency",
    "cross_chapter",
    "outline_compliance",
)
"""检查项视图键序（f34 §2.1 六项；未知 check_type 动态追加）."""


@dataclass
class _ChapterResult:
    """单章批量结果（聚合报告的一行）.

    Attributes:
        position: 1-based 章节序号（`order_index` 升序中的位置）.
        chapter_id: 章节 UUID 字符串.
        chapter_title: 章节标题快照.
        run_status: completed / failed / skipped.
        log_id: 审计记录 ID（skipped 为 None）.
        degraded: 该章审计是否降级.
        error: 失败原因（failed 时非空）.
        findings: 该章 findings（failed / skipped 为空）.
    """

    position: int
    chapter_id: str
    chapter_title: str
    run_status: str = "completed"
    log_id: str | None = None
    degraded: bool = False
    error: str = ""
    findings: list[dict] = field(default_factory=list)


def _parse_chapters_range(spec: str) -> set[int]:
    """解析 `--chapters` 序号区间 → 1-based 序号集合（f34 §5.8）.

    Args:
        spec: 逗号分隔的区间串，如 `1-520` / `8` / `1-5,8,10-12`.

    Returns:
        序号集合（去重）。

    Raises:
        ValueError: 区间非法（空段 / 起止倒置 / 起点 < 1 / 非数字）。
    """
    positions: set[int] = set()
    for token in spec.split(","):
        token = token.strip()
        if not token:
            raise ValueError("存在空的区间段")
        if "-" in token:
            start_text, _, end_text = token.partition("-")
            start, end = int(start_text), int(end_text)
            if start < 1 or end < start:
                raise ValueError(f"非法区间: {token}")
            positions.update(range(start, end + 1))
        else:
            value = int(token)
            if value < 1:
                raise ValueError(f"非法序号: {token}")
            positions.add(value)
    if not positions:
        raise ValueError("区间为空")
    return positions


def _severity_counts(findings: list[dict]) -> dict[str, int]:
    """统计 findings 的三级严重度计数（未知取值动态追加，防丢计数）."""
    counts = {severity: 0 for severity in _SEVERITIES}
    for finding in findings:
        severity = str(finding.get("severity", "info"))
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def _severity_summary(findings: list[dict]) -> str:
    """生成 severity 计数摘要（f34 §6 落库口径：`1 error, 2 warnings, 0 info`）."""
    counts = _severity_counts(findings)
    return f"{counts['error']} error, {counts['warning']} warnings, {counts['info']} info"


def _build_report(project_id: str, results: list[_ChapterResult]) -> dict:
    """聚合批量结果（f34 §5.8）——双视图计数 == 各章 findings 之和（计数断言防丢）.

    Args:
        project_id: 项目 UUID 字符串.
        results: 各章结果（含 skipped）.

    Returns:
        聚合报告对象（Markdown / JSON 同源；`chapters` 含每章 findings 明细）。
    """
    by_severity = {severity: 0 for severity in _SEVERITIES}
    by_check_type = {check_type: 0 for check_type in _CHECK_TYPES}
    findings_total = 0
    for result in results:
        for finding in result.findings:
            findings_total += 1
            severity = str(finding.get("severity", "info"))
            by_severity[severity] = by_severity.get(severity, 0) + 1
            check_type = str(finding.get("check_type", ""))
            by_check_type[check_type] = by_check_type.get(check_type, 0) + 1
    ordered = sorted(results, key=lambda item: item.position)
    return {
        "project_id": project_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "selected": len(ordered),
        "audited": sum(1 for item in ordered if item.run_status == "completed"),
        "failed": sum(1 for item in ordered if item.run_status == "failed"),
        "skipped": sum(1 for item in ordered if item.run_status == "skipped"),
        "findings_total": findings_total,
        "by_severity": by_severity,
        "by_check_type": by_check_type,
        "chapters": [
            {
                "position": item.position,
                "chapter_id": item.chapter_id,
                "chapter_title": item.chapter_title,
                "log_id": item.log_id,
                "run_status": item.run_status,
                "degraded": item.degraded,
                "severity_summary": _severity_summary(item.findings),
                "findings": item.findings,
            }
            for item in ordered
        ],
        "failures": [
            {
                "position": item.position,
                "chapter_id": item.chapter_id,
                "chapter_title": item.chapter_title,
                "log_id": item.log_id,
                "error": item.error,
            }
            for item in ordered
            if item.run_status == "failed"
        ],
        "skipped_chapters": [
            {
                "position": item.position,
                "chapter_id": item.chapter_id,
                "chapter_title": item.chapter_title,
            }
            for item in ordered
            if item.run_status == "skipped"
        ],
    }


def _render_markdown(report: dict) -> str:
    """渲染聚合报告的 Markdown 清单（f34 §5.8：双视图归类 + 章节/失败/跳过清单）."""
    lines = [
        "# 批量章节审计报告",
        "",
        f"- 项目: {report['project_id']}",
        f"- 生成时间: {report['generated_at']}",
        f"- 选中章节: {report['selected']}",
        f"- 已完成: {report['audited']} / 失败: {report['failed']} / 跳过: {report['skipped']}",
        f"- findings 合计: {report['findings_total']}",
        "",
        "## 按严重度归类",
        "",
        "| 严重度 | 条目数 |",
        "|--------|--------|",
    ]
    for severity in _SEVERITIES:
        lines.append(f"| {severity} | {report['by_severity'].get(severity, 0)} |")
    lines += ["", "## 按检查项归类", "", "| 检查项 | 条目数 |", "|--------|--------|"]
    for check_type, count in report["by_check_type"].items():
        lines.append(f"| {check_type} | {count} |")
    lines += [
        "",
        "## 章节清单",
        "",
        "| # | 章节 | 状态 | error | warning | info |",
        "|---|------|------|-------|---------|------|",
    ]
    for chapter in report["chapters"]:
        counts = _severity_counts(chapter["findings"])
        lines.append(
            f"| {chapter['position']} | {chapter['chapter_title']} | {chapter['run_status']} "
            f"| {counts['error']} | {counts['warning']} | {counts['info']} |"
        )
    if report["failures"]:
        lines += [
            "",
            "## 失败章节",
            "",
            "| # | 章节 | log_id | 错误 |",
            "|---|------|--------|------|",
        ]
        for failure in report["failures"]:
            lines.append(
                f"| {failure['position']} | {failure['chapter_title']} "
                f"| {failure['log_id']} | {failure['error']} |"
            )
    if report["skipped_chapters"]:
        lines += ["", "## 跳过章节（--resume）", "", "| # | 章节 |", "|---|------|"]
        for skipped in report["skipped_chapters"]:
            lines.append(f"| {skipped['position']} | {skipped['chapter_title']} |")
    return "\n".join(lines) + "\n"


def _write_reports(cli_ctx: CliContext, out_path: Path, report: dict) -> None:
    """落盘聚合报告（Markdown 写 `out_path`、JSON 写同主名 `.json`）.

    Args:
        cli_ctx: CLI 上下文（错误信封）.
        out_path: Markdown 报告落点.
        report: 聚合报告对象.

    Raises:
        typer.Exit: 写入失败（退出 1）。
    """
    json_path = out_path.with_suffix(".json")
    try:
        out_path.write_text(_render_markdown(report), encoding="utf-8")
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        print_error(cli_ctx, "INTERNAL_ERROR", f"报告写入失败（{out_path}）: {exc}")


async def _load_completed_chapter_ids(client: InkFlowHTTPClient, pid: uuid.UUID) -> set[str]:
    """断点依据：项目 audit_logs 中 `run_status='completed'` 的章节 id 集合（分页全量）.

    **不新建进度表**（f34 §5.8 拍板）——已完成判定完全复用既有审计记录。

    Args:
        client: 内核 HTTP 客户端.
        pid: 项目 UUID.

    Returns:
        已完成章节的 id 字符串集合（`failed` / `running` 不计入）。
    """
    done: set[str] = set()
    offset = 0
    while True:
        data = await client.get(
            f"/projects/{pid}/audit-logs",
            params={"offset": offset, "limit": _BATCH_LOG_PAGE_SIZE},
        )
        logs = list(data.get("logs", []))
        for log in logs:
            if log.get("run_status") == "completed" and log.get("chapter_id"):
                done.add(str(log["chapter_id"]))
        if not logs:
            break
        offset += len(logs)
        if offset >= int(data.get("total", 0) or 0):
            break
    return done


async def _poll_status(client: InkFlowHTTPClient, log_id: str) -> dict:
    """轮询审计任务至终态（镜像 audit_chapter #1425；超时按 failed 收口）.

    Args:
        client: 内核 HTTP 客户端.
        log_id: 审计记录 ID.

    Returns:
        终态读口响应；轮询超总预算 → 合成 `run_status='failed'` + error。
    """
    deadline = time.monotonic() + _BATCH_POLL_TOTAL_TIMEOUT
    while True:
        info: dict = await client.get(f"/audit-logs/{log_id}/status")
        if info.get("run_status") != "running":
            return info
        if time.monotonic() >= deadline:
            return {"run_status": "failed", "error": f"轮询超时未完成（log_id: {log_id}）"}
        await asyncio.sleep(_BATCH_POLL_INTERVAL)


async def _audit_one(
    client: InkFlowHTTPClient,
    pid: uuid.UUID,
    index: int,
    total: int,
    position: int,
    item: dict,
) -> _ChapterResult:
    """审计单章（派发 202 → 轮询终态 → 取明细）——**失败不外抛**（f34 §5.8）.

    任一环节异常（HTTP/轮询超时/明细读取）→ 该章记 `run_status='failed'` + error，
    **不中断整批**（批次退出码不受影响）。

    Args:
        client: 内核 HTTP 客户端.
        pid: 项目 UUID.
        index: 当前进度序号（1-based，进度行用）.
        total: 本批待审计章数（进度行用）.
        position: 章节序号（1-based）.
        item: 章节 JSON（至少含 id / title）.

    Returns:
        该章结果（completed / failed）。
    """
    cid = str(item.get("id", ""))
    title = str(item.get("title", ""))
    prefix = f"[{index}/{total}] {title}"
    log_id: str | None = None
    try:
        submitted = await client.post(
            f"/projects/{pid}/chapters/{cid}/audit",
            json={"include_static": True},
            # #926 覆盖沿用（与 audit chapter 同一端点同款）：202 受理本身瞬时，
            # 但旧内核（同步语义）会阻塞至审计完成——300s 覆盖保住兼容面。
            timeout=LLM_TASK_TIMEOUT,
        )
        log_id = str(submitted["log_id"]) if submitted.get("log_id") else None
        run_status = str(submitted.get("status", "running"))
        error = ""
        # 幂等复用（#1425）已返回 completed → 不轮询，直接取明细.
        if run_status == "running" and log_id is not None:
            info = await _poll_status(client, log_id)
            run_status = str(info.get("run_status", "failed"))
            error = str(info.get("error", "") or "")
        if run_status == "failed" or log_id is None:
            error = error or "审计任务失败（run_status=failed）"
            typer.echo(f"{prefix} … failed: {error}", err=True)
            return _ChapterResult(
                position=position,
                chapter_id=cid,
                chapter_title=title,
                run_status="failed",
                log_id=log_id,
                error=error,
            )
        detail: dict = await client.get(f"/audit-logs/{log_id}")
        findings = [found for found in detail.get("findings", []) if isinstance(found, dict)]
        typer.echo(f"{prefix} … completed ({_severity_summary(findings)})", err=True)
        return _ChapterResult(
            position=position,
            chapter_id=cid,
            chapter_title=title,
            run_status="completed",
            log_id=log_id,
            degraded=bool(detail.get("degraded", False)),
            findings=findings,
        )
    except typer.Exit:
        raise
    except Exception as exc:  # 单章失败不中断整批（f34 §5.8）
        typer.echo(f"{prefix} … failed: {exc}", err=True)
        return _ChapterResult(
            position=position,
            chapter_id=cid,
            chapter_title=title,
            run_status="failed",
            log_id=log_id,
            error=f"{type(exc).__name__}: {exc}",
        )


@app.command("batch")
@instrument(caller_type="cli")
def batch_audit_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", "-p", help="项目名称或 ID"),
    chapters: str | None = typer.Option(
        None,
        "--chapters",
        help="章节序号区间（1-based，如 1-520 / 1-5,8,10-12；省略 = 全部章节）",
    ),
    resume: bool = typer.Option(
        False, "--resume", help="断点续跑：跳过 audit_logs 中 run_status=completed 的章节"
    ),
    concurrency: int = typer.Option(
        1, "--concurrency", help="并发章数（默认 1 = 串行，LLM 限流友好）"
    ),
    out: str | None = typer.Option(
        None, "--out", help="报告落点（Markdown；JSON 写同主名 .json；省略 = 只打印 stdout）"
    ),
) -> None:
    """批量章节审计（枚举/区间 → 逐章派发 + 轮询 → 聚合报告；f34 §4/§5.8）.

    编排薄层：单章执行仍走 #1425 的 202 受理 + 后台执行 + 轮询，本命令不新增端点。
    单章失败不中断整批（记入报告失败清单，退出码仍 0）；批次级错误退出 1；用法错误退出 2。
    """
    cli_ctx: CliContext = ctx.obj
    positions: set[int] | None = None
    if chapters is not None:
        try:
            positions = _parse_chapters_range(chapters)
        except ValueError as exc:
            typer.echo(f"⚠️ --chapters 区间非法（{chapters}）: {exc}", err=True)
            raise typer.Exit(code=2) from None
    if concurrency < 1:
        typer.echo(f"⚠️ --concurrency 必须 ≥ 1，收到: {concurrency}", err=True)
        raise typer.Exit(code=2) from None

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            pid = await _resolve_project_id(client, cli_ctx, project_id)
            raw = await _load_all_chapters(client, pid)
            selected = [(index + 1, item) for index, item in enumerate(raw)]
            if positions is not None:
                selected = [(pos, item) for pos, item in selected if pos in positions]
            if not selected:
                print_error(
                    cli_ctx,
                    "NOT_FOUND",
                    f"无匹配章节（--project-id {project_id} / --chapters {chapters}）",
                )

            done_ids: set[str] = set()
            if resume:
                done_ids = await _load_completed_chapter_ids(client, pid)
            todo = [(pos, item) for pos, item in selected if str(item.get("id")) not in done_ids]
            skipped = [
                _ChapterResult(
                    position=pos,
                    chapter_id=str(item.get("id", "")),
                    chapter_title=str(item.get("title", "")),
                    run_status="skipped",
                )
                for pos, item in selected
                if str(item.get("id")) in done_ids
            ]

            semaphore = asyncio.Semaphore(concurrency)
            total = len(todo)

            async def _one(index: int, pos: int, item: dict) -> _ChapterResult:
                async with semaphore:
                    return await _audit_one(client, pid, index, total, pos, item)

            audited = list(
                await asyncio.gather(
                    *[_one(index + 1, pos, item) for index, (pos, item) in enumerate(todo)]
                )
            )
            return _build_report(str(pid), audited + skipped)

    report = _run(cli_ctx, _impl)
    out_path = Path(out) if out else None
    if out_path is not None:
        _write_reports(cli_ctx, out_path, report)
    if cli_ctx.json_output:
        print_result(cli_ctx, report)
    elif out_path is not None:
        typer.echo(f"✅ 报告已写入 {out_path} 与 {out_path.with_suffix('.json')}")
        typer.echo(
            f"   选中 {report['selected']} 章 / 已完成 {report['audited']} / "
            f"失败 {report['failed']} / 跳过 {report['skipped']} / "
            f"findings {report['findings_total']}"
        )
    else:
        typer.echo(_render_markdown(report))
