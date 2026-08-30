"""F16 风格检测 CLI 命令 — `inkflow style analyze`（spec §4.2）.

分层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() + InkFlowHTTPClient
调用内核 REST API（spec §4.2；Issue #169 CLI 恒经 HTTP）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2。

错误码映射（spec §4/§7）：
- HttpApiError：404 → NOT_FOUND、422 → VALIDATION_ERROR、401 → CONFIG_ERROR、
  500 + X-InkFlow-Error-Code: LLM_ERROR → LLM_ERROR、其余 → INTERNAL_ERROR（spec §5.3；
  DB 错误在 HTTP 后折叠为 INTERNAL_ERROR）
- KernelStartupError → KERNEL_ERROR
- pydantic ValidationError / 文本文件缺失 → VALIDATION_ERROR
- 其余异常 → DB_ERROR

人类可读摘要（spec §4.3）：三大板块摘要（风格指纹关键项 + 高频词前 5 +
verdict 中文映射 + 倾向特征逐条 `[特征名] note`）、jieba/LLM 增强表
（板块非 None 时）+ warnings 逐条 + 末尾提示 --json。verdict 中文映射:
likely_human→「倾向人类创作」、「uncertain→「特征不明显」、
likely_ai→「倾向 AI 生成」。分析结论是「结果」而非「执行错误」——
退出码恒 0（spec §4.2）。

依据: specs/f16-style-analysis/spec.md §4/§7/§9。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import typer
from pydantic import ValidationError

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel

app = typer.Typer(
    name="style",
    help="风格检测（文本风格指纹/AI 痕迹/词汇分析）",
    no_args_is_help=True,
)


@app.callback()
def _style_callback() -> None:
    """style 组回调——保持命令组形态（Typer 单命令提升规避，spec §4 命令树）."""


# verdict 枚举 → 人类可读中文标签（spec §4.3 中文映射）.
_VERDICT_LABELS: dict[str, str] = {
    "likely_human": "✅ 倾向人类创作",
    "uncertain": "特征不明显",
    "likely_ai": "⚠ 倾向 AI 生成",
}

# 人类可读摘要高频词条数（spec §4.3: 高频词前 5）.
_TOP_WORDS_LIMIT = 5

# LLM 判定理由摘要截断长度（spec §4.3: reasoning 摘要）.
_REASONING_MAX_CHARS = 40


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


def _verdict_label(verdict: str) -> str:
    """verdict 枚举 → 人类可读中文标签（spec §4.3 映射表）."""
    return _VERDICT_LABELS.get(verdict, verdict)


def _top_words_line(words: list[dict]) -> str:
    """高频词行（spec §4.3: 前 5 个 `词(次数)` 空格连接；超出加省略号）."""
    parts = [f"{w['word']}({w['count']})" for w in words[:_TOP_WORDS_LIMIT]]
    if len(words) > _TOP_WORDS_LIMIT:
        parts.append("…")
    return " ".join(parts)


def _print_human(report: dict) -> None:
    """人类可读摘要（spec §4.3）：三大板块 + jieba/LLM 增强表 + warnings 逐条."""
    fp = report["fingerprint"]
    typer.echo(f"📊 风格分析 (project {report['project_id']}):")
    typer.echo(
        f"   【风格指纹】字数 {fp['char_count']} · 句子 {fp['sentence_count']} · "
        f"平均句长 {fp['avg_sentence_length']} · 段落 {fp['paragraph_count']} · "
        f"平均段落 {fp['avg_paragraph_length']}"
    )
    typer.echo(
        f"   标点密度 {fp['punctuation_density']} · 感叹号 {fp['exclamation_density']} · "
        f"省略号 {fp['ellipsis_density']} · 对话占比 {fp['dialogue_ratio']}"
    )
    typer.echo(
        f"   词汇丰富度 {fp['vocabulary_richness']} · 高频词: {_top_words_line(fp['top_words'])}"
    )
    ai = report["ai_trace"]
    typer.echo(f"   【AI 痕迹】AI 得分 {ai['ai_score']} → {_verdict_label(ai['verdict'])}")
    for feature in ai["features"]:
        typer.echo(f"  [{feature['feature']}] {feature['note']}")
    lex = report["lexical"]
    typer.echo(
        f"   【词汇分析】总词数 {lex['total_words']} · 唯一词 {lex['unique_words']} · "
        f"平均词长 {lex['avg_word_length']} · 停用词占比 {lex['stopword_ratio']}"
    )
    if lex.get("jieba") is not None:
        jieba = lex["jieba"]
        typer.echo(
            f"   【jieba 增强】总词数 {jieba['jieba_total_words']} · "
            f"唯一词 {jieba['jieba_unique_words']} · "
            f"平均词长 {jieba['jieba_avg_word_length']}"
            "（--json 含完整 jieba_top_words）"
        )
    if report.get("llm_assessment") is not None:
        assessment = report["llm_assessment"]
        label = _verdict_label(assessment["llm_verdict"])
        reasoning = assessment["reasoning"]
        if len(reasoning) > _REASONING_MAX_CHARS:
            reasoning = reasoning[:_REASONING_MAX_CHARS] + "…"
        typer.echo(f"   【LLM 深度分析】{label}（{assessment['model']}）——{reasoning}")
    for warning in report.get("warnings", []):
        typer.echo(f"   ⚠ {warning}")
    typer.echo("   完整报告见 inkflow style analyze --json")


# ---------------------------------------------------------------------------
# analyze  — inkflow style analyze --project-id <uuid> [--text|--text-file|--chapters] ...
# ---------------------------------------------------------------------------


@app.command("analyze")
def style_analyze_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    text: str = typer.Option("", "--text", help="待分析文本（与 --text-file/--chapters 互斥）"),
    text_file: str | None = typer.Option(
        None, "--text-file", help="待分析文本文件路径（与 --text 互斥；长文本推荐）"
    ),
    chapters: str | None = typer.Option(
        None,
        "--chapters",
        help="章节 ID 列表（逗号分隔 UUID；与 --text/--text-file 互斥）",
    ),
    llm_analysis: bool | None = typer.Option(
        None,
        "--llm-analysis/--no-llm-analysis",
        help="LLM 深度分析开关（缺席跟随项目配置 style_llm_analysis）",
    ),
) -> None:
    """文本风格分析（只读幂等；--text/--text-file/--chapters 三选一）"""
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
    if not text and text_file is None and chapters is None:
        typer.echo("⚠️ 必须提供 --text/--text-file/--chapters 之一", err=True)
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
        analyze_text: str | None = text if text else None
        if text_file is not None:
            analyze_text = Path(text_file).read_text(encoding="utf-8")
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.post(
                f"/projects/{pid}/style/analyze",
                json={
                    "text": analyze_text,
                    "chapter_ids": [str(c) for c in chapter_ids] if chapter_ids else None,
                    "llm_analysis": llm_analysis,
                },
            )

    report = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, report)
    else:
        _print_human(report)
