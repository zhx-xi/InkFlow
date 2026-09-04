"""F28 Agent Memory CLI — `inkflow memory <action>`.

薄层设计：仅做参数解析/校验与结果格式化，业务经 ensure_kernel() +
InkFlowHTTPClient 调用内核 REST API（spec §4.1；Issue #169 CLI 恒经 HTTP）。
错误映射（F38 §5.3）：HttpApiError 404/422 等 → stderr「❌ {detail}」+ 退出码 1；
KernelStartupError → 「❌ 内核启动失败: ...」+ 退出码 1。
"""

from __future__ import annotations

import asyncio
import json
import sys

import typer

from inkflow.infrastructure.http import (
    LLM_TASK_TIMEOUT,
    HttpApiError,
    InkFlowHTTPClient,
    map_http_error,
)
from inkflow.infrastructure.kernel import KernelStartupError, ensure_kernel
from inkflow.logging import instrument

app = typer.Typer(name="memory", help="Agent 记忆管理", no_args_is_help=True)

# 偏好分类中文标签映射（spec §3.2；展示辅助——列表行方括号保留原始 key 供脚本消费）
_CATEGORY_LABELS = {
    "addressing": "称呼习惯",
    "style_word": "风格用词",
    "structure": "结构偏好",
    "other": "其他",
}

_CATEGORY_FILTER_HELP = "偏好分类过滤: " + " | ".join(
    f"{k}({v})" for k, v in _CATEGORY_LABELS.items()
)


def _run_async(coro):
    return asyncio.run(coro)


def _print_json_envelope(data) -> None:
    """--json 信封输出（F27 契约: {"ok": true, "data": <API 响应原样>}）."""
    json.dump({"ok": True, "data": data}, sys.stdout, ensure_ascii=False, indent=2)
    print()


