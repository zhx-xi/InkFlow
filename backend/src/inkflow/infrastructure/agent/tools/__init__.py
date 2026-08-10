"""Agent 只读工具包 — 静态注册表 + 工具工厂（本包禁止 import deepagents 任何模块）."""

from __future__ import annotations

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.tools.reader_tools import (
    _TOOL_SPECS,
    ReaderToolDeps,
    Tool,
    build_reader_tools,
)
from inkflow.infrastructure.agent.tools.save_draft_tool import (
    SaveDraftParams,
    SaveDraftToolDeps,
    build_save_draft_tool,
)

TOOL_REGISTRY: list[ToolSpec] = _TOOL_SPECS

__all__ = [
    "TOOL_REGISTRY",
    "ReaderToolDeps",
    "SaveDraftParams",
    "SaveDraftToolDeps",
    "Tool",
    "ToolSpec",
    "build_reader_tools",
    "build_save_draft_tool",
]
