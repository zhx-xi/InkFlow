"""F15 一致性审计 CLI 命令 — `inkflow audit check`（spec §4）.

薄层设计：仅做参数解析/校验与结果格式化，全部业务委托 AuditService
（spec §4）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130。

错误码映射（spec §4/§7）:
- ProjectNotFoundError / 无效 UUID → NOT_FOUND
- 其余异常 → DB_ERROR（F15 无 LLM、无输入校验——错误面只有
  NOT_FOUND / DB_ERROR，无 LLM_ERROR / VALIDATION_ERROR）

人类可读摘要（spec §4.2）: 第一行 consistent 结论 + 三级计数；
error/warning 逐条（[级别] 维度: 消息），info 只计数不逐条；
有 findings 时末尾提示 --json 完整报告。发现不一致是「结果」而非
「执行错误」——退出码恒 0（spec §4.1 Q1 拍板 A）。

依据: specs/f15-audit-service/spec.md §4/§7。
"""

from __future__ import annotations

import asyncio
import uuid

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.core.database import async_session_factory, create_tables
from inkflow.domain.models.audit import (
    AuditDimension,
    AuditFinding,
    AuditReport,
    AuditSeverity,
)
from inkflow.domain.ports.audit_errors import ProjectNotFoundError
from inkflow.domain.services.audit_service import AuditService
from inkflow.domain.services.timeline_service import TimelineService
from inkflow.infrastructure.database.repositories.audit_repo import (
    SQLiteAuditRepository,
)
from inkflow.infrastructure.database.repositories.chapter_repo import (
    SQLiteChapterRepository,
)
from inkflow.infrastructure.database.repositories.character_repo import (
    SQLiteCharacterRepository,
)
from inkflow.infrastructure.database.repositories.extraction_run_repo import (
    SQLExtractionRunRepository,
)
from inkflow.infrastructure.database.repositories.foreshadowing_repo import (
    SQLiteForeshadowingRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.database.repositories.timeline_repo import (
    SQLiteTimelineRepository,
)
from inkflow.infrastructure.database.repositories.world_repo import (
    SQLiteWorldRepository,
)

app = typer.Typer(
    name="audit",
    help="一致性审计（角色/时间线/世界/伏笔/跨维度）",
    no_args_is_help=True,
)


@app.callback()
def _audit_callback() -> None:
    """audit 组回调——保持命令组形态（Typer 单命令提升规避，spec §4 命令树）."""


# 维度枚举 → 人类可读中文标签（spec §4.2 人类可读摘要）。
_DIMENSION_LABELS: dict[AuditDimension, str] = {
    AuditDimension.CHARACTER: "角色",
    AuditDimension.TIMELINE: "时间线",
    AuditDimension.WORLD: "世界",
    AuditDimension.FORESHADOWING: "伏笔",
    AuditDimension.CROSS: "跨维度",
}

# counts 键 → 人类可读中文标签（spec §4.2 档案规模观测行）。
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
    """执行服务调用并统一映射领域异常为 F7 错误信封（退出码 1）.

    F15 错误面（spec §4）: ProjectNotFoundError → NOT_FOUND；
    其余异常 → DB_ERROR。
    """
    try:
        return _run_async(coro_fn())
    except typer.Exit:
        raise
    except ProjectNotFoundError as e:
        print_error(cli_ctx, "NOT_FOUND", str(e))
    except Exception as e:  # noqa: BLE001
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


def _build_service(session):
    """构造 AuditService（F15 门面：注入 F1/F2/F9/F10/F12/F13/F14 各仓储 + F12 TimelineService）."""
    project_repo = SQLiteProjectRepository(session)
    return AuditService(
        project_repo=project_repo,
        character_repo=SQLiteCharacterRepository(session),
        world_repo=SQLiteWorldRepository(session),
        timeline_service=TimelineService(
            repository=SQLiteTimelineRepository(session),
            project_repo=project_repo,
        ),
        foreshadowing_repo=SQLiteForeshadowingRepository(session),
        chapter_repo=SQLiteChapterRepository(session),
        run_repo=SQLExtractionRunRepository(session),
        audit_repo=SQLiteAuditRepository(session),
    )


def _dimension_label(finding: AuditFinding) -> str:
    """维度枚举 → 人类可读中文标签（spec §4.2 `[级别] 维度: 消息`）."""
    return _DIMENSION_LABELS.get(finding.dimension, finding.dimension.value)


def _counts_line(report: AuditReport) -> str:
    """档案规模观测行（spec §4.2: 角色 3 · 关系 2 · 事件 6 · 伏笔 2 · 条目 4 · 章节 3）."""
    return " · ".join(f"{_COUNT_LABELS.get(k, k)} {v}" for k, v in report.summary.counts.items())


def _print_human(report: AuditReport) -> None:
    """人类可读摘要（spec §4.2）: error/warning 逐条、info 只计数不逐条."""
    findings = report.findings
    errors = [f for f in findings if f.severity == AuditSeverity.ERROR]
    warnings = [f for f in findings if f.severity == AuditSeverity.WARNING]
    infos = [f for f in findings if f.severity == AuditSeverity.INFO]

    if report.summary.consistent:
        typer.echo(
            f"✅ 审计通过 (project {report.project_id}): "
            f"{len(errors)} error / {len(warnings)} warning / {len(infos)} info"
            f"（{_counts_line(report)}）"
        )
    else:
        typer.echo(
            f"🔍 审计完成 (project {report.project_id}): ❌ 不一致"
            f"（{len(errors)} error / {len(warnings)} warning / {len(infos)} info）"
        )
    for finding in errors + warnings:
        typer.echo(f"  [{finding.severity.value}] {_dimension_label(finding)}: {finding.message}")
    if findings:
        typer.echo(f"（共 {len(findings)} 条发现；完整报告见 inkflow audit check --json）")


# ---------------------------------------------------------------------------
# check  —  inkflow audit check --project-id <uuid> [--json]
# ---------------------------------------------------------------------------


@app.command("check")
def check_audit_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
) -> None:
    """4 维度一致性审计（只读幂等，无副作用）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = _build_service(session)
            return await svc.run_audit(project_id=pid)

    report = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, report.model_dump(mode="json"))
    else:
        _print_human(report)
