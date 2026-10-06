"""F27 agentic writer 装配——build_deep_agent 组装 5 只读 + save_draft + writer_agent 模板.

F39 M3（spec §5.2）：白名单确定性强制扩展——tool_ids 过滤工具目录（include
透传 build_reader_tools，save_draft 仅当 None 或白名单含名时追加）；skill_ids
过滤 skill 库（_append_skills 按白名单顺序把 skill content 拼进 system_prompt，
base 前 skill 后）。skill_lookup 由装配层经 AgenticWriterDeps.skill_lookup
注入（契约疑点 1 裁定：deps 可选字段）。

装配层（infrastructure，可 import deepagents/langchain）：
- AgenticWriterDeps: 装配依赖（service 实例注入，鸭子类型，镜像
  ReaderToolDeps/SaveDraftToolDeps）
- build_writer_agent_system_prompt: 渲染 writer_agent.yaml system_prompt
  （模板无变量写死——render 空 dict 原样返回）
- build_agentic_writer: build_reader_tools(写作轨白名单过滤，10 只读) +
  build_save_draft_tool（写作轨专用 11 项，#1507）
  → build_deep_agent（deepagents ReAct 循环，工具循环在 agent 内建）
- _append_skills: skill 白名单拼接纯函数（已下沉 `domain/services/skill_assembly.py`，
  本模块以别名引用同一实现；base 前 skill 后，查不到跳过；#1472）
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from inkflow.domain.services.skill_assembly import append_skills as _append_skills
from inkflow.infrastructure.agent.deepagents.harness import build_deep_agent
from inkflow.infrastructure.agent.tools.reader_tools import (
    _TOOL_SPECS,
    ReaderToolDeps,
    build_reader_tools,
)
from inkflow.infrastructure.agent.tools.save_draft_tool import (
    SaveDraftToolDeps,
    build_save_draft_tool,
)
from inkflow.logging import instrument

_READER_TOOL_NAMES: frozenset[str] = frozenset(spec.name for spec in _TOOL_SPECS)
"""reader 工具目录全名集（= `reader_tools._TOOL_SPECS` 口径）——#1507 守卫基准。"""

_WRITER_TRACK_TOOL_NAMES: list[str] = [
    # ── reader 目录 10（序 = reader_tools._TOOL_SPECS 原序）──
    "search_characters",
    "get_character",
    "check_foreshadowing",
    "list_foreshadowing",
    "get_foreshadowing",
    "list_world_settings",
    "get_world_setting",
    "get_prior_summary",
    "audit_chapter",
    "count_words",
    # ── 落草稿写工具（reader 目录外，写作轨唯一写面）──
    "save_draft",
]
"""写作轨**专用**工具白名单（#1507）——写作轨 ≠ chat 写手角色。

⚠️ 与 chat 轨写手角色的 grants 展开（18 名）**刻意不同口径**：写手 grants 里
`list_outlines` / `get_outline` / `list_plot_points` / `list_maps` / `generate` /
`continue` / `revise` 7 名对写作轨是超职责授权（写手 system_prompt 只点名前文摘要 /
`search_characters` / `check_foreshadowing` / `save_draft`；大纲走 `{outline}` 模板
变量注入而非工具）→ 本清单如实声明写作轨真用到的 11 项（reader 目录 10 + `save_draft`）。
chat 轨写手角色仍走 grants（18 个），两轨互不影响（specs/f27-writer-agent §5.1）。

本常量是 `tool_ids is None` 的**唯一默认来源**，也是 `resolve_writer_authorization()`
的返回源——旧实现「grants 18 / 物化 11 / 静默丢弃 7」的三口径分叉由此消除。"""


