"""F26/F58 只读 Agent 工具 — 领域只读工具（search_characters / get_character /
check_foreshadowing / list_foreshadowing / get_foreshadowing /
list_world_settings / get_world_setting / get_prior_summary / audit_chapter /
count_words；world_service 未注入时剔除世界观检索 2 个），输出统一 JSON 信封.

#680: 检索工具 schema 移除 project_id——装配期闭包绑定（仿 save_draft_tool
expected_project_id 先例），LLM 无需自报项目 ID（防编造全零 UUID 孤儿数据）。

本模块承载工具工厂与静态注册表数据源，不 import LangChain/deepagents 任何模块
（ADR-015 隔离不变式由 tools 包边界承担）。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.domain.services._word_count import count_words
from inkflow.infrastructure.agent.tools import _tool_db_lock as _tool_db_lock_mod
from inkflow.logging import instrument

_PAGE_SIZE = 50
_WORLD_TOOL_NAMES = frozenset({"list_world_settings", "get_world_setting"})
"""依赖 world_service 的工具名——world_service=None 时 build 不物化这两个工具."""


# ── 参数模型（用于生成 ToolSpec.input_schema） ──


class SearchCharactersParams(BaseModel):
    """search_characters 工具参数."""

    search: str | None = None
    group_id: uuid.UUID | None = None


class CheckForeshadowingParams(BaseModel):
    """check_foreshadowing 工具参数."""

    status: str | None = None


class GetPriorSummaryParams(BaseModel):
    """get_prior_summary 工具参数."""

    limit: int = 10


class AuditChapterParams(BaseModel):
    """audit_chapter 工具参数."""

    chapter_id: uuid.UUID
    include_static: bool = True


class CountWordsParams(BaseModel):
    """count_words 工具参数."""

    text: str


class GetCharacterParams(BaseModel):
    """get_character 工具参数."""

    character_id: uuid.UUID


class ListForeshadowingParams(BaseModel):
    """list_foreshadowing 工具参数."""

    search: str | None = None
    status: str | None = None


class GetForeshadowingParams(BaseModel):
    """get_foreshadowing 工具参数."""

    foreshadowing_id: uuid.UUID


class ListWorldSettingsParams(BaseModel):
    """list_world_settings 工具参数."""

    search: str | None = None
    category: str | None = None


class GetWorldSettingParams(BaseModel):
    """get_world_setting 工具参数."""

    setting_id: uuid.UUID


# ── 工具数据契约 ──


@dataclass
class Tool:
    """可执行工具 — spec 定义 + 实现函数."""

    spec: ToolSpec
    func: Callable[..., Awaitable[str]]


@dataclass
class ReaderToolDeps:
    """工具工厂依赖 — service 实例注入（鸭子类型）."""

    character_service: object  # 有 list_characters(project_id, ...) / get_character(character_id)
    foreshadowing_service: object  # 有 list(project_id, ...) / get(foreshadowing_id)
    summary_service: object  # 有 list_recent(project_id, limit=10)
    chapter_audit_service: object  # 有 audit(project_id, chapter_id, *, include_static=True)
    world_service: object | None = None  # 有 list_settings/get_setting（WorldService 形态）


# ── 序列化与信封 ──


def _coerce_uuid(value: object) -> uuid.UUID:
    """规范化为 uuid.UUID——deepagents 透传 LLM JSON 原值，参数恒为 str（#275）."""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


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


T = TypeVar("T")


def _require_found(value: T, message: str) -> T:
    """service 返回 None（实体不存在）→ 抛 ValueError 走 _fail 信封."""
    if value is None:
        raise ValueError(message)
    return value


