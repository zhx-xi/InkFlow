"""#838 统一工具目录 — ALL_TOOL_SPECS / TOOL_REGISTRY / UnifiedToolDeps / build_tools_by_ids.

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

build_tools_by_ids 按 tool_ids 白名单物化工具：调 9 组 build 后按 spec.name
过滤拼接（未知名忽略，防御）；None 子 deps 跳过该组 build（delete 子 deps 在
conversation 删除授权为 manual 时为 None——核心工具本就不允许自定义 agent 勾选）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from inkflow.domain.models.agent_tools import ToolSpec
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


def build_tools_by_ids(
    tool_ids: list[str],
    deps: UnifiedToolDeps,
    project_id: uuid.UUID | str | None = None,
) -> list[Tool]:
    """按 tool_ids 白名单物化工具（调 9 组 build 后按 spec.name 过滤拼接，未知名忽略）.

    Args:
        tool_ids: 自定义 agent 的工具白名单（调用方已过 _validate_tool_ids）。
        deps: 9 组子 deps 聚合；None 子 deps 跳过该组 build（核心工具不可勾选，跳过安全）。
        project_id: #680 装配期项目 ID，透传 build_reader_tools（闭包绑定；默认 None）。

    Returns:
        按 tool_ids 顺序物化的 Tool 列表（未知名防御性忽略）。
    """
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
    by_name = {t.spec.name: t for t in all_tools}
    return [by_name[tid] for tid in tool_ids if tid in by_name]