def _validate_writer_track_tools(names: list[str]) -> None:
    """写作轨工具面守卫（#1507）：除 `save_draft` 外，工具名必须 ∈ reader 目录。

    旧实现把 grants 展开（18）直接喂 `build_reader_tools(include=…)`，目录外 7 名被
    **静默**滤掉——授权面与物化面长期分叉，之后改 grants 不生效也不报错（#1476 同族
    「装配链静默断」）。此处把「目录外语工具名」由静默丢弃改为**响亮失败**，杜绝退化。
    """
    outside = sorted(n for n in names if n not in _READER_TOOL_NAMES and n != "save_draft")
    if outside:
        raise ValueError(
            "写作轨工具名必须 ∈ reader 目录（或 save_draft），目录外名会被静默丢弃 → 拒收："
            f"{outside}。若确需扩权，请改 `_WRITER_TRACK_TOOL_NAMES` 并同步 "
            "specs/f27-writer-agent（#1507）。"
        )


def resolve_writer_authorization() -> tuple[list[str], list[str]]:
    """写作轨授权来源（#1181 → #1507）：写作轨**专用**工具清单 + 写手 skill 目录名。

    ⚠️ 写作轨 ≠ chat 写手角色（#1507）：工具面取自本模块私有白名单
    `_WRITER_TRACK_TOOL_NAMES`（11 项），**不再**复用内置「写手」Agent 的 grants
    展开（18 名里 7 名对写作轨超职责 → 旧实现按 reader 目录过滤时被静默丢弃，授权面
    与物化面分叉）。skill 目录名仍取自内置写手实体（`writing-methodology`，职责同源，
    无分叉问题）。

    Returns:
        (tool_ids, skill_ids)：写作轨专用工具名清单 + skill 目录名清单（F39 #522）。
    """
    from inkflow.domain.services.agent_entity_service import BUILTIN_AGENT_SPECS

    spec = next(s for s in BUILTIN_AGENT_SPECS if s["role_key"] == "writer")
    return list(_WRITER_TRACK_TOOL_NAMES), [spec["skill_name"]]


@dataclass
class AgenticWriterDeps:
    """装配依赖——service 实例注入（鸭子类型，镜像 ReaderToolDeps/SaveDraftToolDeps）."""

    character_service: object
    foreshadowing_service: object
    summary_service: object
    chapter_audit_service: object
    draft_service: object
    audit_service: object
    world_service: object | None = None
    """#1180：世界观只读 service（有 list_settings/get_setting，WorldService 形态）。
    未注入 → world 工具不物化（与 ReaderToolDeps.world_service 同语义）；
    装配层两 factory 均注入（镜像 chat 轨 deps_chat_agent.py:228）。"""
    skill_lookup: Callable[[str], object | None] | None = None
    """skill 查表函数（F39 M3 + #522）：按 skill 目录名取 Skill 鸭子对象
    （含 name/content），None = 未注入（仅 skill_ids 非 None 时读取）。"""
    volume_lookup: Callable[[uuid.UUID, uuid.UUID | None], Awaitable[str | None]] | None = None
    """#976 D3：草稿卷解析闭包（project_id, chapter_id → 卷 UUID 字符串），
    透传给 save_draft 工具；None = 未注入（草稿 volume_id=None，不归卷）。"""


def build_writer_agent_system_prompt(
    prompt_manager,
    *,
    project_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
    outline: str = "",
    context: str = "",
    min_words: int = 2000,
    style_hint: str = "",
) -> str:
    """渲染 writer_agent.yaml system_prompt（#275: 注入当前项目/章节 UUID）。

    变量 dict 恒含 project_id/chapter_id 键（None → 空串）——模板 variables
    声明后 PromptManager.render 的 validate 要求两键必传。

    #1174/#1177 死参数族（原 agentic_writer.py:64-89 声明四参从不读取）：
    outline/context/min_words/style_hint 现一并进 render 变量 dict，模板
    variables 同步声明 → 四值可达渲染产物。
    """
    template = prompt_manager.load("writer_agent")
    rendered = prompt_manager.render(
        template,
        {
            "project_id": str(project_id) if project_id is not None else "",
            "chapter_id": str(chapter_id) if chapter_id is not None else "",
            "outline": outline,
            "context": context,
            "min_words": str(min_words),
            "style_hint": style_hint,
        },
    )
    if rendered.messages:
        return str(rendered.messages[0]["content"])
    return str(template.system_prompt)


