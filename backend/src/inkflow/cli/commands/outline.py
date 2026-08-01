"""F11 大纲管理 CLI 命令 — `inkflow outline <action>` + `outline point <action>`
+ `outline arc <action>` + `outline generate`.

薄层设计：仅做参数解析/校验与结果格式化，全部业务委托 OutlineService
（spec §4）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130；删除类命令二次确认 + --force；
--json + 无 --force 的删除 → VALIDATION_ERROR。

错误码映射（spec §4/§7）:
- OutlineServiceError 子类（同名大纲/弧线、弧线跨项目等）→ VALIDATION_ERROR
- OutlineNotFoundError / PlotPointNotFoundError / StoryArcNotFoundError /
  ProjectNotFoundError / 无效 UUID → NOT_FOUND
- OutlineGenerationError / LLMRequestError → LLM_ERROR
- 其余异常 → DB_ERROR

依据: specs/f11-outline-service/spec.md §4/§4.5/§7。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import typer
from pydantic import ValidationError

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.core.database import async_session_factory, create_tables
from inkflow.domain.models.outline import (
    Outline,
    OutlineGenerateRequest,
    OutlineGenerationResult,
    OutlineUpdate,
    PlotPoint,
    PlotPointUpdate,
    StoryArc,
    StoryArcUpdate,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.outline_errors import (
    OutlineGenerationError,
    OutlineNotFoundError,
    OutlineServiceError,
    PlotPointNotFoundError,
    ProjectNotFoundError,
    StoryArcNotFoundError,
)
from inkflow.domain.services._outline_generator import OutlineGenerator
from inkflow.domain.services.outline_service import OutlineService
from inkflow.infrastructure.database.repositories.outline_repo import (
    SQLiteOutlineRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager

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
    """执行服务调用并统一映射领域异常为 F7 错误信封（退出码 1）."""
    try:
        return _run_async(coro_fn())
    except typer.Exit:
        raise
    except (
        OutlineNotFoundError,
        PlotPointNotFoundError,
        StoryArcNotFoundError,
        ProjectNotFoundError,
    ) as e:
        print_error(cli_ctx, "NOT_FOUND", str(e))
    except OutlineGenerationError as e:
        print_error(cli_ctx, "LLM_ERROR", str(e))
    except LLMRequestError:
        print_error(cli_ctx, "LLM_ERROR", "LLM 调用失败，请稍后重试")
    except OutlineServiceError as e:
        print_error(cli_ctx, "VALIDATION_ERROR", str(e))
    except ValidationError as e:
        messages = "; ".join(str(err.get("msg", "")) for err in e.errors())
        print_error(cli_ctx, "VALIDATION_ERROR", messages or "参数校验失败")
    except FileNotFoundError as e:
        print_error(cli_ctx, "VALIDATION_ERROR", f"文本文件不存在: {e.filename}")
    except Exception as e:  # noqa: BLE001
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


def _outline_to_dict(outline: Outline) -> dict:
    """大纲领域模型 → JSON-safe dict."""
    return outline.model_dump(mode="json")


def _point_to_dict(point: PlotPoint) -> dict:
    """情节点领域模型 → JSON-safe dict."""
    return point.model_dump(mode="json")


def _arc_to_dict(arc: StoryArc) -> dict:
    """弧线领域模型 → JSON-safe dict."""
    return arc.model_dump(mode="json")


def _make_service(session):
    """构造 OutlineService（含生成管线依赖），供各命令复用."""
    repo = SQLiteOutlineRepository(session)
    return OutlineService(
        repository=repo,
        generator=OutlineGenerator(
            llm_client=LangChainLLMClient(),
            prompt_manager=LangChainPromptManager(),
            repository=repo,
        ),
        project_repo=SQLiteProjectRepository(session),
    )


# ---------------------------------------------------------------------------
# create  —  inkflow outline create --project-id <uuid> --name <str> ...
# ---------------------------------------------------------------------------


@app.command("create")
def create_outline_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    name: str = typer.Option(..., "--name", "-n", help="大纲名"),
    description: str = typer.Option("", "--description", "-d", help="大纲总体描述"),
    sort_order: int = typer.Option(0, "--sort-order", help="排序权重（小者在前）"),
) -> None:
    """创建大纲"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.create_outline(
                project_id=pid,
                name=name,
                description=description,
                sort_order=sort_order,
            )

    outline = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _outline_to_dict(outline))
    else:
        typer.echo(f"✅ 大纲创建成功: [{outline.name}]")


# ---------------------------------------------------------------------------
# list  —  inkflow outline list --project-id <uuid> [--search] ...
# ---------------------------------------------------------------------------


@app.command("list")
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

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.list_outlines(
                project_id=pid,
                search=search,
                sort_by=sort,
                sort_desc=sort_desc,
                offset=offset,
                limit=limit,
            )

    outlines, total = _run(cli_ctx, _impl)
    if not outlines and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无大纲")
        return
    if not cli_ctx.json_output and total:
        print_result(cli_ctx, f"共 {total} 个大纲")
    print_result(cli_ctx, [_outline_to_dict(o) for o in outlines])


