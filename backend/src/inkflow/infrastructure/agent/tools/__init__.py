"""Agent 工具包 — 统一目录 + 兼容注册表 + 工具工厂（本包禁止 import deepagents 任何模块）.

#838: ALL_TOOL_SPECS/TOOL_REGISTRY/UnifiedToolDeps/build_tools_by_ids 聚合于
registry.py（独立文件，防 __init__ 超 900 行护栏）；本文件仅 re-export 保持
既有导入路径（`from inkflow.infrastructure.agent.tools import TOOL_REGISTRY` 等）。
"""

from __future__ import annotations

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.tools.reader_tools import (
    ReaderToolDeps,
    Tool,
    build_reader_tools,
)
from inkflow.infrastructure.agent.tools.registry import (
    ALL_TOOL_SPECS,
    TOOL_REGISTRY,
    UnifiedToolDeps,
    build_tools_by_ids,
)
from inkflow.infrastructure.agent.tools.save_draft_tool import (
    SAVE_DRAFT_SPEC,
    SaveDraftParams,
    SaveDraftToolDeps,
    build_save_draft_tool,
)

__all__ = [
    "ALL_TOOL_SPECS",
    "SAVE_DRAFT_SPEC",
    "TOOL_REGISTRY",
    "ReaderToolDeps",
    "SaveDraftParams",
    "SaveDraftToolDeps",
    "Tool",
    "ToolSpec",
    "UnifiedToolDeps",
    "build_reader_tools",
    "build_save_draft_tool",
    "build_tools_by_ids",
]
