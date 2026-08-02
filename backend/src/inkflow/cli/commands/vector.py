"""F14 RAG 向量 CLI 命令 — `inkflow vector <action>`.

薄层设计：仅做参数解析/校验与结果格式化，全部业务委托 ExtractionService
（spec §4.2）。遵循 F7 §5 全局约定：--json 统一信封
{"ok": true, "data": ...} / {"ok": false, "error": {"code", "message"}}；
退出码 0/1/2/130。

错误码映射（spec §4/§7）:
- RAGUnavailableError / VectorStoreError → RAG_ERROR（向量库不可用/检索失败）
- 无效 UUID → NOT_FOUND
- 其余异常 → DB_ERROR

reindex 缺省 --type = 全部 5 种实体类型（服务层展开）；--type 可重复指定；
retrieve 结果按 relevance_score 降序输出（spec §4.2）。--type 非法值由
Typer Choice 校验 → 退出码 2；retrieve 缺 --query → 退出码 2（spec §7）。

依据: specs/f14-extraction-service/spec.md §4.2/§4.3/§7/§9。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import typer

from inkflow.cli.context import CliContext
from inkflow.cli.output import print_error, print_result
from inkflow.core.database import async_session_factory, create_tables
from inkflow.domain.models.extraction import ReindexResult
from inkflow.domain.ports.extraction_errors import (
    RAGUnavailableError,
    VectorStoreError,
)
from inkflow.domain.ports.vector_store import EntityType, RetrievedEntity
from inkflow.domain.services._character_extractor import CharacterExtractor
from inkflow.domain.services._foreshadowing_extractor import ForeshadowingExtractor
from inkflow.domain.services._outline_generator import OutlineGenerator
from inkflow.domain.services._timeline_extractor import TimelineExtractor
from inkflow.domain.services._world_extractor import WorldExtractor
from inkflow.domain.services.character_service import CharacterService
from inkflow.domain.services.extraction_service import ExtractionService
from inkflow.domain.services.outline_service import OutlineService
from inkflow.domain.services.style_service import StyleService
from inkflow.domain.services.timeline_service import TimelineService
from inkflow.domain.services.world_service import WorldService
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
from inkflow.infrastructure.database.repositories.outline_repo import (
    SQLiteOutlineRepository,
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
from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient
from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager

app = typer.Typer(name="vector", help="RAG 向量索引与检索", no_args_is_help=True)


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


def _run(cli_ctx: CliContext, coro_fn) -> Any:
    """执行服务调用并统一映射领域异常为 F7 错误信封（退出码 1）."""
    try:
        return _run_async(coro_fn())
    except typer.Exit:
        raise
    except (RAGUnavailableError, VectorStoreError) as e:
        print_error(cli_ctx, "RAG_ERROR", str(e))
    except Exception as e:  # noqa: BLE001
        print_error(cli_ctx, "DB_ERROR", f"内部错误: {e}")


def _make_service(session) -> ExtractionService:
    """构造注入完整依赖的 ExtractionService（ADR-015）.

    向量存储未装配（LangChainVectorStore 归 M6/M7）: vector_store=None，
    reindex / retrieve 时门面抛 RAGUnavailableError → RAG_ERROR。
    """
    project_repo = SQLiteProjectRepository(session)
    chapter_repo = SQLiteChapterRepository(session)
    character_repo = SQLiteCharacterRepository(session)
    world_repo = SQLiteWorldRepository(session)
    outline_repo = SQLiteOutlineRepository(session)
    timeline_repo = SQLiteTimelineRepository(session)
    foreshadowing_repo = SQLiteForeshadowingRepository(session)
    llm_client = LangChainLLMClient()
    prompt_manager = LangChainPromptManager()
    return ExtractionService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        run_repo=SQLExtractionRunRepository(session),
        character_service=CharacterService(
            repository=character_repo,
            extractor=CharacterExtractor(
                llm_client=llm_client,
                prompt_manager=prompt_manager,
                repository=character_repo,
            ),
            project_repo=project_repo,
        ),
        world_service=WorldService(
            repository=world_repo,
            extractor=WorldExtractor(
                llm_client=llm_client,
                prompt_manager=prompt_manager,
                repository=world_repo,
            ),
            project_repo=project_repo,
        ),
        outline_service=OutlineService(
            repository=outline_repo,
            generator=OutlineGenerator(
                llm_client=llm_client,
                prompt_manager=prompt_manager,
                repository=outline_repo,
            ),
            project_repo=project_repo,
        ),
        timeline_service=TimelineService(repository=timeline_repo, project_repo=project_repo),
        foreshadowing_extractor=ForeshadowingExtractor(
            llm_client=llm_client,
            prompt_manager=prompt_manager,
            foreshadowing_repo=foreshadowing_repo,
        ),
        timeline_extractor=TimelineExtractor(
            llm_client=llm_client,
            prompt_manager=prompt_manager,
            timeline_repo=timeline_repo,
        ),
        style_service=StyleService(
            project_repo=project_repo,
            chapter_repo=chapter_repo,
        ),
        character_repo=character_repo,
        world_repo=world_repo,
        timeline_repo=timeline_repo,
        foreshadowing_repo=foreshadowing_repo,
        vector_store=None,
    )


def _reindex_summary(result: ReindexResult) -> str:
    """重建索引结果的人类可读表达（spec §4.3）。"""
    types_label = "/".join(t.value for t in result.entity_types)
    return f"✅ 索引完成: {types_label} 共 {result.indexed} 条"


def _retrieved_to_dict(entity: RetrievedEntity) -> dict[str, Any]:
    """检索结果 → JSON-safe dict（spec §4.3 items 元素）."""
    return {
        "entity_id": entity.entity_id,
        "entity_type": entity.entity_type.value,
        "content": entity.content,
        "relevance_score": entity.relevance_score,
        "metadata": entity.metadata,
    }


def _retrieved_label(entity: RetrievedEntity, index: int) -> str:
    """检索结果条目的人类可读表达（spec §4.3）。"""
    name = entity.metadata.get("name", entity.entity_id)
    first_line = entity.content.splitlines()[0] if entity.content else ""
    snippet = first_line if len(first_line) <= 50 else f"{first_line[:50]}……"
    return (
        f"  {index}. [{entity.entity_type.value}] {name} — {entity.relevance_score:.2f}\n"
        f"     （{snippet}）"
    )


# ---------------------------------------------------------------------------
# reindex  —  inkflow vector reindex --project-id <uuid> [--type <type>]...
# ---------------------------------------------------------------------------


@app.command("reindex")
def vector_reindex_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    entity_types: list[EntityType] | None = typer.Option(
        None,
        "--type",
        help="实体类型（可重复指定；缺省 = 全部 5 种）",
    ),
) -> None:
    """全量重建项目向量索引（幂等 upsert，spec §5.6）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).reindex(project_id=pid, entity_types=entity_types)

    result = _run(cli_ctx, _impl)
    if cli_ctx.json_output:
        print_result(cli_ctx, result.model_dump(mode="json"))
    else:
        typer.echo(_reindex_summary(result))


