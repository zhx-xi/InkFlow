"""Agent 工具领域模型 — 领域层工具契约，不泄漏 LangChain/deepagents 类型."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolSpec:
    """工具定义 — 领域层工具契约，不泄漏 LangChain/deepagents 类型."""

    name: str  # 工具名（snake_case）
    description: str  # 工具用途描述
    input_schema: dict  # JSON Schema（Pydantic model_json_schema() 产物）
    group: str = "project"  # 分组键（writing/retrieval/audit/project）


@dataclass
class ToolAuth:
    """删除授权状态——per-conversation，由前端分段控件设置。"""

    delete_permission: str = "manual"  # "manual" | "ask_once" | "auto"