class DeepAgentInvokeAdapter:
    """deepagents 0.7.5 invoke 形态适配——服务层契约传裸消息列表，
    真实 graph 需要 {"messages": [...]} dict（真实冒烟 2026-08-10 实测
    InvalidUpdateError: Expected dict）。

    #953：async 优先——真实 CompiledStateGraph.ainvoke 是协程函数 → await 在宿主
    事件循环执行（工具 coroutine 由 ToolNode async 路径在宿主循环运行）；sync
    graph.invoke 兜底保留（MagicMock 鸭子 / 无 async 能力实现，同步调用线程视角
    不变）。旧注释"graph.invoke 为同步方法（TypeError await）"作废：那是 sync
    返回 dict 时 await 的 TypeError，与本 adapter 的 async 化不冲突。"""

    def __init__(self, inner: object) -> None:
        self._inner = inner

    @instrument(caller_type="agent")
    async def invoke(self, messages: list, config: dict | None = None) -> dict:
        # #821：显式 config 原样透传；缺失时自动补 thread_id（InMemorySaver 兜底）
        # ——以下两分支共用该兜底逻辑
        if config is None:
            config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        # #953：async 优先——真实 CompiledStateGraph.ainvoke 是协程函数 → await 在
        # 宿主循环执行（sync graph.invoke 走 ToolNode sync 桥 → worker 新循环跑工具
        # 协程，跨循环 acquire 模块锁抛 bound to a different event loop，book run 崩溃）
        ainvoke = getattr(self._inner, "ainvoke", None)
        if ainvoke is not None and inspect.iscoroutinefunction(ainvoke):
            result = await ainvoke({"messages": messages}, config=config)
        else:
            # 既有同步分支原样保留：MagicMock 鸭子（.ainvoke 为 MagicMock 属性非协程
            # 函数）/无 async 能力实现回退；deepagents 输入 {"messages": [...]}
            result = self._inner.invoke({"messages": messages}, config=config)  # type: ignore[attr-defined]  # 鸭子类型：deepagents CompiledStateGraph
        if isinstance(result, Awaitable):
            return cast(dict, await result)
        return cast(dict, result)