def _run(coro_fn):
    """执行内核调用并映射 HTTP 异常 → stderr「❌ {detail}」+ 退出码 1."""
    try:
        return _run_async(coro_fn())
    except HttpApiError as exc:
        _, message = map_http_error(exc.status_code, exc.detail, exc.code)
        typer.echo(f"❌ {message}", err=True)
        raise typer.Exit(code=1) from exc
    except KernelStartupError as exc:
        typer.echo(f"❌ 内核启动失败: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("list")
@instrument(caller_type="cli")
def memory_list(
    project_id: str = typer.Option(..., "--project-id", help="项目 ID（UUID）"),
    category: str | None = typer.Option(
        None,
        "--category",
        help=_CATEGORY_FILTER_HELP,
    ),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """列出项目已学偏好"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            params: dict[str, object] = {"project_id": project_id}
            if category:
                params["category"] = category
            return await client.get("/agent/preferences", params=params)

    data = _run(_impl)
    if data is None:
        return
    if json_output:
        _print_json_envelope(data)
        return
    items = data.get("items") or []
    typer.echo(f"共 {data.get('total', len(items))} 条已学偏好")
    for pref in items:
        typer.echo(
            f"[{pref['category']}] {pref['pattern']} "
            f"(confidence {pref['confidence']}, ×{pref['count']})"
        )


@app.command("remove")
@instrument(caller_type="cli")
def memory_remove(
    preference_id: str = typer.Argument(..., help="偏好 ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """删除已学偏好（立即停止注入）"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.delete(f"/agent/preferences/{preference_id}")

    data = _run(_impl)
    if data is None:
        return
    if json_output:
        _print_json_envelope(data)
        return
    typer.echo("✅ 已删除偏好（下次生成立即停止注入）")


@app.command("stats")
@instrument(caller_type="cli")
def memory_stats(
    project_id: str = typer.Option(..., "--project-id", help="项目 ID（UUID）"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """查看项目记忆学习统计（修改率/重新生成率 + 基线对照）"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.get("/agent/memory/stats", params={"project_id": project_id})

    data = _run(_impl)
    if data is None:
        return
    if json_output:
        _print_json_envelope(data)
        return
    agentic = data.get("agentic") or {}
    modify_rate = agentic.get("modify_rate")
    regenerate_rate = agentic.get("regenerate_rate")
    baseline_ref = data.get("baseline_ref")
    typer.echo(f"已学习偏好: {data.get('learned_preferences', 0)} 条")
    user_prefs = data.get("user_preferences")
    if user_prefs:
        user_pref_count = user_prefs.get("count", 0)
        user_pref_projects = user_prefs.get("projects", 0)
        typer.echo(f"用户级偏好: {user_pref_count} 条（跨 {user_pref_projects} 项目）")
    if modify_rate is None:
        typer.echo("修改率: N/A（无修改数据）")
    else:
        typer.echo(f"修改率: {modify_rate:.0%}")
    if regenerate_rate is None:
        typer.echo("重新生成率: N/A（无重新生成数据）")
    else:
        typer.echo(f"重新生成率: {regenerate_rate:.0%}")
    if modify_rate is None or not baseline_ref:
        typer.echo("基线对照: N/A（无修改率数据）")
    else:
        typer.echo(f"基线对照: {baseline_ref}")


@app.command("user-list")
@instrument(caller_type="cli")
def memory_user_list(
    category: str | None = typer.Option(
        None,
        "--category",
        help=_CATEGORY_FILTER_HELP,
    ),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """列出用户级偏好（全局跨项目，M1）"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            params: dict[str, object] = {}
            if category:
                params["category"] = category
            return await client.get("/agent/user-preferences", params=params)

    data = _run(_impl)
    if data is None:
        return
    if json_output:
        _print_json_envelope(data)
        return
    items = data.get("items") or []
    typer.echo(f"共 {data.get('total', len(items))} 条用户级偏好")
    for pref in items:
        typer.echo(
            f"[{pref['category']}] {pref['pattern']} → {pref['value']} "
            f"(confidence {pref['confidence']}, ×{pref['count']}, {pref['project_count']} 项目)"
        )


@app.command("user-remove")
@instrument(caller_type="cli")
def memory_user_remove(
    preference_id: str = typer.Argument(..., help="用户级偏好 ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """删除用户级偏好（所有项目立即停止注入，M1）"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            return await client.delete(f"/agent/user-preferences/{preference_id}")

    data = _run(_impl)
    if data is None:
        return
    if json_output:
        _print_json_envelope(data)
        return
    typer.echo("✅ 已删除用户级偏好（所有项目生成立即停止注入）")

@app.command("summarize")
@instrument(caller_type="cli")
def memory_summarize(
    project_id: str = typer.Option(..., "--project-id", help="项目 ID（UUID）"),
    force: bool = typer.Option(False, "--force", help="忽略锚点哈希强制重新总结"),
    remove: bool = typer.Option(False, "--remove", help="删除语义总结（替代总结动作）"),
    json_output: bool = typer.Option(False, "--json", help="JSON 格式输出"),
) -> None:
    """手动触发语义总结（M2，spec §4.1）"""

    async def _impl() -> dict:
        handle = await ensure_kernel()
        client = InkFlowHTTPClient(handle)
        async with client:
            if remove:
                return await client.delete(
                    "/agent/memory/summaries",
                    params={"project_id": project_id},
                )
            return await client.post(
                "/agent/memory/summarize",
                params={"project_id": project_id, "force": force},
                timeout=LLM_TASK_TIMEOUT,
            )

    data = _run(_impl)
    if data is None:
        return
    if json_output:
        _print_json_envelope(data)
        return
    if remove:
        typer.echo("✅ 已删除语义总结")
        return
    project = data.get("project")
    user = data.get("user")
    summarized = data.get("summarized")
    if not summarized and not project and not user:
        typer.echo("ℹ️ 锚点未变化，复用既有摘要（--force 强制重新总结）")
        return
    if project and project.get("anchor_count") is not None:
        typer.echo(f"✅ 已生成项目级风格摘要（{project.get('anchor_count')} 锚点）")
    else:
        typer.echo("ℹ️ 项目级锚点未变化，复用既有摘要（--force 强制重新总结）")
    if user and user.get("anchor_count") is not None:
        typer.echo(f"✅ 已生成用户级风格摘要（{user.get('anchor_count')} 锚点）")
    else:
        typer.echo("ℹ️ 用户级锚点未变化，复用既有摘要（--force 强制重新总结）")
