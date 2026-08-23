"""#597 chat 系统级 Agent 装配依赖 — 自 deps.py 迁出（防超 900 行护栏）.

deps.py 以 `from inkflow.api.deps_chat_agent import get_chat_agent_service` re-export，
chat_stream.py 与单测仍从 inkflow.api.deps 导入（命名空间不变）。

迁移要点（相对 deps.py 原函数体，行为等价）：
- 工具工厂与各 service getter 经 deps_module（= inkflow.api.deps）命名空间在调用期解析：
  f27 绑定名快照契约——单测 patch 目标是 inkflow.api.deps.<名>（test_chat_agent_stream.py），
  本模块不得在模块级重新绑定同名符号，否则 patch 失效。
- 签名注解 `data: deps_module.ChatStreamRequest`：运行时由 chat_stream.py 在模块级把
  ChatStreamRequest 注册进 deps 全局（FastAPI 依赖签名解析用）；本模块经 deps_module
  间接解析——模块级直 import chat_stream 会成环（chat_stream → deps → 本模块）。
- db 默认值用本地 _get_db 惰性代理：deps.get_db 在 deps.py 定义，本模块在 deps.py
  import 阶段被加载，模块级直取会 AttributeError（循环 import 规避）。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

import inkflow.api.deps as deps_module
from inkflow.infrastructure.agent.pipeline_templates import _CHAT_SYSTEM_AGENT_PROMPT

if TYPE_CHECKING:
    from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService


async def _get_db() -> AsyncGenerator[AsyncSession, None]:
    """deps.get_db 惰性代理（规避 deps ↔ 本模块模块级循环 import）。"""
    from inkflow.api.deps import get_db

    async for session in get_db():
        yield session


def get_chat_agent_service(
    data: deps_module.ChatStreamRequest,
    db: AsyncSession = Depends(_get_db),
) -> ChatAgentService:
    """获取 ChatAgentService 实例（#597 chat 系统级 Agent：全量 5 只读 + save_draft）.

    chat_stream.py 顶层导入本函数（绑定名同一性 → dependency_overrides 命中）；
    模型/密钥/base_url 解析镜像 get_agentic_writer_service（provider_config 同源）。
    """
    import uuid

    from inkflow.core.config import config
    from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService
    from inkflow.infrastructure.agent.tools.reader_tools import ReaderToolDeps
    from inkflow.infrastructure.agent.tools.save_draft_tool import SaveDraftToolDeps
    from inkflow.infrastructure.llm.provider_config import (
        get_provider_config,
        parse_model_string,
    )

    # 模型/密钥/base_url 同源装配（F5 provider_config）：默认模型解析 provider，
    # 未配置 key/base_url 时回退空串（harness 支持空 key/base_url 走 ChatOpenAI 默认）
    model = config.llm_default_model
    api_key = ""
    base_url = ""
    try:
        provider, _ = parse_model_string(model)
        provider_cfg = get_provider_config(provider)
        api_key = provider_cfg.api_key
        base_url = provider_cfg.base_url or ""
    except ValueError:
        pass

    reader_tools = deps_module.build_reader_tools(
        ReaderToolDeps(
            character_service=deps_module.get_character_service(db),
            foreshadowing_service=deps_module.get_foreshadowing_service(db),
            summary_service=deps_module.get_summary_service(db),
            chapter_audit_service=deps_module.get_chapter_audit_service(db),
        )
    )
    save_draft_tool = deps_module.build_save_draft_tool(
        SaveDraftToolDeps(
            draft_service=deps_module.get_draft_service(db),
            audit_service=deps_module.get_audit_service(db),
            expected_project_id=uuid.UUID(data.project_id),
            expected_chapter_id=uuid.UUID(data.chapter_id) if data.chapter_id else None,
        )
    )
    agent = deps_module.build_deep_agent(
        model=model,
        api_key=api_key,
        base_url=base_url,
        tools=[*reader_tools, save_draft_tool],
        system_prompt=_CHAT_SYSTEM_AGENT_PROMPT,
        profile_key=None,
    )
    return ChatAgentService(agent=agent, system_prompt=_CHAT_SYSTEM_AGENT_PROMPT)
