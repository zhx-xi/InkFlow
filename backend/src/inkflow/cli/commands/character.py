"""F9 角色管理 CLI 命令 — `inkflow character <action>` + `character group <action>`.

薄层设计：仅做参数解析/校验与结果格式化，全部业务委托 CharacterService
（spec §4）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130；删除类命令二次确认 + --force；
--json + 无 --force 的删除 → VALIDATION_ERROR。

错误码映射（spec §4/§7）:
- CharacterServiceError 子类（同名/自环/重复关系等）→ VALIDATION_ERROR
- CharacterNotFoundError / ProjectNotFoundError / 无效 UUID → NOT_FOUND
- CharacterExtractionError / LLMRequestError → LLM_ERROR
- 其余异常 → DB_ERROR

依据: specs/f9-character-service/spec.md §4/§7/§9。
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
from inkflow.core.database import async_session_factory, create_tables
from inkflow.domain.models.character import (
    Character,
    CharacterExtractionResult,
    CharacterExtractRequest,
    CharacterGroup,
    CharacterUpdate,
)
from inkflow.domain.ports.character_errors import (
    CharacterExtractionError,
    CharacterNotFoundError,
    CharacterServiceError,
    ProjectNotFoundError,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.services._character_extractor import CharacterExtractor
from inkflow.domain.services.character_service import CharacterService
from inkflow.infrastructure.database.repositories.character_repo import (
    SQLiteCharacterRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager

app = typer.Typer(name="character", help="角色管理", no_args_is_help=True)

group_app = typer.Typer(name="group", help="角色分组管理", no_args_is_help=True)


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
    except (CharacterNotFoundError, ProjectNotFoundError) as e:
        print_error(cli_ctx, "NOT_FOUND", str(e))
    except CharacterExtractionError as e:
        print_error(cli_ctx, "LLM_ERROR", str(e))
    except LLMRequestError:
        print_error(cli_ctx, "LLM_ERROR", "LLM 调用失败，请稍后重试")
    except CharacterServiceError as e:
        print_error(cli_ctx, "VALIDATION_ERROR", str(e))
    except ValidationError as e:
        messages = "; ".join(str(err.get("msg", "")) for err in e.errors())
        print_error(cli_ctx, "VALIDATION_ERROR", messages or "参数校验失败")
    except FileNotFoundError as e:
        print_error(cli_ctx, "VALIDATION_ERROR", f"文本文件不存在: {e.filename}")
    except Exception as e:
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


def _character_to_dict(character: Character) -> dict:
    """角色领域模型 → JSON-safe dict."""
    return character.model_dump(mode="json")


def _group_to_dict(group: CharacterGroup) -> dict:
    """分组领域模型 → JSON-safe dict."""
    return group.model_dump(mode="json")


def _relation_to_dict(relation) -> dict:
    """关系领域模型 → JSON-safe dict."""
    return dict(relation.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# create  —  inkflow character create --project-id <uuid> --name <str> ...
# ---------------------------------------------------------------------------


@app.command("create")
def create_character(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    name: str = typer.Option(..., "--name", "-n", help="角色名"),
    personality: str = typer.Option("", "--personality", help="性格描述"),
    background: str = typer.Option("", "--background", help="背景设定"),
    goals: str = typer.Option("", "--goals", help="目标/动机"),
    group_id: str | None = typer.Option(None, "--group-id", help="所属角色分组 ID (UUID)"),
) -> None:
    """创建角色"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")
    gid = _parse_uuid(cli_ctx, group_id, "分组不存在") if group_id is not None else None

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.create_character(
                project_id=pid,
                name=name,
                personality=personality,
                background=background,
                goals=goals,
                group_id=gid,
            )

    character = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _character_to_dict(character))
    else:
        typer.echo(f"✅ 角色创建成功: [{character.name}]")


# ---------------------------------------------------------------------------
# list  —  inkflow character list --project-id <uuid> [--search] [--group-id] ...
# ---------------------------------------------------------------------------


