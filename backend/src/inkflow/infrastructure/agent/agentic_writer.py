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
- build_agentic_writer: build_reader_tools(5 只读) + build_save_draft_tool
  → build_deep_agent（deepagents ReAct 循环，工具循环在 agent 内建）
- _append_skills: skill 白名单拼接纯函数（base 前 skill 后，查不到跳过）
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
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
    skill_lookup: Callable[[str], object | None] | None = None
    """skill 查表函数（F39 M3）：按 skill id 取 Skill 鸭子对象（含 name/content），
    None = 未注入（仅 skill_ids 非 None 时读取）。"""


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
    """渲染 writer_agent.yaml system_prompt（#275: 注入当前项目/章节 UUID）.

    变量 dict 恒含 project_id/chapter_id 键（None → 空串）——模板 variables
    声明后 PromptManager.render 的 validate 要求两键必传。
    """
    template = prompt_manager.load("writer_agent")
    rendered = prompt_manager.render(
        template,
        {
            "project_id": str(project_id) if project_id is not None else "",
            "chapter_id": str(chapter_id) if chapter_id is not None else "",
        },
    )
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
    tool_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
    profile_key: str | None = None,
    expected_project_id: uuid.UUID | None = None,
    expected_chapter_id: uuid.UUID | None = None,
):
    """组装 agent：白名单过滤工具 + skill 拼接 → build_deep_agent（deepagents ReAct 循环）.

    Args:
        model: LLM 模型标识（registry 前缀剥离在 build_deep_agent 内）.
        api_key: LLM API Key（可空）.
        base_url: OpenAI 兼容 base_url（可空）.
        deps: 装配依赖（5 只读 service + draft/audit service）.
        system_prompt: writer_agent 系统提示（build_writer_agent_system_prompt 产物）.
        tool_ids: 工具白名单（工具目录 name 列表）；None = 全量 5 只读 +
            save_draft（F27 现行为，向后兼容）；[names] = 只 build 白名单命中项，
            save_draft 仅当白名单含 "save_draft" 时追加.
        skill_ids: skill 白名单（Skill.id 字符串化列表）；None = 不拼 skill
            （F27 现行为）；[ids] = 按白名单顺序把命中 skill content 追加到
            system_prompt 之后（base 前 skill 后，查不到跳过）.
        profile_key: deepagents HarnessProfile key（None = 按模型名自动确保）.
        expected_project_id: #275 期望项目上下文——save_draft 工具防御用
            （每次 run 由装配层注入请求真实值，工具参数不符 → 拒绝）.
        expected_chapter_id: #275 期望章节上下文——save_draft 工具防御用
            （每次 run 由装配层注入请求真实值，工具参数不符 → 拒绝）.

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
    tools = build_reader_tools(reader_deps, include=tool_ids)
    if tool_ids is None or "save_draft" in tool_ids:
        tools.append(
            build_save_draft_tool(
                SaveDraftToolDeps(
                    draft_service=deps.draft_service,
                    audit_service=deps.audit_service,
                    expected_project_id=expected_project_id,
                    expected_chapter_id=expected_chapter_id,
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
    )
    return DeepAgentInvokeAdapter(agent)


def _no_skill_lookup(_skill_id: str) -> object | None:
    """默认 skill 查表函数：装配层未注入时任何 id 均查不到（防御语义）."""
    return None


def _append_skills(
    base_prompt: str,
    skill_ids: list[str],
    skill_lookup: Callable[[str], object | None],
) -> str:
    """把白名单 skill 内容按顺序拼接到 base prompt 之后（spec §5.2）.

    Args:
        base_prompt: 基础 system prompt（恒在前）.
        skill_ids: skill 白名单（Skill.id 字符串化列表，顺序固定）.
        skill_lookup: 按 skill id 取 Skill 鸭子对象（含 name/content）的查表函数；
            查不到该 id → 跳过（防御语义，契约疑点 2）.

    Returns:
        拼接后的完整 system prompt：base + 每个命中 skill 追加
        '\\n\\n# 技能：<name>\\n\\n<content>\\n\\n---\\n'.
    """
    parts = [base_prompt]
    for skill_id in skill_ids:
        skill = skill_lookup(skill_id)
        if skill is None:
            continue
        name = getattr(skill, "name", "")
        content = getattr(skill, "content", "")
        parts.append(f"\n\n# 技能：{name}\n\n{content}\n\n---\n")
    return "".join(parts)
