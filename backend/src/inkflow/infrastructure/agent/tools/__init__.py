"""Agent 工具包 — 统一目录 + grants 授权面 + 工具工厂（本包禁止 import deepagents 任何模块）.

#838: ALL_TOOL_SPECS/TOOL_REGISTRY/UnifiedToolDeps/build_tools_by_ids 聚合于
registry.py（独立文件，防 __init__ 超 900 行护栏）；#954/#955 F58 grants 授权面
（GRANT_TOOL_MAP/TOOL_NAME_TO_CELL/expand_grants/grants_from_tool_ids/
resolve_grants/build_tools_by_grants + 退役别名 LEGACY_RENAMED_TOOL_NAMES）同源
聚合；outline_tools 工厂（OutlineToolDeps/build_outline_tools）亦在此 re-export；
本文件仅 re-export 保持既有导入路径与包级新消费面。
"""

from __future__ import annotations

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.tools.outline_tools import (
    OutlineToolDeps,
    build_outline_tools,
)
from inkflow.infrastructure.agent.tools.reader_tools import (
    ReaderToolDeps,
    Tool,
    build_reader_tools,
)
from inkflow.infrastructure.agent.tools.registry import (
    ALL_TOOL_SPECS,
    GRANT_TOOL_MAP,
    LEGACY_RENAMED_TOOL_NAMES,
    TOOL_NAME_TO_CELL,
    TOOL_REGISTRY,
    UnifiedToolDeps,
    build_tools_by_grants,
    build_tools_by_ids,
    expand_grants,
    grants_from_tool_ids,
    resolve_grants,
)
from inkflow.infrastructure.agent.tools.save_draft_tool import (
    SAVE_DRAFT_SPEC,
    SaveDraftParams,
    SaveDraftToolDeps,
    build_save_draft_tool,
)

__all__ = [
    "ALL_TOOL_SPECS",
    "GRANT_TOOL_MAP",
    "LEGACY_RENAMED_TOOL_NAMES",
    "SAVE_DRAFT_SPEC",
    "TOOL_NAME_TO_CELL",
    "TOOL_REGISTRY",
    "OutlineToolDeps",
    "ReaderToolDeps",
    "SaveDraftParams",
    "SaveDraftToolDeps",
    "Tool",
    "ToolSpec",
    "UnifiedToolDeps",
    "build_outline_tools",
    "build_reader_tools",
    "build_save_draft_tool",
    "build_tools_by_grants",
    "build_tools_by_ids",
    "expand_grants",
    "grants_from_tool_ids",
    "resolve_grants",
]