@app.command("list")
def list_characters(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    search: str | None = typer.Option(None, "--search", "-s", help="按名称搜索"),
    group_id: str | None = typer.Option(None, "--group-id", help="按分组过滤 (UUID)"),
    sort: str = typer.Option(
        "updated_at", "--sort", help="排序字段 (name / updated_at / created_at)"
    ),
    sort_desc: bool = typer.Option(
        True, "--sort-desc/--no-sort-desc", help="按排序字段降序（默认开启）"
    ),
    offset: int = typer.Option(0, "--offset", help="分页偏移"),
    limit: int = typer.Option(50, "--limit", help="每页数量"),
) -> None:
    """列出项目内角色"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")
    gid = _parse_uuid(cli_ctx, group_id, "分组不存在") if group_id is not None else None

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.list_characters(
                project_id=pid,
                search=search,
                group_id=gid,
                sort_by=sort,
                sort_desc=sort_desc,
                offset=offset,
                limit=limit,
            )

    characters, total = _run(cli_ctx, _impl)
    if not characters and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无角色")
        return
    if not cli_ctx.json_output and total:
        print_result(cli_ctx, f"共 {total} 个角色")
    print_result(cli_ctx, [_character_to_dict(c) for c in characters])


# ---------------------------------------------------------------------------
# get  —  inkflow character get --id <uuid>
# ---------------------------------------------------------------------------


@app.command("get")
def get_character(
    ctx: typer.Context,
    character_id: str = typer.Option(..., "--id", "-i", help="角色 ID (UUID)"),
) -> None:
    """查看角色详情"""
    cli_ctx: CliContext = ctx.obj
    cid = _parse_uuid(cli_ctx, character_id, "角色不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.get_character(character_id=cid)

    character = _run(cli_ctx, _impl)
    if character is None:
        print_error(cli_ctx, "NOT_FOUND", "角色不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _character_to_dict(character))
    else:
        typer.echo(f"ID:         {character.id}")
        typer.echo(f"名称:       {character.name}")
        typer.echo(f"性格:       {character.personality}")
        typer.echo(f"背景:       {character.background}")
        typer.echo(f"目标:       {character.goals}")
        typer.echo(f"分组:       {character.group_id}")
        typer.echo(f"创建时间:   {character.created_at}")
        typer.echo(f"更新时间:   {character.updated_at}")


# ---------------------------------------------------------------------------
# update  —  inkflow character update --id <uuid> [--name] [--group-id ""]
# ---------------------------------------------------------------------------


@app.command("update")
def update_character(
    ctx: typer.Context,
    character_id: str = typer.Option(..., "--id", "-i", help="角色 ID (UUID)"),
    name: str | None = typer.Option(None, "--name", "-n", help="新角色名"),
    personality: str | None = typer.Option(None, "--personality", help="新性格描述"),
    background: str | None = typer.Option(None, "--background", help="新背景设定"),
    goals: str | None = typer.Option(None, "--goals", help="新目标/动机"),
    group_id: str | None = typer.Option(
        None, "--group-id", help='新分组 ID (UUID)；传空字符串 "" 表示清除分组'
    ),
) -> None:
    """更新角色（仅更新传入的字段）"""
    cli_ctx: CliContext = ctx.obj
    cid = _parse_uuid(cli_ctx, character_id, "角色不存在")

    async def _impl():
        update_fields: dict[str, Any] = {}
        if name is not None:
            update_fields["name"] = name
        if personality is not None:
            update_fields["personality"] = personality
        if background is not None:
            update_fields["background"] = background
        if goals is not None:
            update_fields["goals"] = goals
        if group_id is not None:
            update_fields["group_id"] = (
                None if group_id == "" else _parse_uuid(cli_ctx, group_id, "分组不存在")
            )
        update = CharacterUpdate(**update_fields)
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.update_character(character_id=cid, update=update)

    character = _run(cli_ctx, _impl)
    if character is None:
        print_error(cli_ctx, "NOT_FOUND", "角色不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _character_to_dict(character))
    else:
        typer.echo(f"✅ 角色已更新: [{character.name}]")


# ---------------------------------------------------------------------------
# delete  —  inkflow character delete --id <uuid> [--force] [--permanent]
# ---------------------------------------------------------------------------


@app.command("delete")
def delete_character(
    ctx: typer.Context,
    character_id: str = typer.Option(..., "--id", "-i", help="角色 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
    permanent: bool = typer.Option(False, "--permanent", "-p", help="硬删除（物理删除）"),
) -> None:
    """删除角色（默认软删除；--permanent 物理删除）"""
    cli_ctx: CliContext = ctx.obj
    cid = _parse_uuid(cli_ctx, character_id, "角色不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        label = "永久删除" if permanent else "删除"
        if not typer.confirm(f"确定要{label}角色 #{character_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.delete_character(character_id=cid, force=permanent)

    ok = _run(cli_ctx, _impl)
    if ok:
        label = "永久删除" if permanent else "已删除"
        if cli_ctx.json_output:
            print_result(cli_ctx, {"id": str(cid), "deleted": True})
        else:
            typer.echo(f"✅ 角色 #{character_id} {label}")
    else:
        print_error(cli_ctx, "NOT_FOUND", "角色不存在")


# ---------------------------------------------------------------------------
# restore  —  inkflow character restore --id <uuid>
# ---------------------------------------------------------------------------


@app.command("restore")
def restore_character(
    ctx: typer.Context,
    character_id: str = typer.Option(..., "--id", "-i", help="角色 ID (UUID)"),
) -> None:
    """恢复已删除的角色（级联恢复其双向关系）"""
    cli_ctx: CliContext = ctx.obj
    cid = _parse_uuid(cli_ctx, character_id, "角色不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.restore_character(character_id=cid)

    character = _run(cli_ctx, _impl)
    if character is None:
        print_error(cli_ctx, "NOT_FOUND", "角色不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _character_to_dict(character))
    else:
        typer.echo(f"✅ 角色已恢复: [{character.name}]")


# ---------------------------------------------------------------------------
# relate  —  inkflow character relate --id <uuid> --to <uuid> --type <str>
# ---------------------------------------------------------------------------


@app.command("relate")
def relate_characters(
    ctx: typer.Context,
    character_id: str = typer.Option(..., "--id", "-i", help="起点角色 ID (UUID)"),
    to_character_id: str = typer.Option(..., "--to", help="终点角色 ID (UUID)"),
    relation_type: str = typer.Option(..., "--type", "-t", help="关系类型"),
    description: str = typer.Option("", "--description", "-d", help="关系描述"),
) -> None:
    """创建角色关系（from = 路径角色）"""
    cli_ctx: CliContext = ctx.obj
    cid = _parse_uuid(cli_ctx, character_id, "角色不存在")
    to = _parse_uuid(cli_ctx, to_character_id, "角色不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.create_relation(
                character_id=cid,
                to_character_id=to,
                relation_type=relation_type,
                description=description,
            )

    relation = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _relation_to_dict(relation))
    else:
        typer.echo(f"✅ 关系已创建: {cid} → {to} ({relation.relation_type})")


# ---------------------------------------------------------------------------
# unrelate  —  inkflow character unrelate --id <uuid> --relation-id <uuid>
# ---------------------------------------------------------------------------


@app.command("unrelate")
def unrelate_characters(
    ctx: typer.Context,
    character_id: str = typer.Option(..., "--id", "-i", help="角色 ID (UUID)"),
    relation_id: str = typer.Option(..., "--relation-id", help="关系 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
) -> None:
    """删除角色关系"""
    cli_ctx: CliContext = ctx.obj
    cid = _parse_uuid(cli_ctx, character_id, "角色不存在")
    rid = _parse_uuid(cli_ctx, relation_id, "关系不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        if not typer.confirm(f"确定要删除关系 #{relation_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.delete_relation(character_id=cid, relation_id=rid)

    ok = _run(cli_ctx, _impl)
    if ok:
        if cli_ctx.json_output:
            print_result(cli_ctx, {"id": str(rid), "deleted": True})
        else:
            typer.echo(f"✅ 关系 #{relation_id} 已删除")
    else:
        print_error(cli_ctx, "NOT_FOUND", "关系不存在")


# ---------------------------------------------------------------------------
# relations  —  inkflow character relations --id <uuid>
# ---------------------------------------------------------------------------


@app.command("relations")
def list_relations(
    ctx: typer.Context,
    character_id: str = typer.Option(..., "--id", "-i", help="角色 ID (UUID)"),
) -> None:
    """列出角色全部活动关系（双向: from 或 to）"""
    cli_ctx: CliContext = ctx.obj
    cid = _parse_uuid(cli_ctx, character_id, "角色不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.list_relations(character_id=cid)

    relations = _run(cli_ctx, _impl)
    if not relations and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无关系")
        return
    if cli_ctx.json_output:
        print_result(cli_ctx, [_relation_to_dict(r) for r in relations])
    else:
        for r in relations:
            typer.echo(
                f"  [{r.relation_type}] {r.from_character_id} → {r.to_character_id}"
                f"{': ' + r.description if r.description else ''}"
            )


# ---------------------------------------------------------------------------
# extract  —  inkflow character extract --project-id <uuid> --text|--text-file
# ---------------------------------------------------------------------------


@app.command("extract")
def extract_characters(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    text: str = typer.Option("", "--text", help="待提取文本（与 --text-file 互斥）"),
    text_file: str | None = typer.Option(
        None, "--text-file", help="待提取文本文件路径（与 --text 互斥）"
    ),
    model: str | None = typer.Option(
        None, "--model", help="覆盖项目默认模型 (provider/model_name)"
    ),
) -> None:
    """AI 提取角色与关系（spec §5）"""
    cli_ctx: CliContext = ctx.obj
    if text and text_file is not None:
        typer.echo("❌ --text 与 --text-file 不能同时使用", err=True)
        raise typer.Exit(code=2)
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        extract_text = text
        if text_file is not None:
            extract_text = Path(text_file).read_text(encoding="utf-8")
        request = CharacterExtractRequest(project_id=pid, text=extract_text, model=model)
        await create_tables()
        async with async_session_factory() as session:
            repo = SQLiteCharacterRepository(session)
            svc = CharacterService(
                repository=repo,
                extractor=CharacterExtractor(
                    llm_client=LangChainLLMClient(),
                    prompt_manager=LangChainPromptManager(),
                    repository=repo,
                ),
                project_repo=SQLiteProjectRepository(session),
            )
            return await svc.extract(request)

    result: CharacterExtractionResult = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, result.model_dump(mode="json"))
    else:
        n_created = len(result.created)
        n_updated = len(result.updated)
        n_rel_created = len(result.relations_created)
        n_rel_updated = len(result.relations_updated)
        n_warnings = len(result.warnings)
        typer.echo(
            f"✅ 提取完成: 新增 {n_created} 个角色, 更新 {n_updated} 个角色, "
            f"新增 {n_rel_created} 条关系, 更新 {n_rel_updated} 条, 警告 {n_warnings} 条"
        )
        if n_warnings:
            typer.echo(f"⚠️ 提取完成但有警告: {'; '.join(result.warnings[:3])}")


# ---------------------------------------------------------------------------
# group 子组  —  inkflow character group <create|list|get|update|delete>
# ---------------------------------------------------------------------------


@group_app.command("create")
def create_group_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    name: str = typer.Option(..., "--name", "-n", help="分组名"),
    description: str = typer.Option("", "--description", "-d", help="分组说明"),
) -> None:
    """创建角色分组"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.create_group(project_id=pid, name=name, description=description)

    group = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, _group_to_dict(group))
    else:
        typer.echo(f"✅ 分组创建成功: [{group.name}]")


