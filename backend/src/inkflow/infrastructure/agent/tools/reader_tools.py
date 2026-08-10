"""F26 只读 Agent 工具 — 5 个领域只读工具（search_characters / check_foreshadowing /
get_prior_summary / audit_chapter / count_words），输出统一 JSON 信封.

本模块承载工具工厂与静态注册表数据源，不 import LangChain/deepagents 任何模块
（ADR-015 隔离不变式由 tools 包边界承担）。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.domain.services._word_count import count_words

_PAGE_SIZE = 50


# ── 参数模型（用于生成 ToolSpec.input_schema） ──


class SearchCharactersParams(BaseModel):
    """search_characters 工具参数."""

    project_id: uuid.UUID
    search: str | None = None
    group_id: uuid.UUID | None = None


class CheckForeshadowingParams(BaseModel):
    """check_foreshadowing 工具参数."""

    project_id: uuid.UUID
    status: str | None = None


class GetPriorSummaryParams(BaseModel):
    """get_prior_summary 工具参数."""

    project_id: uuid.UUID
    limit: int = 10


class AuditChapterParams(BaseModel):
    """audit_chapter 工具参数."""

    project_id: uuid.UUID
    chapter_id: uuid.UUID
    include_static: bool = True


class CountWordsParams(BaseModel):
    """count_words 工具参数."""

    text: str


# ── 工具数据契约 ──


@dataclass
class Tool:
    """可执行工具 — spec 定义 + 实现函数."""

    spec: ToolSpec
    func: Callable[..., Awaitable[str]]


@dataclass
class ReaderToolDeps:
    """工具工厂依赖 — service 实例注入（鸭子类型）."""

    character_service: object  # 有 list_characters(project_id, search=None, group_id=None, ...)
    foreshadowing_service: object  # 有 list(project_id, search=None, status=None, ...)
    summary_service: object  # 有 list_recent(project_id, limit=10)
    chapter_audit_service: object  # 有 audit(project_id, chapter_id, *, include_static=True)


# ── 序列化与信封 ──


def _serialize_data(value: object) -> object:
    """递归序列化：列表逐元素、pydantic 模型 model_dump(mode="json")、其余原样."""
    if isinstance(value, list):
        return [_serialize_data(item) for item in value]
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        dumped = dumper(mode="json")
        if isinstance(dumped, dict):
            return dumped
    return value


def _ok(data: object) -> str:
    """成功信封: {"ok": True, "data": <序列化结果>}."""
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False)


def _fail(exc: Exception) -> str:
    """失败信封: {"ok": False, "error": "<异常消息>"}."""
    return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


async def _fetch_all_pages(
    fetch: Callable[..., Awaitable[object]],
    project_id: uuid.UUID,
    **kwargs: object,
) -> list[object]:
    """分页循环取全：limit=50，offset 递增（0, 50, 100, ...）直到单次返回 < 50 条或空.

    兼容真实 service 的 tuple[list, int] 返回（当前页, 总数）与裸列表两种形态。
    """
    items: list[object] = []
    offset = 0
    while True:
        result = await fetch(project_id, offset=offset, limit=_PAGE_SIZE, **kwargs)
        page = result[0] if isinstance(result, tuple) else result
        page_items = list(page) if isinstance(page, list | tuple) else []
        items.extend(page_items)
        if len(page_items) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return items


# ── 静态注册表数据源（与 build_reader_tools 顺序/描述一致） ──


_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="search_characters",
        description="搜索项目内角色档案（名称/简介/性格/关系摘要），支持按名称搜索与分组过滤",
        input_schema=SearchCharactersParams.model_json_schema(),
    ),
    ToolSpec(
        name="check_foreshadowing",
        description="列出项目中未回收的伏笔（内容/状态/埋设位置）",
        input_schema=CheckForeshadowingParams.model_json_schema(),
    ),
    ToolSpec(
        name="get_prior_summary",
        description="获取项目前文摘要（最近 N 章，与写作时上下文注入同源数据）",
        input_schema=GetPriorSummaryParams.model_json_schema(),
    ),
    ToolSpec(
        name="audit_chapter",
        description="对单个章节执行一致性审计（字数 + LLM 漂移 + 静态一致性），返回 findings",
        input_schema=AuditChapterParams.model_json_schema(),
    ),
    ToolSpec(
        name="count_words",
        description="统计中英文混合文本字数（去除 Markdown 语法）",
        input_schema=CountWordsParams.model_json_schema(),
    ),
]


def build_reader_tools(deps: ReaderToolDeps) -> list[Tool]:
    """构建 5 个只读工具（顺序固定：search_characters → count_words），func 闭包绑定 service."""

    async def _search_characters(
        project_id: uuid.UUID,
        search: str | None = None,
        group_id: uuid.UUID | None = None,
    ) -> str:
        try:
            items = await _fetch_all_pages(
                deps.character_service.list_characters,  # type: ignore[attr-defined]  # 鸭子类型：字段按契约声明为 object，运行时注入真实 service
                project_id,
                search=search,
                group_id=group_id,
            )
            return _ok(_serialize_data(items))
        except Exception as exc:
            return _fail(exc)

    async def _check_foreshadowing(project_id: uuid.UUID, status: str | None = None) -> str:
        try:
            items = await _fetch_all_pages(
                deps.foreshadowing_service.list,  # type: ignore[attr-defined]  # 鸭子类型：字段按契约声明为 object，运行时注入真实 service
                project_id,
                status=status,
            )
            return _ok(_serialize_data(items))
        except Exception as exc:
            return _fail(exc)

    async def _get_prior_summary(project_id: uuid.UUID, limit: int = 10) -> str:
        try:
            result = await deps.summary_service.list_recent(  # type: ignore[attr-defined]  # 鸭子类型：字段按契约声明为 object，运行时注入真实 service
                project_id, limit=limit
            )
            return _ok(_serialize_data(result))
        except Exception as exc:
            return _fail(exc)

    async def _audit_chapter(
        project_id: uuid.UUID,
        chapter_id: uuid.UUID,
        include_static: bool = True,
    ) -> str:
        try:
            result = await deps.chapter_audit_service.audit(  # type: ignore[attr-defined]  # 鸭子类型：字段按契约声明为 object，运行时注入真实 service
                project_id,
                chapter_id,
                include_static=include_static,
            )
            return _ok(_serialize_data(result))
        except Exception as exc:
            return _fail(exc)

    async def _count_words(text: str) -> str:
        try:
            return _ok(count_words(text))
        except Exception as exc:
            return _fail(exc)

    return [
        Tool(spec=_TOOL_SPECS[0], func=_search_characters),
        Tool(spec=_TOOL_SPECS[1], func=_check_foreshadowing),
        Tool(spec=_TOOL_SPECS[2], func=_get_prior_summary),
        Tool(spec=_TOOL_SPECS[3], func=_audit_chapter),
        Tool(spec=_TOOL_SPECS[4], func=_count_words),
    ]
