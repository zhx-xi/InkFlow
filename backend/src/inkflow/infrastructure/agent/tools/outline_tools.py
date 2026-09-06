"""#955 F58 大纲域层级化工具矩阵 — 10 个大纲工具（3 读 + 7 写），统一 JSON 信封.

镜像 setting_write_tools / reader_tools 形态：
- 参数模型 → model_json_schema() → 静态 ToolSpec + 闭包动态 func
- 读工具（list_outlines / get_outline / list_plot_points）group="retrieval"，
  镜像 reader_tools：func 不暴露 project_id（#680 装配期闭包绑定）、不落审计；
  信封经 reader_tools._ok/_fail/_serialize_data/_fetch_all_pages 同包复用
- 写工具（create_overall_outline 等 7 个）group="writing"，func 保留可选 shim
  project_id（dict args_schema 下 deepagents 只传 schema 内参数，shim 兜底兼容
  MCP/writer 直接调用）；成功/失败均落审计（actor="agent:chat"），审计自身异常静默
- 层级字段（level/parent_id/chapter_id/volume_id）一律不出现在 schema（#955 N2）：
  层级语义由工具按名解析（父级名三态，contract-955 §2）与服务层校验承担
- 大纲名项目内唯一（含 volume 层）；整本根唯一由本模块 create_overall_outline
  前置检查承担（服务层无守卫，contract-955 §0-2）
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, NoReturn

from pydantic import BaseModel

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.domain.models.outline import (
    Outline,
    OutlineUpdate,
    PlotPoint,
    PlotPointUpdate,
    StoryArc,
)
from inkflow.infrastructure.agent.tools import _tool_db_lock as _tool_db_lock_mod
from inkflow.infrastructure.agent.tools.reader_tools import (
    Tool,
    _fail,
    _fetch_all_pages,
    _ok,
    _serialize_data,
)
from inkflow.logging import instrument


def _coerce_uuid(value: object) -> uuid.UUID:
    """规范化 uuid.UUID——deepagents 透传 LLM JSON 原值，参数恒为 str（#275）。"""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _coerce_id(value: object) -> object:
    """尽力规范化实体 id：可解析为 UUID 则转 UUID（服务层再转 int），否则原样透传."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return value


def _fmt_candidates(outlines: list[Outline]) -> str:
    """候选格式：`名称(id=UUID)` 以「、」连接（contract-955 §2）。"""
    return "、".join(f"{o.name}(id={o.id})" for o in outlines)


async def _resolve_unique_outline(
    deps: OutlineToolDeps,
    project_id: uuid.UUID | None,
    *,
    name: str,
    level: str | None,
    not_found: str,
    ambiguous: str,
) -> Outline | str:
    """父级名解析共用三态逻辑（contract-955 §2；返回 Outline 或失败信封错误文案）。

    唯一匹配 → Outline；无匹配 → not_found.format(name=name)；歧义（≥2）→
    ambiguous.format(name=name, candidates=候选串)。
    """
    all_outlines = await _fetch_all_outlines(deps, project_id)
    matches = [o for o in all_outlines if o.name == name and (level is None or o.level == level)]
    if len(matches) == 0:
        return not_found.format(name=name)
    if len(matches) > 1:
        return ambiguous.format(name=name, candidates=_fmt_candidates(matches))
    return matches[0]


async def _resolve_arc_name(
    deps: OutlineToolDeps,
    project_id: uuid.UUID | None,
    arc: str,
) -> uuid.UUID | str:
    """按弧线名解析 arc_id（项目内唯一；无匹配/歧义返回失败文案）。"""
    list_arcs = deps.outline_service.list_arcs  # type: ignore[attr-defined]  # 鸭子类型字段
    arcs: list[StoryArc] = await list_arcs(project_id)
    matches = [a for a in arcs if a.name == arc]
    if not matches:
        return f"故事弧线「{arc}」不存在"
    if len(matches) > 1:
        candidates = "、".join(f"{a.name}(id={a.id})" for a in matches)
        return f"故事弧线「{arc}」存在多个同名条目（异常数据），候选：{candidates}"
    return matches[0].id


async def _fetch_all_outlines(
    deps: OutlineToolDeps,
    project_id: uuid.UUID | None,
    **kwargs: object,
) -> list[Outline]:
    """分页取全项目大纲（鸭子类型：list_outlines 返回 tuple[list[Outline], int]）。"""
    return await _fetch_all_pages(  # type: ignore[return-value]  # 鸭子类型：运行时元素为 Outline 实体
        deps.outline_service.list_outlines,  # type: ignore[attr-defined]  # 鸭子类型：outline_service 按契约提供 list_outlines
        project_id,
        **kwargs,
    )


def _raise_error(message: str) -> NoReturn:
    """抛业务错误（工具内统一走失败信封；独立函数避免 TRY301 抽象 raise 提示）。"""
    raise ValueError(message)


async def _build_parent_chain(
    deps: OutlineToolDeps,
    outlines_by_id: dict[str, Outline],
    start_id: uuid.UUID | None,
) -> list[dict[str, str]]:
    """从 start_id 的父开始向上收集 parent_chain（防环上限 10）。"""
    chain: list[dict[str, str]] = []
    seen: set[str] = set()
    current_id = start_id
    while current_id is not None and len(chain) < 10:
        cid = str(current_id)
        if cid in seen:
            break
        seen.add(cid)
        current = outlines_by_id.get(cid)
        if current is None:
            current = await _resolve_outline_by_id(deps, current_id)
        if current is None:
            break
        chain.append({"id": cid, "name": current.name, "level": current.level})
        current_id = current.parent_id
    return chain


async def _resolve_outline_by_id(
    deps: OutlineToolDeps,
    outline_id: object,
) -> Outline | None:
    """按 id 逐级 get_outline（_build_parent_chain 兜底 resolve 回调）。"""
    get_outline = getattr(deps.outline_service, "get_outline", None)
    if not callable(get_outline):
        return None
    maybe = get_outline(_coerce_uuid(outline_id))
    if not asyncio.iscoroutine(maybe):
        return None
    outline_value = await maybe
    return outline_value if isinstance(outline_value, Outline) else None


async def _resolve_arc_names(
    deps: OutlineToolDeps,
    points: list[Any],
) -> dict[str, str | None]:
    """对 unique arc_ids 逐个 get_arc 解析 arc_name（局部 dict 缓存，§1.8）。"""
    arc_names: dict[str, str | None] = {}
    arc_ids: set[str] = set()
    for point in points:
        if point.arc_id is not None:
            arc_ids.add(str(point.arc_id))
    for arc_id in arc_ids:
        get_arc = getattr(deps.outline_service, "get_arc", None)
        if callable(get_arc):
            maybe = get_arc(_coerce_uuid(arc_id))
            if asyncio.iscoroutine(maybe):
                arc = await maybe
                arc_names[arc_id] = arc.name if arc is not None else None
            else:
                arc_names[arc_id] = None
        else:
            arc_names[arc_id] = None
    return arc_names


def _enrich_points_with_arc_name(
    points: list[Any],
    arc_names: dict[str, str | None],
) -> list[dict[str, Any]]:
    """情点列表序列化：条目键集合含 arc_name（arc_id 无命中 → None，不报错）。"""
    serialized: list[dict[str, Any]] = _serialize_data(points)  # type: ignore[assignment]  # _serialize_data 返回 object，运行时为 list[dict]（Pydantic 实体序列化结果）
    for item in serialized:
        item["arc_name"] = (
            arc_names.get(str(item["arc_id"])) if item.get("arc_id") is not None else None
        )
    return serialized


# ─── 参数模型（用于生成 ToolSpec.input_schema；project_id 由装配期绑定，不在 schema） ───


class ListOutlinesParams(BaseModel):
    """list_outlines 工具参数。"""

    level: str | None = None
    search: str | None = None


class GetOutlineParams(BaseModel):
    """get_outline 工具参数。"""

    outline_id: uuid.UUID | str
    include_plot_points: bool = False


class ListPlotPointsParams(BaseModel):
    """list_plot_points 工具参数。"""

    outline_id: uuid.UUID | str


class CreateOverallOutlineParams(BaseModel):
    """create_overall_outline 工具参数（整本根，无 level/parent_id）。"""

    name: str
    description: str = ""
    sort_order: int = 0


class CreateVolumeOutlineParams(BaseModel):
    """create_volume_outline 工具参数（父 = 整本根，无 level/parent_id）。"""

    name: str
    description: str = ""
    sort_order: int = 0
    overall: str | None = None  # 父消歧名（仅多整本根防御数据时需要）
    volume_name: str | None = None  # 关联写作卷标题


class CreateChapterOutlineParams(BaseModel):
    """create_chapter_outline 工具参数（父 = 卷大纲按名定位，无 level/parent_id）。"""

    name: str
    volume_outline_name: str
    description: str = ""
    sort_order: int = 0


class UpdateVolumeOutlineParams(BaseModel):
    """update_volume_outline 工具参数（部分更新；schema 无 level/parent_id/chapter_id）。"""

    outline_id: uuid.UUID | str
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None


class UpdateChapterOutlineParams(BaseModel):
    """update_chapter_outline 工具参数（部分更新；schema 无 level/parent_id/chapter_id）。"""

    outline_id: uuid.UUID | str
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None


class CreatePlotPointParams(BaseModel):
    """create_plot_point 工具参数（outline_id / chapter_outline_name 二选一定位）。"""

    outline_id: uuid.UUID | str | None = None
    chapter_outline_name: str | None = None
    name: str
    type: str = ""
    description: str = ""
    arc: str | None = None  # 弧线名


class UpdatePlotPointParams(BaseModel):
    """update_plot_point 工具参数（部分更新；arc_id 字符串直传，工具不强转 UUID）。"""

    plot_point_id: uuid.UUID | str
    name: str | None = None
    type: str | None = None
    description: str | None = None
    position: int | None = None
    arc_id: str | None = None


# ─── 工具 spec 静态常量（func 动态构建，镜像 setting_write_tools） ───


LIST_OUTLINES_SPEC = ToolSpec(
    name="list_outlines",
    description=(
        "列出项目内大纲条目（可按层级 overall/volume/chapter 过滤、按名称搜索），"
        "每条含父级链与关联写作卷标题"
    ),
    input_schema=ListOutlinesParams.model_json_schema(),
    group="retrieval",
)

GET_OUTLINE_SPEC = ToolSpec(
    name="get_outline",
    description="获取项目内单个大纲条目完整信息（含父级链；可选附该大纲的全部情节点）",
    input_schema=GetOutlineParams.model_json_schema(),
    group="retrieval",
)

LIST_PLOT_POINTS_SPEC = ToolSpec(
    name="list_plot_points",
    description="列出项目内指定大纲下的情节点（按位置升序，含所属故事弧线名）",
    input_schema=ListPlotPointsParams.model_json_schema(),
    group="retrieval",
)

CREATE_OVERALL_OUTLINE_SPEC = ToolSpec(
    name="create_overall_outline",
    description="创建项目整本根大纲（一个项目仅一根，已存在整本根时会失败）",
    input_schema=CreateOverallOutlineParams.model_json_schema(),
    group="writing",
)

CREATE_VOLUME_OUTLINE_SPEC = ToolSpec(
    name="create_volume_outline",
    description="创建项目卷大纲（自动挂在唯一整本根下，可按写作卷标题关联写作卷）",
    input_schema=CreateVolumeOutlineParams.model_json_schema(),
    group="writing",
)

CREATE_CHAPTER_OUTLINE_SPEC = ToolSpec(
    name="create_chapter_outline",
    description="创建项目章大纲（必须按卷大纲名称挂到既有卷大纲下）",
    input_schema=CreateChapterOutlineParams.model_json_schema(),
    group="writing",
)

UPDATE_VOLUME_OUTLINE_SPEC = ToolSpec(
    name="update_volume_outline",
    description="更新项目内卷大纲（部分更新，未传字段保持不变；仅限卷大纲）",
    input_schema=UpdateVolumeOutlineParams.model_json_schema(),
    group="writing",
)

UPDATE_CHAPTER_OUTLINE_SPEC = ToolSpec(
    name="update_chapter_outline",
    description="更新项目内章大纲（部分更新，未传字段保持不变；仅限章大纲）",
    input_schema=UpdateChapterOutlineParams.model_json_schema(),
    group="writing",
)

CREATE_PLOT_POINT_SPEC = ToolSpec(
    name="create_plot_point",
    description="创建项目内情节点并写入大纲（按大纲 id 或章大纲名称定位，可挂故事弧线）",
    input_schema=CreatePlotPointParams.model_json_schema(),
    group="writing",
)

UPDATE_PLOT_POINT_SPEC = ToolSpec(
    name="update_plot_point",
    description="更新项目内情节点（部分更新，未传字段保持不变）",
    input_schema=UpdatePlotPointParams.model_json_schema(),
    group="writing",
)


@dataclass
class OutlineToolDeps:
    """大纲工具工厂依赖——service 实例注入（鸭子类型，镜像 setting_write_tools）。

    expected_project_id: #748 绑定项目——每次 run 由装配层注入请求真实值；工具总是
    使用绑定值（LLM 无法编造全量 UUID 落孤儿数据），未注入时回退 caller 传入值
    （MCP/writer 兼容）。
    """

    outline_service: object  # 有 create_outline(project_id, name, description="",
    #   sort_order=0, level="overall", parent_id=None, volume_id=None) -> Outline(.id)；
    #   get_outline(outline_id) / list_outlines(project_id, search=None, offset, limit) /
    #   update_outline(outline_id, OutlineUpdate) / list_points(outline_id) /
    #   create_point(outline_id, name, type="", description="", position=None, arc_id=None) /
    #   update_point(point_id, PlotPointUpdate) / delete_point(point_id) /
    #   get_arc(arc_id) / list_arcs(project_id)
    chapter_service: object  # 有 list_volumes(project_id) ->
    #   list[Volume(.id,.title,.order_index)]；get_volume(volume_id) -> Volume(.title) | None
    audit_service: object  # 有 record(**kwargs)（AuditLogService 形态）
    expected_project_id: uuid.UUID | None = None


def _bind_project_id(deps: OutlineToolDeps, project_id: object) -> uuid.UUID | None:
    """解析绑定项目 id：装配期 expected 优先，未注入回退 caller 传入值."""
    bound = deps.expected_project_id if deps.expected_project_id is not None else project_id
    if isinstance(bound, uuid.UUID):
        return bound
    if isinstance(bound, str):
        try:
            return uuid.UUID(bound)
        except ValueError:
            return None
    return None


async def _audit(deps: OutlineToolDeps, project_id: uuid.UUID | None, *, summary: str) -> None:
    """写工具审计落盘（自身异常静默，不影响主返回）。"""
    with contextlib.suppress(Exception):
        await deps.audit_service.record(  # type: ignore[attr-defined]  # 鸭子类型：audit_service 按契约提供 record
            actor="agent:chat",
            project_id=project_id,
            severity_summary=summary,
            degraded=True,
        )


def build_outline_tools(deps: OutlineToolDeps) -> list[Tool]:
    """构建大纲域工具（顺序固定 = contract-955 §1 编号 1-10 序）。

    Args:
        deps: 工具依赖（outline/chapter + audit service 实例 + 绑定项目）。

    Returns:
        十个可执行 Tool；func 成功/失败均返回 JSON 信封且不抛异常。
    """

    @instrument(caller_type="tool")
    async def _list_outlines(
        level: str | None = None,
        search: str | None = None,
        **kwargs: object,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            try:
                bound_project_id = _bind_project_id(deps, kwargs.get("project_id"))
                items = await _fetch_all_outlines(deps, bound_project_id, search=search)
                outlines_by_id = {str(o.id): o for o in items}
                rows: list[dict[str, Any]] = []
                for outline in items:
                    if level is not None and outline.level != level:
                        continue
                    dumped = outline.model_dump(mode="json")
                    volume_title: str | None = None
                    if dumped["volume_id"] is not None:
                        try:
                            get_volume = getattr(deps.chapter_service, "get_volume", None)
                            if callable(get_volume):
                                maybe = get_volume(_coerce_uuid(dumped["volume_id"]))
                                volume = await maybe if asyncio.iscoroutine(maybe) else None
                                volume_title = volume.title if volume is not None else None
                        except Exception:
                            volume_title = None
                    row = {
                        "id": dumped["id"],
                        "name": dumped["name"],
                        "level": dumped["level"],
                        "sort_order": dumped["sort_order"],
                        "parent_chain": await _build_parent_chain(
                            deps,
                            outlines_by_id,
                            outline.parent_id,
                        ),
                        "volume_id": dumped["volume_id"],
                        "volume_title": volume_title,
                    }
                    rows.append(row)
                return _ok(rows)
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _get_outline(
        outline_id: uuid.UUID | str,
        include_plot_points: bool = False,
        **kwargs: object,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            try:
                outline = await deps.outline_service.get_outline(_coerce_uuid(outline_id))  # type: ignore[attr-defined]  # 鸭子类型：outline_service 按契约提供 get_outline
                if outline is None:
                    return json.dumps({"ok": False, "error": "大纲条目不存在"}, ensure_ascii=False)
                outlines_by_id = {str(outline.id): outline}
                dumped = outline.model_dump(mode="json")
                dumped["parent_chain"] = await _build_parent_chain(
                    deps,
                    outlines_by_id,
                    outline.parent_id,
                )
                if include_plot_points:
                    list_points = deps.outline_service.list_points  # type: ignore[attr-defined]  # 鸭子类型字段
                    points: list[PlotPoint] = await list_points(outline.id)
                    arc_names = await _resolve_arc_names(deps, points)
                    dumped["plot_points"] = _enrich_points_with_arc_name(points, arc_names)
                return _ok(dumped)
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _list_plot_points(
        outline_id: uuid.UUID | str,
        **kwargs: object,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            try:
                list_points = deps.outline_service.list_points  # type: ignore[attr-defined]  # 鸭子类型字段
                points: list[PlotPoint] = await list_points(_coerce_uuid(outline_id))
                arc_names = await _resolve_arc_names(deps, points)
                return _ok(_enrich_points_with_arc_name(points, arc_names))
            except Exception as exc:
                return _fail(exc)

    @instrument(caller_type="tool")
    async def _create_overall_outline(
        project_id: uuid.UUID | str | None = None,
        name: str = "",
        description: str = "",
        sort_order: int = 0,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            _project_id = _bind_project_id(deps, project_id)
            try:
                all_outlines = await _fetch_all_outlines(deps, _project_id)
                existing_roots = [o for o in all_outlines if o.level == "overall"]
                if existing_roots:
                    root = existing_roots[0]
                    _raise_error(
                        f"整体大纲已存在：「{root.name}」（id={root.id}），不允许重复创建整本根"
                    )
                outline = await deps.outline_service.create_outline(  # type: ignore[attr-defined]  # 鸭子类型：outline_service 按契约提供 create_outline
                    project_id=_project_id,
                    name=name,
                    description=description,
                    sort_order=sort_order,
                    level="overall",
                    parent_id=None,
                )
                await _audit(
                    deps,
                    _project_id,
                    summary="create_overall_outline_created",
                )
                return json.dumps(
                    {
                        "ok": True,
                        "outline_id": str(outline.id),
                        "name": name,
                        "level": "overall",
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                await _audit(
                    deps,
                    _project_id,
                    summary="create_overall_outline_create_failed",
                )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @instrument(caller_type="tool")
    async def _create_volume_outline(
        project_id: uuid.UUID | str | None = None,
        name: str = "",
        description: str = "",
        sort_order: int = 0,
        overall: str | None = None,
        volume_name: str | None = None,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            _project_id = _bind_project_id(deps, project_id)
            try:
                all_outlines = await _fetch_all_outlines(deps, _project_id)
                roots = [o for o in all_outlines if o.level == "overall"]
                if len(roots) == 0:
                    _raise_error("未找到整体大纲（整本根），请先用 create_overall_outline 创建")
                if len(roots) > 1:
                    if overall is None:
                        _raise_error(
                            "存在多个整体大纲（防御性异常数据），请用 overall 参数指定；"
                            f"候选：{_fmt_candidates(roots)}"
                        )
                    matched = [o for o in roots if o.name == overall]
                    if not matched:
                        _raise_error(
                            f"整本大纲名称「{overall}」未找到，候选：{_fmt_candidates(roots)}"
                        )
                    root = matched[0]
                else:
                    root = roots[0]
                volume_id: uuid.UUID | None = None
                if volume_name is not None:
                    volumes = await deps.chapter_service.list_volumes(_project_id)  # type: ignore[attr-defined]  # 鸭子类型：chapter_service 按契约提供 list_volumes
                    matched_volumes = [v for v in volumes if v.title == volume_name]
                    if not matched_volumes:
                        _raise_error(f"写作卷「{volume_name}」未找到")
                    volume = min(
                        matched_volumes,
                        key=lambda v: getattr(v, "order_index", 0),
                    )
                    volume_id = _coerce_uuid(volume.id)
                outline = await deps.outline_service.create_outline(  # type: ignore[attr-defined]  # 鸭子类型：outline_service 按契约提供 create_outline
                    project_id=_project_id,
                    name=name,
                    description=description,
                    sort_order=sort_order,
                    level="volume",
                    parent_id=root.id,
                    volume_id=volume_id,
                )
                await _audit(
                    deps,
                    _project_id,
                    summary="create_volume_outline_created",
                )
                return json.dumps(
                    {
                        "ok": True,
                        "outline_id": str(outline.id),
                        "name": name,
                        "level": "volume",
                        "parent_id": str(root.id),
                        "volume_id": str(volume_id) if volume_id is not None else None,
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                await _audit(
                    deps,
                    _project_id,
                    summary="create_volume_outline_create_failed",
                )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @instrument(caller_type="tool")
    async def _create_chapter_outline(
        project_id: uuid.UUID | str | None = None,
        name: str = "",
        volume_outline_name: str = "",
        description: str = "",
        sort_order: int = 0,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            _project_id = _bind_project_id(deps, project_id)
            try:
                resolved = await _resolve_unique_outline(
                    deps,
                    _project_id,
                    name=volume_outline_name,
                    level="volume",
                    not_found="卷大纲「{name}」不存在，请先创建卷大纲或用 list_outlines 确认名称",
                    ambiguous="卷大纲「{name}」存在多个同名条目（异常数据），候选：{candidates}",
                )
                if isinstance(resolved, str):
                    _raise_error(resolved)
                outline = await deps.outline_service.create_outline(  # type: ignore[attr-defined]  # 鸭子类型：outline_service 按契约提供 create_outline
                    project_id=_project_id,
                    name=name,
                    description=description,
                    sort_order=sort_order,
                    level="chapter",
                    parent_id=resolved.id,
                )
                await _audit(
                    deps,
                    _project_id,
                    summary="create_chapter_outline_created",
                )
                return json.dumps(
                    {
                        "ok": True,
                        "outline_id": str(outline.id),
                        "name": name,
                        "level": "chapter",
                        "parent_id": str(resolved.id),
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                await _audit(
                    deps,
                    _project_id,
                    summary="create_chapter_outline_create_failed",
                )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    def _make_update_outline(
        *,
        tool_name: str,
        expected_level: str,
        wrong_level_message: str,
    ) -> Any:
        @instrument(caller_type="tool")
        async def _update_outline(
            project_id: uuid.UUID | str | None = None,
            outline_id: uuid.UUID | str = "",
            name: str | None = None,
            description: str | None = None,
            sort_order: int | None = None,
        ) -> str:
            async with _tool_db_lock_mod.get_tool_db_lock():
                _project_id = _bind_project_id(deps, project_id)
                try:
                    existing = await deps.outline_service.get_outline(_coerce_id(outline_id))  # type: ignore[attr-defined]  # 鸭子类型：outline_service 按契约提供 get_outline
                    if existing is None:
                        _raise_error("大纲条目不存在")
                    if existing.level != expected_level:
                        _raise_error(wrong_level_message.format(level=existing.level))
                    update_fields: dict[str, Any] = {}
                    if name is not None:
                        update_fields["name"] = name
                    if description is not None:
                        update_fields["description"] = description
                    if sort_order is not None:
                        update_fields["sort_order"] = sort_order
                    outline = await deps.outline_service.update_outline(  # type: ignore[attr-defined]  # 鸭子类型：outline_service 按契约提供 update_outline
                        _coerce_id(outline_id),
                        OutlineUpdate(**update_fields),
                    )
                    if outline is None:
                        _raise_error("大纲条目不存在")
                    await _audit(
                        deps,
                        _project_id,
                        summary=f"{tool_name}_updated",
                    )
                    return json.dumps(
                        {
                            "ok": True,
                            "outline_id": str(outline.id),
                            "name": outline.name or name or "",
                        },
                        ensure_ascii=False,
                    )
                except Exception as exc:
                    await _audit(
                        deps,
                        _project_id,
                        summary=f"{tool_name}_update_failed",
                    )
                    return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

        return _update_outline

    @instrument(caller_type="tool")
    async def _create_plot_point(
        project_id: uuid.UUID | str | None = None,
        outline_id: uuid.UUID | str | None = None,
        chapter_outline_name: str | None = None,
        name: str = "",
        type: str = "",
        description: str = "",
        arc: str | None = None,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            _project_id = _bind_project_id(deps, project_id)
            try:
                if (outline_id is None) == (chapter_outline_name is None):
                    _raise_error("outline_id 与 chapter_outline_name 必须恰好提供一个")
                if outline_id is not None:
                    resolved_outline_id = _coerce_uuid(outline_id)
                else:
                    resolved = await _resolve_unique_outline(
                        deps,
                        _project_id,
                        name=chapter_outline_name or "",
                        level=None,
                        not_found="大纲「{name}」不存在，请先创建或用 list_outlines 确认名称",
                        ambiguous=(
                            "大纲「{name}」存在多个同名条目（异常数据），候选：{candidates}"
                        ),
                    )
                    if isinstance(resolved, str):
                        _raise_error(resolved)
                    resolved_outline_id = _coerce_uuid(resolved.id)
                arc_id: uuid.UUID | None = None
                if arc is not None:
                    resolved_arc = await _resolve_arc_name(deps, _project_id, arc)
                    if isinstance(resolved_arc, str):
                        _raise_error(resolved_arc)
                    arc_id = _coerce_uuid(resolved_arc)
                point = await deps.outline_service.create_point(  # type: ignore[attr-defined]  # 鸭子类型：outline_service 按契约提供 create_point
                    outline_id=resolved_outline_id,
                    name=name,
                    type=type,
                    description=description,
                    position=None,
                    arc_id=arc_id,
                )
                await _audit(
                    deps,
                    _project_id,
                    summary="create_plot_point_created",
                )
                return json.dumps(
                    {
                        "ok": True,
                        "plot_point_id": str(point.id),
                        "name": name,
                        "outline_id": str(point.outline_id),
                        "position": point.position,
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                await _audit(
                    deps,
                    _project_id,
                    summary="create_plot_point_create_failed",
                )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @instrument(caller_type="tool")
    async def _update_plot_point(
        project_id: uuid.UUID | str | None = None,
        plot_point_id: uuid.UUID | str = "",
        name: str | None = None,
        type: str | None = None,
        description: str | None = None,
        position: int | None = None,
        arc_id: str | None = None,
    ) -> str:
        async with _tool_db_lock_mod.get_tool_db_lock():
            _project_id = _bind_project_id(deps, project_id)
            try:
                update_fields: dict[str, Any] = {}
                if name is not None:
                    update_fields["name"] = name
                if type is not None:
                    update_fields["type"] = type
                if description is not None:
                    update_fields["description"] = description
                if position is not None:
                    update_fields["position"] = position
                if arc_id is not None:
                    update_fields["arc_id"] = arc_id  # "" 清除 / UUID 串由模型 mode=before 归一
                point = await deps.outline_service.update_point(  # type: ignore[attr-defined]  # 鸭子类型：outline_service 按契约提供 update_point
                    _coerce_id(plot_point_id),
                    PlotPointUpdate(**update_fields),
                )
                if point is None:
                    _raise_error("情节点不存在")
                await _audit(
                    deps,
                    _project_id,
                    summary="update_plot_point_updated",
                )
                return json.dumps(
                    {
                        "ok": True,
                        "plot_point_id": str(point.id),
                        "name": point.name or name or "",
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                await _audit(
                    deps,
                    _project_id,
                    summary="update_plot_point_update_failed",
                )
                return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    return [
        Tool(spec=LIST_OUTLINES_SPEC, func=_list_outlines),
        Tool(spec=GET_OUTLINE_SPEC, func=_get_outline),
        Tool(spec=LIST_PLOT_POINTS_SPEC, func=_list_plot_points),
        Tool(spec=CREATE_OVERALL_OUTLINE_SPEC, func=_create_overall_outline),
        Tool(spec=CREATE_VOLUME_OUTLINE_SPEC, func=_create_volume_outline),
        Tool(spec=CREATE_CHAPTER_OUTLINE_SPEC, func=_create_chapter_outline),
        Tool(
            spec=UPDATE_VOLUME_OUTLINE_SPEC,
            func=_make_update_outline(
                tool_name="update_volume_outline",
                expected_level="volume",
                wrong_level_message=(
                    "目标大纲层级为「{level}」，不是卷大纲，请改用 update_chapter_outline"
                ),
            ),
        ),
        Tool(
            spec=UPDATE_CHAPTER_OUTLINE_SPEC,
            func=_make_update_outline(
                tool_name="update_chapter_outline",
                expected_level="chapter",
                wrong_level_message=(
                    "目标大纲层级为「{level}」，不是章大纲，请改用 update_volume_outline"
                ),
            ),
        ),
        Tool(spec=CREATE_PLOT_POINT_SPEC, func=_create_plot_point),
        Tool(spec=UPDATE_PLOT_POINT_SPEC, func=_update_plot_point),
    ]