@group_app.command("list")
def list_groups_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
) -> None:
    """列出项目内分组"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.list_groups(project_id=pid)

    groups = _run(cli_ctx, _impl)
    if not groups and not cli_ctx.json_output:
        print_result(cli_ctx, "📭 暂无分组")
        return
    print_result(cli_ctx, [_group_to_dict(g) for g in groups])


@group_app.command("get")
def get_group_cmd(
    ctx: typer.Context,
    group_id: str = typer.Option(..., "--id", "-i", help="分组 ID (UUID)"),
) -> None:
    """查看分组详情"""
    cli_ctx: CliContext = ctx.obj
    gid = _parse_uuid(cli_ctx, group_id, "分组不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.get_group(group_id=gid)

    group = _run(cli_ctx, _impl)
    if group is None:
        print_error(cli_ctx, "NOT_FOUND", "分组不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _group_to_dict(group))
    else:
        typer.echo(f"ID:         {group.id}")
        typer.echo(f"名称:       {group.name}")
        typer.echo(f"说明:       {group.description}")
        typer.echo(f"排序:       {group.sort_order}")
        typer.echo(f"创建时间:   {group.created_at}")


@group_app.command("update")
def update_group_cmd(
    ctx: typer.Context,
    group_id: str = typer.Option(..., "--id", "-i", help="分组 ID (UUID)"),
    name: str | None = typer.Option(None, "--name", "-n", help="新分组名"),
    description: str | None = typer.Option(None, "--description", "-d", help="新分组说明"),
) -> None:
    """更新分组（仅更新传入的字段）"""
    cli_ctx: CliContext = ctx.obj
    gid = _parse_uuid(cli_ctx, group_id, "分组不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.update_group(group_id=gid, name=name, description=description)

    group = _run(cli_ctx, _impl)
    if group is None:
        print_error(cli_ctx, "NOT_FOUND", "分组不存在")
    if cli_ctx.json_output:
        print_result(cli_ctx, _group_to_dict(group))
    else:
        typer.echo(f"✅ 分组已更新: [{group.name}]")


@group_app.command("delete")
def delete_group_cmd(
    ctx: typer.Context,
    group_id: str = typer.Option(..., "--id", "-i", help="分组 ID (UUID)"),
    force: bool = typer.Option(False, "--force", "-f", help="跳过确认"),
) -> None:
    """删除分组（成员角色 group_id 置 NULL，角色保留）"""
    cli_ctx: CliContext = ctx.obj
    gid = _parse_uuid(cli_ctx, group_id, "分组不存在")
    if not force:
        if cli_ctx.json_output:
            print_error(cli_ctx, "VALIDATION_ERROR", "删除需 --force 或交互确认")
        if not typer.confirm(f"确定要删除分组 #{group_id} 吗？"):
            typer.echo("已取消")
            raise typer.Exit()

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            svc = CharacterService(repository=SQLiteCharacterRepository(session))
            return await svc.delete_group(group_id=gid, force=False)

    ok = _run(cli_ctx, _impl)
    if ok:
        if cli_ctx.json_output:
            print_result(cli_ctx, {"id": str(gid), "deleted": True})
        else:
            typer.echo(f"✅ 分组 #{group_id} 已删除")
    else:
        print_error(cli_ctx, "NOT_FOUND", "分组不存在")


# ── 注册 group 子组 ──

app.add_typer(group_app, name="group")