# ---------------------------------------------------------------------------
# retrieve  —  inkflow vector retrieve --project-id <uuid> --query <str>
#             [--type] [--top-k] [--min-score]
# ---------------------------------------------------------------------------


@app.command("retrieve")
def vector_retrieve_cmd(
    ctx: typer.Context,
    project_id: str = typer.Option(..., "--project-id", help="项目 ID (UUID)"),
    query: str = typer.Option(..., "--query", help="检索查询文本"),
    entity_types: list[EntityType] | None = typer.Option(
        None, "--type", help="限定实体类型（可重复指定）"
    ),
    top_k: int = typer.Option(10, "--top-k", help="返回结果数量上限（默认 10）"),
    min_score: float = typer.Option(0.0, "--min-score", help="最低相关度阈值（0-1，默认 0.0）"),
) -> None:
    """语义检索项目向量库（结果按相关度降序，spec §5.6）"""
    cli_ctx: CliContext = ctx.obj
    pid = _parse_uuid(cli_ctx, project_id, "项目不存在")

    async def _impl():
        await create_tables()
        async with async_session_factory() as session:
            return await _make_service(session).retrieve(
                query,
                project_id=pid,
                entity_types=entity_types,
                top_k=top_k,
                min_score=min_score,
            )

    items = _run(cli_ctx, _impl)
    items = sorted(items, key=lambda e: e.relevance_score, reverse=True)
    if cli_ctx.json_output:
        print_result(cli_ctx, {"items": [_retrieved_to_dict(e) for e in items]})
        return
    if not items:
        typer.echo("🔍 未找到相关结果")
        return
    typer.echo(f"🔍 检索结果 (query: {query}, top {top_k}):")
    for i, entity in enumerate(items, 1):
        typer.echo(_retrieved_label(entity, i))