async def _fetch_all_pages(
    fetch: Callable[..., Awaitable[object]],
    project_id: uuid.UUID | None,
    **kwargs: object,
) -> list[object]:
    """分页循环取全：limit=50，offset 递增（0, 50, 100, ...）直到单次返回 < 50 条或空.

    兼容真实 service 的 tuple[list, int] 返回（当前页, 总数）与裸列表两种形态。
    project_id 可为 None（#680 防御：装配期未注入时传给 service，异常走 _fail 信封）。
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
        group="retrieval",
    ),
    ToolSpec(
        name="get_character",
        description="按角色 ID 获取角色档案详情（性格/背景/目标/关系摘要）",
        input_schema=GetCharacterParams.model_json_schema(),
        group="retrieval",
    ),
    ToolSpec(
        name="check_foreshadowing",
        description="列出项目中未回收的伏笔（内容/状态/埋设位置）",
        input_schema=CheckForeshadowingParams.model_json_schema(),
        group="retrieval",
    ),
    ToolSpec(
        name="list_foreshadowing",
        description="列出项目内全部伏笔（全状态视角，可按关键字/状态过滤）",
        input_schema=ListForeshadowingParams.model_json_schema(),
        group="retrieval",
    ),
    ToolSpec(
        name="get_foreshadowing",
        description="按伏笔 ID 获取单条伏笔详情（内容/状态/埋设位置/回收时间）",
        input_schema=GetForeshadowingParams.model_json_schema(),
        group="retrieval",
    ),
    ToolSpec(
        name="list_world_settings",
        description="列出项目内世界观设定条目（可按名称关键字/类别过滤）",
        input_schema=ListWorldSettingsParams.model_json_schema(),
        group="retrieval",
    ),
    ToolSpec(
        name="get_world_setting",
        description="按条目 ID 获取单个世界观设定条目详情",
        input_schema=GetWorldSettingParams.model_json_schema(),
        group="retrieval",
    ),
    ToolSpec(
        name="get_prior_summary",
        description="获取项目前文摘要（最近 N 章，与写作时上下文注入同源数据）",
        input_schema=GetPriorSummaryParams.model_json_schema(),
        group="retrieval",
    ),
    ToolSpec(
        name="audit_chapter",
        description="对单个章节执行一致性审计（字数 + LLM 漂移 + 静态一致性），返回 findings",
        input_schema=AuditChapterParams.model_json_schema(),
        group="audit",
    ),
    ToolSpec(
        name="count_words",
        description="统计中英文混合文本字数（去除 Markdown 语法）",
        input_schema=CountWordsParams.model_json_schema(),
        group="audit",
    ),
]


def build_reader_tools(
    deps: ReaderToolDeps,
    project_id: uuid.UUID | str | None = None,
    include: list[str] | None = None,
) -> list[Tool]:
    """构建只读工具（顺序固定 = _TOOL_SPECS 目录序；world_service=None 时剔除世界观 2 个）.

    Args:
        deps: 工具依赖（service 实例注入）.
        project_id: 装配期项目 ID（可为 None）——#680 闭包绑定：检索工具自动作用于
            当前项目，func 调用不再接收 project_id 参数；None 时向 service 传 None，
            异常走 _fail 信封（防御性）.
        include: 白名单工具名列表；None = 全量只读（world_service 注入时 10 个，
            未注入剔除世界观 2 个 → 8 个）；传入 [names] = 只返回白名单命中项
            （按 _TOOL_SPECS 目录原序，未知名忽略）.
    """
    bound_project_id = _coerce_uuid(project_id) if project_id is not None else None

    @instrument(caller_type="tool")
    async def _search_characters(
        search: str | None = None,
        group_id: uuid.UUID | None = None,
        **kwargs: object,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            try:
                if group_id is not None:
                    group_id = _coerce_uuid(group_id)
                items = await _fetch_all_pages(
                    deps.character_service.list_characters,  # type: ignore[attr-defined]  # 鸭子类型：字段按契约声明为 object，运行时注入真实 service
                    bound_project_id,
                    search=search,
                    group_id=group_id,
                )
                return _ok(_serialize_data(items))
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _get_character(character_id: uuid.UUID, **kwargs: object) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            try:
                character = await deps.character_service.get_character(  # type: ignore[attr-defined]  # 鸭子类型：字段按契约声明为 object，运行时注入真实 service
                    _coerce_uuid(character_id)
                )
                return _ok(_serialize_data(_require_found(character, "角色不存在")))
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _check_foreshadowing(status: str | None = None, **kwargs: object) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            try:
                items = await _fetch_all_pages(
                    deps.foreshadowing_service.list,  # type: ignore[attr-defined]  # 鸭子类型：字段按契约声明为 object，运行时注入真实 service
                    bound_project_id,
                    status=status,
                )
                return _ok(_serialize_data(items))
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _list_foreshadowing(
        search: str | None = None,
        status: str | None = None,
        **kwargs: object,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            try:
                items = await _fetch_all_pages(
                    deps.foreshadowing_service.list,  # type: ignore[attr-defined]  # 鸭子类型：字段按契约声明为 object，运行时注入真实 service
                    bound_project_id,
                    search=search,
                    status=status,
                )
                return _ok(_serialize_data(items))
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _get_foreshadowing(foreshadowing_id: uuid.UUID, **kwargs: object) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            try:
                foreshadowing = await deps.foreshadowing_service.get(  # type: ignore[attr-defined]  # 鸭子类型：字段按契约声明为 object，运行时注入真实 service
                    _coerce_uuid(foreshadowing_id)
                )
                return _ok(_serialize_data(_require_found(foreshadowing, "伏笔不存在")))
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _list_world_settings(
        search: str | None = None,
        category: str | None = None,
        **kwargs: object,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            try:
                items = await _fetch_all_pages(
                    deps.world_service.list_settings,  # type: ignore[attr-defined]  # 鸭子类型：字段按契约声明为 object|None，world 工具仅在注入时物化
                    bound_project_id,
                    search=search,
                    category=category,
                )
                return _ok(_serialize_data(items))
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _get_world_setting(setting_id: uuid.UUID, **kwargs: object) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            try:
                setting = await deps.world_service.get_setting(  # type: ignore[attr-defined]  # 鸭子类型：字段按契约声明为 object|None，world 工具仅在注入时物化
                    _coerce_uuid(setting_id)
                )
                return _ok(_serialize_data(_require_found(setting, "世界观条目不存在")))
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _get_prior_summary(limit: int = 10, **kwargs: object) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            try:
                result = await deps.summary_service.list_recent(  # type: ignore[attr-defined]  # 鸭子类型：字段按契约声明为 object，运行时注入真实 service
                    bound_project_id, limit=limit
                )
                return _ok(_serialize_data(result))
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _audit_chapter(
        chapter_id: uuid.UUID,
        include_static: bool = True,
        **kwargs: object,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            chapter_id = _coerce_uuid(chapter_id)
            try:
                result = await deps.chapter_audit_service.audit(  # type: ignore[attr-defined]  # 鸭子类型：字段按契约声明为 object，运行时注入真实 service
                    bound_project_id,
                    chapter_id,
                    include_static=include_static,
                )
                return _ok(_serialize_data(result))
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _count_words(text: str, **kwargs: object) -> str:
        try:
            return _ok(count_words(text))
        except Exception as exc:
            return _fail(exc)

    funcs: dict[str, Callable[..., Awaitable[str]]] = {
        "search_characters": _search_characters,
        "get_character": _get_character,
        "check_foreshadowing": _check_foreshadowing,
        "list_foreshadowing": _list_foreshadowing,
        "get_foreshadowing": _get_foreshadowing,
        "list_world_settings": _list_world_settings,
        "get_world_setting": _get_world_setting,
        "get_prior_summary": _get_prior_summary,
        "audit_chapter": _audit_chapter,
        "count_words": _count_words,
    }
    specs = [
        spec
        for spec in _TOOL_SPECS
        if (deps.world_service is not None or spec.name not in _WORLD_TOOL_NAMES)
        and (include is None or spec.name in include)
    ]
    return [Tool(spec=spec, func=funcs[spec.name]) for spec in specs]