# ---------------------------------------------------------------------------
# get  —  inkflow outline get --id <uuid>
# ---------------------------------------------------------------------------


@app.command("get")
def get_outline_cmd(
    ctx: typer.Context,
    outline_id: str = typer.Option(..., "--id", "-i", help="大纲 ID (UUID)"),
) -> None:
    """查看大纲详情"""
    cli_ctx: CliContext = ctx.obj
    oid = _parse_uuid(cli_ctx, outline_id, "大纲不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.get_outline(outline_id=oid)

    outline = _run(cli_ctx, _impl)
    if outline is None:
        print_error(cli_ctx, "NOT_FOUND", "大纲不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _outline_to_dict(outline))
    else:
        typer.echo(f"ID:         {outline.id}")
        typer.echo(f"名称:       {outline.name}")
        typer.echo(f"描述:       {outline.description}")
        typer.echo(f"排序:       {outline.sort_order}")
        typer.echo(f"创建时间:   {outline.created_at}")
        typer.echo(f"更新时间:   {outline.updated_at}")


# ---------------------------------------------------------------------------
# update  —  inkflow outline update --id <uuid> [--name] [--sort-order] ...
# ---------------------------------------------------------------------------


@app.command("update")
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

    async def _impl():
        update_fields: dict[str, object] = {}
        if name is not None:
            update_fields["name"] = name
        if description is not None:
            update_fields["description"] = description
        if sort_order is not None:
            update_fields["sort_order"] = sort_order
        update = OutlineUpdate(**update_fields)
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.update_outline(outline_id=oid, update=update)

    outline = _run(cli_ctx, _impl)
    if outline is None:
        print_error(cli_ctx, "NOT_FOUND", "大纲不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _outline_to_dict(outline))
    else:
        typer.echo(f"✅ 大纲已更新: [{outline.name}]")


# ---------------------------------------------------------------------------
# delete  —  inkflow outline delete --id <uuid> [--force] [--permanent]
# ---------------------------------------------------------------------------


@app.command("delete")
def delete_outline_cmd(
    ctx: typer.Context,
    outline_id: str = typer.Option(..., "--id", "-i", help="大纲 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
    permanent: bool = typer.Option(False, "--permanent", "-p", help="硬删除（物理删除）"),
) -> None:
    """删除大纲（默认软删除并级联其情节点；--permanent 物理删除）"""
    cli_ctx: CliContext = ctx.obj
    oid = _parse_uuid(cli_ctx, outline_id, "大纲不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        label = "永久删除" if permanent else "删除"
        if not typer.confirm(f"确定要{label}大纲 #{outline_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.delete_outline(outline_id=oid, force=permanent)

    ok = _run(cli_ctx, _impl)
    if ok:
        label = "永久删除" if permanent else "已删除"
        if cli_ctx.json_output:
            print_result(cli_ctx, {"id": str(oid), "deleted": True})
        else:
            typer.echo(f"✅ 大纲 #{outline_id} {label}")
    else:
        print_error(cli_ctx, "NOT_FOUND", "大纲不存在")


# ---------------------------------------------------------------------------
# restore  —  inkflow outline restore --id <uuid>
# ---------------------------------------------------------------------------


@app.command("restore")
def restore_outline_cmd(
    ctx: typer.Context,
    outline_id: str = typer.Option(..., "--id", "-i", help="大纲 ID (UUID)"),
) -> None:
    """恢复已删除的大纲（级联恢复其情节点）"""
    cli_ctx: CliContext = ctx.obj
    oid = _parse_uuid(cli_ctx, outline_id, "大纲不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.restore_outline(outline_id=oid)

    outline = _run(cli_ctx, _impl)
    if outline is None:
        print_error(cli_ctx, "NOT_FOUND", "大纲不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _outline_to_dict(outline))
    else:
        typer.echo(f"✅ 大纲已恢复: [{outline.name}]")


# ---------------------------------------------------------------------------
# generate  —  inkflow outline generate --project-id <uuid> [--prompt] ...
# ---------------------------------------------------------------------------


@app.command("generate")
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

    async def _impl():
        gen_prompt = prompt
        if prompt_file is not None:
            gen_prompt = Path(prompt_file).read_text(encoding="utf-8")
        request = OutlineGenerateRequest(
            project_id=pid,
            name=name,
            prompt=gen_prompt,
            num_chapters=num_chapters,
            save=save,
            model=model,
        )
        await create_tables()
        async with async_session_factory() as session:
            svc = _make_service(session)
            return await svc.generate(request)

    result: OutlineGenerationResult = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, result.model_dump(mode="json"))
    else:
        if result.saved:
            outline_name = result.outline.name if result.outline else (name or "未命名大纲")
            typer.echo(
                f"✅ 大纲生成并保存: [{outline_name}]，含 {len(result.plot_points)} 个情节点、"
                f"{len(result.arcs)} 条弧线"
            )
        else:
            n_points = len(result.preview.plot_points) if result.preview else 0
            n_arcs = len(result.preview.arcs) if result.preview else 0
            typer.echo(
                f"🔍 大纲预览（未保存）: {n_points} 个情节点、{n_arcs} 条弧线 "
                "—— 使用 --save 保存后落库"
            )
        if result.warnings:
            typer.echo(f"⚠️ 生成完成但有警告: {'; '.join(result.warnings[:3])}")


# ---------------------------------------------------------------------------
# point 子组  —  inkflow outline point <list|create|update|delete>
# ---------------------------------------------------------------------------


@point_app.command("list")
def list_points_cmd(
    ctx: typer.Context,
    outline_id: str = typer.Option(..., "--outline-id", help="大纲 ID (UUID)"),
) -> None:
    """列出大纲内情节点（position 升序）"""
    cli_ctx: CliContext = ctx.obj
    oid = _parse_uuid(cli_ctx, outline_id, "大纲不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.list_points(outline_id=oid)

    points = _run(cli_ctx, _impl)
    if not points and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无情节点")
        return
    print_result(cli_ctx, [_point_to_dict(p) for p in points])


@point_app.command("create")
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

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.create_point(
                outline_id=oid,
                name=name,
                type=type,
                description=description,
                position=position,
                arc_id=aid,
            )

    point = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _point_to_dict(point))
    else:
        type_suffix = f" ({point.type})" if point.type else ""
        typer.echo(f"✅ 情节点创建成功: [{point.name}]{type_suffix}")


@point_app.command("update")
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

    async def _impl():
        update_fields: dict[str, object] = {}
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
                "" if arc_id == "" else _parse_uuid(cli_ctx, arc_id, "弧线不存在")
            )
        update = PlotPointUpdate(**update_fields)
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.update_point(point_id=pid, update=update)

    point = _run(cli_ctx, _impl)
    if point is None:
        print_error(cli_ctx, "NOT_FOUND", "情节点不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _point_to_dict(point))
    else:
        typer.echo(f"✅ 情节点已更新: [{point.name}]")


@point_app.command("delete")
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

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.delete_point(point_id=pid, force=False)

    ok = _run(cli_ctx, _impl)
    if ok:
        if cli_ctx.json_output:
            print_result(cli_ctx, {"id": str(pid), "deleted": True})
        else:
            typer.echo(f"✅ 情节点 #{point_id} 已删除")
    else:
        print_error(cli_ctx, "NOT_FOUND", "情节点不存在")


# ---------------------------------------------------------------------------
# arc 子组  —  inkflow outline arc <list|create|update|delete>
# ---------------------------------------------------------------------------


@arc_app.command("list")
def list_arcs_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
) -> None:
    """列出项目内故事弧线（名称升序）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.list_arcs(project_id=pid)

    arcs = _run(cli_ctx, _impl)
    if not arcs and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无弧线")
        return
    print_result(cli_ctx, [_arc_to_dict(a) for a in arcs])


@arc_app.command("create")
def create_arc_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    name: str = typer.Option(..., "--name", "-n", help="弧线名"),
    description: str = typer.Option("", "--description", "-d", help="弧线说明"),
) -> None:
    """创建故事弧线"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.create_arc(project_id=pid, name=name, description=description)

    arc = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _arc_to_dict(arc))
    else:
        typer.echo(f"✅ 弧线创建成功: [{arc.name}]")


@arc_app.command("update")
def update_arc_cmd(
    ctx: typer.Context,
    arc_id: str = typer.Option(..., "--id", "-i", help="弧线 ID (UUID)"),
    name: str | None = typer.Option(None, "--name", "-n", help="新弧线名"),
    description: str | None = typer.Option(None, "--description", "-d", help="新弧线说明"),
) -> None:
    """更新故事弧线（仅更新传入的字段）"""
    cli_ctx: CliContext = ctx.obj
    aid = _parse_uuid(cli_ctx, arc_id, "弧线不存在")

    async def _impl():
        update_fields: dict[str, object] = {}
        if name is not None:
            update_fields["name"] = name
        if description is not None:
            update_fields["description"] = description
        update = StoryArcUpdate(**update_fields)
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.update_arc(arc_id=aid, update=update)

    arc = _run(cli_ctx, _impl)
    if arc is None:
        print_error(cli_ctx, "NOT_FOUND", "弧线不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _arc_to_dict(arc))
    else:
        typer.echo(f"✅ 弧线已更新: [{arc.name}]")


@arc_app.command("delete")
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

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = OutlineService(repository=SQLiteOutlineRepository(session))
            return await svc.delete_arc(arc_id=aid, force=False)

    ok = _run(cli_ctx, _impl)
    if ok:
        if cli_ctx.json_output:
            print_result(cli_ctx, {"id": str(aid), "deleted": True})
        else:
            typer.echo(f"✅ 弧线 #{arc_id} 已删除")
    else:
        print_error(cli_ctx, "NOT_FOUND", "弧线不存在")


# ── 注册 point / arc 子组 ──

app.add_typer(point_app, name="point")
app.add_typer(arc_app, name="arc")