@instrument(caller_type="agent")
def build_agentic_writer(
    *,
    model: str,
    api_key: str,
    base_url: str,
    deps: AgenticWriterDeps,
    system_prompt: str,
    tool_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
    profile_key: str | None = None,
    expected_project_id: uuid.UUID | None = None,
    expected_chapter_id: uuid.UUID | None = None,
    expected_source_outline_id: uuid.UUID | None = None,
    expected_volume_outline_id: uuid.UUID | None = None,
    reasoning_effort: str | None = None,
):
    """组装 agent：白名单过滤工具 + skill 拼接 → build_deep_agent（deepagents ReAct 循环）.

    Args:
        model: LLM 模型标识（registry 前缀校准在 build_deep_agent 内：zhipu/glm-4.5 → zai/glm-4.5）.
        api_key: LLM API Key（可空）.
        base_url: OpenAI 兼容 base_url（可空）.
        deps: 装配依赖（5 只读 service + draft/audit service）.
        system_prompt: writer_agent 系统提示（build_writer_agent_system_prompt 产物）.
        tool_ids: 写作轨工具白名单（工具目录 name 列表）；None = 写作轨专用默认清单
            （`_WRITER_TRACK_TOOL_NAMES`，reader 10 + save_draft，#1507 唯一默认源）；
            [names] = 只 build 白名单命中项，
            目录外名（非 "save_draft"）→ ValueError（#1507 响亮失败，不再静默丢弃），
            save_draft 仅当 None 或白名单含 "save_draft" 时追加.
        skill_ids: skill 白名单（skill 目录名列表，#522）；None = 不拼 skill
            （F27 现行为）；[names] = 按白名单顺序把命中 skill content 追加
            到 system_prompt 之后（base 前 skill 后，查不到跳过）.
        profile_key: deepagents HarnessProfile key（None = 按模型名自动确保）.
        expected_project_id: #275/#1476 期望项目上下文——每次 run 由装配层注入请求真实值：
            ① 检索工具（#680 闭包绑定入口）：作为 `build_reader_tools(project_id=…)` 的
            绑定值，6 个项目域检索工具据此查库（schema 不含 project_id → LLM 无法指向
            别的项目，跨项目隔离是结构性的）；
            ② save_draft 写工具防御用（每次 run 由装配层注入请求真实值，工具参数不符
            → 拒绝）.
        expected_chapter_id: #275 期望章节上下文——save_draft 工具防御用
            （每次 run 由装配层注入请求真实值，工具参数不符 → 拒绝）.
        expected_source_outline_id: #996 来源大纲章节点锚点——透传给 save_draft
            工具（create 落库 drafts.source_outline_id；chat 轨 None）.
        expected_volume_outline_id: #996 卷 outline 节点锚点——透传给 save_draft
            工具（volume_lookup 回退键；chat 轨 None）.
        reasoning_effort: F59-M4 可选思考档位——透传 build_deep_agent
            （default/None 由 capability_probe 剥离，本层只解析不判断能力）.

    Returns:
        DeepAgentInvokeAdapter（包装 deepagents CompiledStateGraph，服务层
        契约裸消息列表 → graph {"messages": [...]} dict 形态）.
    """
    reader_deps = ReaderToolDeps(
        character_service=deps.character_service,
        foreshadowing_service=deps.foreshadowing_service,
        summary_service=deps.summary_service,
        chapter_audit_service=deps.chapter_audit_service,
        # #1180 第 2 重锁：world_service 未注入 → world 工具根本不物化
        # （reader_tools.py 过滤条件），单改白名单无效。
        world_service=deps.world_service,
    )
    # #1507：写作轨工具名先经守卫——目录外名（非 save_draft）→ ValueError（响亮失败，
    # 不再静默丢弃）。默认源 = 写作轨专用白名单（`tool_ids=None`）。
    include_names = tool_ids if tool_ids is not None else _WRITER_TRACK_TOOL_NAMES
    _validate_writer_track_tools(include_names)
    # #1476：检索工具的项目上下文注入——`build_reader_tools` 的 `project_id` 形参才是
    # #680 的闭包绑定入口（工具 schema 不含 project_id，由装配期绑定）。写作轨此前漏传
    # → `bound_project_id=None` → 6 个项目域检索工具全按 None 查库（issue #1476：
    # search_characters / list_world_settings / list_foreshadowing 返回「项目不存在」，
    # Agent 因此盲写）。此处以装配期 `expected_project_id`（= 请求真实项目）绑定，
    # 与 chat 轨 `tools/registry.py::_build_all_tools(project_id=…)` 同源语义。
    tools = build_reader_tools(
        reader_deps,
        project_id=expected_project_id,
        include=include_names,
    )
    if tool_ids is None or "save_draft" in tool_ids:
        tools.append(
            build_save_draft_tool(
                SaveDraftToolDeps(
                    draft_service=deps.draft_service,
                    audit_service=deps.audit_service,
                    expected_project_id=expected_project_id,
                    expected_chapter_id=expected_chapter_id,
                    expected_source_outline_id=expected_source_outline_id,
                    expected_volume_outline_id=expected_volume_outline_id,
                    volume_lookup=deps.volume_lookup,
                )
            )
        )
    if skill_ids is not None:
        skill_lookup = deps.skill_lookup
        if skill_lookup is None:
            skill_lookup = _no_skill_lookup
        system_prompt = _append_skills(system_prompt, skill_ids, skill_lookup)
    agent = build_deep_agent(
        model=model,
        api_key=api_key,
        base_url=base_url,
        tools=tools,
        system_prompt=system_prompt,
        profile_key=profile_key,
        reasoning_effort=reasoning_effort,
    )
    return DeepAgentInvokeAdapter(agent)


def _no_skill_lookup(_skill_name: str) -> object | None:
    """默认 skill 查表函数：装配层未注入时任何目录名均查不到（防御语义）."""
    return None


# #1472：skill 白名单拼接纯函数已下沉 domain（`skill_assembly.append_skills`），
# 本模块顶部以 `_append_skills` 别名引用**同一实现**（写手轨与管线链路共用，
# 避免两份实现；domain 层不得 import infrastructure —— AGENTS.md §4.2）。
