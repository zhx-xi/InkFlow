"""F27 agentic writer 装配——build_deep_agent 组装 5 只读 + save_draft + writer_agent 模板.

装配层（infrastructure，可 import deepagents/langchain）：
- AgenticWriterDeps: 装配依赖（service 实例注入，鸭子类型，镜像
  ReaderToolDeps/SaveDraftToolDeps）
- build_writer_agent_system_prompt: 渲染 writer_agent.yaml system_prompt
  （模板无变量写死——render 空 dict 原样返回）
- build_agentic_writer: build_reader_tools(5 只读) + build_save_draft_tool
  → build_deep_agent（deepagents ReAct 循环，工具循环在 agent 内建）
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import cast

from inkflow.infrastructure.agent.deepagents.harness import build_deep_agent
from inkflow.infrastructure.agent.tools.reader_tools import ReaderToolDeps, build_reader_tools
from inkflow.infrastructure.agent.tools.save_draft_tool import (
    SaveDraftToolDeps,
    build_save_draft_tool,
)


@dataclass
class AgenticWriterDeps:
    """装配依赖——service 实例注入（鸭子类型，镜像 ReaderToolDeps/SaveDraftToolDeps）."""

    character_service: object
    foreshadowing_service: object
    summary_service: object
    chapter_audit_service: object
    draft_service: object
    audit_service: object


def build_writer_agent_system_prompt(
    prompt_manager,
    *,
    outline: str = "",
    context: str = "",
    min_words: int = 2000,
    style_hint: str = "",
) -> str:
    """渲染 writer_agent.yaml system_prompt（variables 按需，模板未用变量可传空）.

    父侧定稿：模板 system_prompt 写死（无变量）——render 用空 dict 原样返回；
    outline/context/min_words/style_hint 参数预留（后续模板变量化时启用）。
    """
    template = prompt_manager.load("writer_agent")
    rendered = prompt_manager.render(template, {})
    if rendered.messages:
        return str(rendered.messages[0]["content"])
    return str(template.system_prompt)


class DeepAgentInvokeAdapter:
    """deepagents 0.7.5 invoke 形态适配——服务层契约传裸消息列表，
    真实 graph 需要 {"messages": [...]} dict（真实冒烟 2026-08-10 实测
    InvalidUpdateError: Expected dict）；graph.invoke 为同步方法（返回 dict
    非 coroutine，冒烟第二轮实测 TypeError await）。"""

    def __init__(self, inner: object) -> None:
        self._inner = inner

    async def invoke(self, messages: list, config: dict | None = None) -> dict:
        # deepagents 输入 {"messages": [...]}；graph.invoke 同步返回（含 "messages" 键）
        result = self._inner.invoke({"messages": messages}, config=config)  # type: ignore[attr-defined]  # 鸭子类型：deepagents CompiledStateGraph
        if isinstance(result, Awaitable):
            return cast(dict, await result)
        return cast(dict, result)


def build_agentic_writer(
    *,
    model: str,
    api_key: str,
    base_url: str,
    deps: AgenticWriterDeps,
    system_prompt: str,
    profile_key: str | None = None,
):
    """组装 agent：5 只读 + save_draft → build_deep_agent（deepagents ReAct 循环）.

    Args:
        model: LLM 模型标识（registry 前缀剥离在 build_deep_agent 内）.
        api_key: LLM API Key（可空）.
        base_url: OpenAI 兼容 base_url（可空）.
        deps: 装配依赖（5 只读 service + draft/audit service）.
        system_prompt: writer_agent 系统提示（build_writer_agent_system_prompt 产物）.
        profile_key: deepagents HarnessProfile key（None = 按模型名自动确保）.

    Returns:
        DeepAgentInvokeAdapter（包装 deepagents CompiledStateGraph，服务层
        契约裸消息列表 → graph {"messages": [...]} dict 形态）.
    """
    reader_deps = ReaderToolDeps(
        character_service=deps.character_service,
        foreshadowing_service=deps.foreshadowing_service,
        summary_service=deps.summary_service,
        chapter_audit_service=deps.chapter_audit_service,
    )
    tools = build_reader_tools(reader_deps)
    tools.append(
        build_save_draft_tool(
            SaveDraftToolDeps(
                draft_service=deps.draft_service,
                audit_service=deps.audit_service,
            )
        )
    )
    agent = build_deep_agent(
        model=model,
        api_key=api_key,
        base_url=base_url,
        tools=tools,
        system_prompt=system_prompt,
        profile_key=profile_key,
    )
    return DeepAgentInvokeAdapter(agent)
