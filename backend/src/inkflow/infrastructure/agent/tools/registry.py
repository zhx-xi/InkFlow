"""#838/#954 统一工具目录 — ALL_TOOL_SPECS / TOOL_REGISTRY / UnifiedToolDeps / grants 授权物化.

本模块聚合 9 组 35 个工具 spec（reader/save_draft/setting_write/setting_update/
world_rw/memory/writing/delete/agent_chain）为统一目录，供 API 工具目录
（GET /agents/tools）、`_validate_tool_ids` 白名单校验与 chat 路径运行时物化
（deps_chat_agent._run_single_agent）消费。

标记规则（#838 用户拍板）:
- 核心工具 9 个（agent_run/agent_call + 7 个删除类）: allow_custom_agent=False,
  is_core=True —— 不进 TOOL_REGISTRY，自定义 agent 不可勾选/调用。
- 其余 26 个默认暴露（allow_custom_agent=True, is_core=False）。

TOOL_REGISTRY 保留为兼容别名 = allow_custom_agent 过滤子集（26 个），供
`_validate_tool_ids`/内置 seed/CLI `tools list` 等既有消费方（目录外名仍拒绝）。

GRANT_TOOL_MAP（F58 #954）为 (ToolDomain, ToolOp) → 工具名的唯一真相源：
expand_grants 按映射插入序展开授权；grants_from_tool_ids 兼作旧 tool_ids 的
反查迁移入口；resolve_grants 统一读取（grants 优先 / tool_ids 回退）。
build_tools_by_ids/build_tools_by_grants 均调 9 组 build 后按 spec.name 过滤
拼接（未知名忽略，防御）；None 子 deps 跳过该组 build（delete 子 deps 在
conversation 删除授权为 manual 时为 None——核心工具本就不允许自定义 agent 勾选）。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from inkflow.domain.models.agent_grants import GrantEntry, ToolDomain, ToolOp
from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.domain.ports.agent_errors import ToolReferenceError
from inkflow.infrastructure.agent.tools.agent_chain_tools import (
    AGENT_CALL_SPEC,
    AGENT_RUN_SPEC,
    AgentChainToolDeps,
    build_agent_chain_tools,
)
from inkflow.infrastructure.agent.tools.delete_tools import (
    DELETE_CHARACTER_SPEC,
    DELETE_FORESHADOWING_SPEC,
    DELETE_MAP_SPEC,
    DELETE_OUTLINE_SPEC,
    DELETE_TIMELINE_EVENT_SPEC,
    DELETE_WORLD_SETTING_SPEC,
    MEMORY_REMOVE_SPEC,
    DeleteToolDeps,
    build_delete_tools,
)
from inkflow.infrastructure.agent.tools.memory_tools import (
    MEMORY_ADD_SPEC,
    MEMORY_LIST_SPEC,
    MEMORY_UPDATE_SPEC,
    MemoryToolDeps,
    build_memory_tools,
)
from inkflow.infrastructure.agent.tools.reader_tools import (
    _TOOL_SPECS,
    ReaderToolDeps,
    Tool,
    build_reader_tools,
)
from inkflow.infrastructure.agent.tools.save_draft_tool import (
    SAVE_DRAFT_SPEC,
    SaveDraftToolDeps,
    build_save_draft_tool,
)
from inkflow.infrastructure.agent.tools.setting_update_tools import (
    UPDATE_CHARACTER_SPEC,
    UPDATE_OUTLINE_SPEC,
    UPDATE_WORLD_SETTING_SPEC,
    SettingUpdateToolDeps,
    build_setting_update_tools,
)
from inkflow.infrastructure.agent.tools.setting_write_tools import (
    CREATE_CHARACTER_SPEC,
    CREATE_OUTLINE_SPEC,
    CREATE_WORLD_SETTING_SPEC,
    SettingWriteToolDeps,
    build_setting_write_tools,
)
from inkflow.infrastructure.agent.tools.world_readwrite_tools import (
    CREATE_FORESHADOWING_SPEC,
    CREATE_MAP_SPEC,
    CREATE_TIMELINE_EVENT_SPEC,
    LIST_MAPS_SPEC,
    LIST_TIMELINE_EVENTS_SPEC,
    UPDATE_FORESHADOWING_SPEC,
    UPDATE_MAP_SPEC,
    UPDATE_TIMELINE_EVENT_SPEC,
    WorldRwToolDeps,
    build_world_rw_tools,
)
from inkflow.infrastructure.agent.tools.writing_tools import (
    CONTINUE_SPEC,
    GENERATE_SPEC,
    REVISE_SPEC,
    WritingToolDeps,
    build_writing_tools,
)

logger = logging.getLogger(__name__)

# ── 统一工具目录（顺序契约：#838 建议序 = reader 5 → save_draft → 设定写 3 →
#    设定改 3 → 世界读写 8 → 记忆 3 → 写作 3 → 删除 7 → agent 链 2） ──


ALL_TOOL_SPECS: list[ToolSpec] = [
    *_TOOL_SPECS,
    SAVE_DRAFT_SPEC,
    CREATE_CHARACTER_SPEC,
    CREATE_WORLD_SETTING_SPEC,
    CREATE_OUTLINE_SPEC,
    UPDATE_CHARACTER_SPEC,
    UPDATE_WORLD_SETTING_SPEC,
    UPDATE_OUTLINE_SPEC,
    LIST_MAPS_SPEC,
    CREATE_MAP_SPEC,
    UPDATE_MAP_SPEC,
    LIST_TIMELINE_EVENTS_SPEC,
    CREATE_TIMELINE_EVENT_SPEC,
    UPDATE_TIMELINE_EVENT_SPEC,
    CREATE_FORESHADOWING_SPEC,
    UPDATE_FORESHADOWING_SPEC,
    MEMORY_LIST_SPEC,
    MEMORY_ADD_SPEC,
    MEMORY_UPDATE_SPEC,
    GENERATE_SPEC,
    CONTINUE_SPEC,
    REVISE_SPEC,
    DELETE_CHARACTER_SPEC,
    DELETE_WORLD_SETTING_SPEC,
    DELETE_OUTLINE_SPEC,
    DELETE_MAP_SPEC,
    DELETE_TIMELINE_EVENT_SPEC,
    DELETE_FORESHADOWING_SPEC,
    MEMORY_REMOVE_SPEC,
    AGENT_RUN_SPEC,
    AGENT_CALL_SPEC,
]

TOOL_REGISTRY: list[ToolSpec] = [s for s in ALL_TOOL_SPECS if s.allow_custom_agent]
"""兼容别名：自定义 agent 可见工具（26 个，= ALL_TOOL_SPECS 过滤 allow_custom_agent）."""


GRANT_TOOL_MAP: dict[tuple[ToolDomain, ToolOp], list[str]] = {
    (ToolDomain.OUTLINE, ToolOp.WRITE): ["create_outline", "update_outline"],
    (ToolDomain.OUTLINE, ToolOp.DELETE): ["delete_outline"],
    (ToolDomain.CHARACTER, ToolOp.READ): ["search_characters"],
    (ToolDomain.CHARACTER, ToolOp.WRITE): ["create_character", "update_character"],
    (ToolDomain.CHARACTER, ToolOp.DELETE): ["delete_character"],
    (ToolDomain.WORLD, ToolOp.READ): ["list_maps"],
    (ToolDomain.WORLD, ToolOp.WRITE): [
        "create_world_setting",
        "update_world_setting",
        "create_map",
        "update_map",
    ],
    (ToolDomain.WORLD, ToolOp.DELETE): ["delete_world_setting", "delete_map"],
    (ToolDomain.TIMELINE, ToolOp.READ): ["list_timeline_events"],
    (ToolDomain.TIMELINE, ToolOp.WRITE): [
        "create_timeline_event",
        "update_timeline_event",
    ],
    (ToolDomain.TIMELINE, ToolOp.DELETE): ["delete_timeline_event"],
    (ToolDomain.FORESHADOWING, ToolOp.READ): ["check_foreshadowing"],
    (ToolDomain.FORESHADOWING, ToolOp.WRITE): [
        "create_foreshadowing",
        "update_foreshadowing",
    ],
    (ToolDomain.FORESHADOWING, ToolOp.DELETE): ["delete_foreshadowing"],
    (ToolDomain.MEMORY, ToolOp.READ): ["memory_list"],
    (ToolDomain.MEMORY, ToolOp.WRITE): ["memory_add", "memory_update"],
    (ToolDomain.MEMORY, ToolOp.DELETE): ["memory_remove"],
    (ToolDomain.WRITING, ToolOp.READ): [
        "get_prior_summary",
        "audit_chapter",
        "count_words",
    ],
    (ToolDomain.WRITING, ToolOp.WRITE): ["save_draft", "generate", "continue", "revise"],
}
"""F58 授权格映射（spec §2.1 逐字；插入序 = 展开序，空格子键不入表）."""


TOOL_NAME_TO_CELL: dict[str, tuple[ToolDomain, ToolOp]] = {
    name: cell for cell, names in GRANT_TOOL_MAP.items() for name in names
}
"""工具名 → 所属 (domain, op) 格（grants_from_tool_ids 反查迁移索引）."""


def expand_grants(grants: list[GrantEntry]) -> list[str]:
    """GRANT_TOOL_MAP 展开 → 工具名清单（映射插入序拼接，去重保序）."""
    ops_by_domain = {entry.domain: set(entry.ops) for entry in grants}
    expanded: list[str] = []
    for (domain, op), names in GRANT_TOOL_MAP.items():
        if op in ops_by_domain.get(domain, set()):
            expanded.extend(names)
    return expanded


def grants_from_tool_ids(tool_ids: list[str], *, strict: bool) -> list[GrantEntry]:
    """按旧 tool_ids 反查 grants（命中格按首次出现序收集，ops 按枚举序）.

    strict=True（API 写路径）：目录外名或核心名（allow_custom_agent=False）→
    ToolReferenceError；strict=False（存量读取路径）：未识别名忽略并记 WARNING。
    """
    specs = {spec.name: spec for spec in ALL_TOOL_SPECS}
    domain_ops: dict[ToolDomain, set[ToolOp]] = {}
    for tool_id in tool_ids:
        cell = TOOL_NAME_TO_CELL.get(tool_id)
        spec = specs.get(tool_id)
        if cell is None or spec is None or (strict and not spec.allow_custom_agent):
            if strict:
                raise ToolReferenceError()
            logger.warning("grants_from_tool_ids 忽略未识别工具名: %s", tool_id)
            continue
        domain_ops.setdefault(cell[0], set()).add(cell[1])
    return [
        GrantEntry(
            domain=domain,
            ops=[op for op in ToolOp if op in ops],
        )
        for domain, ops in domain_ops.items()
    ]


def resolve_grants(agent: object) -> list[GrantEntry]:
    """统一读取 Agent 授权（grants 非空优先，否则 tool_ids 宽松反查，双空 → []）.

    鸭子对象（Agent | SimpleNamespace | MagicMock）经 getattr 防御读取，镜像
    deps_chat_agent 既有形态。
    """
    grants: list[GrantEntry] = list(getattr(agent, "grants", None) or [])
    if grants:
        return grants
    tool_ids: list[str] = list(getattr(agent, "tool_ids", None) or [])
    return grants_from_tool_ids(tool_ids, strict=False)


@dataclass
class UnifiedToolDeps:
    """统一工具目录聚合依赖（9 组子 deps；None 子 deps = build_tools_by_ids 跳过该组）."""

    reader: ReaderToolDeps | None
    save_draft: SaveDraftToolDeps | None
    setting_write: SettingWriteToolDeps | None
    setting_update: SettingUpdateToolDeps | None
    world_rw: WorldRwToolDeps | None
    memory: MemoryToolDeps | None
    writing: WritingToolDeps | None
    delete: DeleteToolDeps | None
    agent_chain: AgentChainToolDeps | None


def _build_all_tools(
    deps: UnifiedToolDeps,
    project_id: uuid.UUID | str | None,
) -> list[Tool]:
    """调 9 组 build 物化全量工具（None 子 deps 跳过该组，同旧）."""
    all_tools: list[Tool] = []
    if deps.reader is not None:
        all_tools.extend(build_reader_tools(deps.reader, project_id=project_id))
    if deps.save_draft is not None:
        all_tools.append(build_save_draft_tool(deps.save_draft))
    if deps.setting_write is not None:
        all_tools.extend(build_setting_write_tools(deps.setting_write))
    if deps.setting_update is not None:
        all_tools.extend(build_setting_update_tools(deps.setting_update))
    if deps.world_rw is not None:
        all_tools.extend(build_world_rw_tools(deps.world_rw))
    if deps.memory is not None:
        all_tools.extend(build_memory_tools(deps.memory))
    if deps.writing is not None:
        all_tools.extend(build_writing_tools(deps.writing))
    if deps.delete is not None:
        all_tools.extend(build_delete_tools(deps.delete))
    if deps.agent_chain is not None:
        all_tools.extend(build_agent_chain_tools(deps.agent_chain))
    return all_tools


def build_tools_by_ids(
    tool_ids: list[str],
    deps: UnifiedToolDeps,
    project_id: uuid.UUID | str | None = None,
) -> list[Tool]:
    """按 tool_ids 白名单物化工具（F58 过渡：反查展开集 ∩ tool_ids 保原序）.

    Args:
        tool_ids: 自定义 agent 的工具白名单（调用方已过 _validate_tool_ids）。
        deps: 9 组子 deps 聚合；None 子 deps 跳过该组 build。
        project_id: #680 装配期项目 ID，透传 build_reader_tools（闭包绑定；默认 None）。

    Returns:
        按 tool_ids 顺序物化的 Tool 列表（未知名防御性忽略）。
        授权扩权只存在于 grants/build_tools_by_grants/resolve 新路径，本函数
        保持旧精确白名单语义（∩ 交集设计，contract-954 §7.5）。
    """
    all_tools = _build_all_tools(deps, project_id)
    by_name = {t.spec.name: t for t in all_tools}
    granted_names = set(expand_grants(grants_from_tool_ids(tool_ids, strict=False)))
    return [by_name[tid] for tid in tool_ids if tid in granted_names and tid in by_name]


def build_tools_by_grants(
    grants: list[GrantEntry],
    deps: UnifiedToolDeps,
    project_id: uuid.UUID | str | None = None,
) -> list[Tool]:
    """按 grants 授权矩阵物化工具（F58 新路径，扩权语义只在本函数生效）.

    expand_grants → 9 组 build（None 子 deps 跳过该组）→ 按名过滤拼接；
    未知名防御忽略；grants 为空 → []。
    """
    expanded = expand_grants(grants)
    all_tools = _build_all_tools(deps, project_id)
    by_name = {t.spec.name: t for t in all_tools}
    return [by_name[name] for name in expanded if name in by_name]
