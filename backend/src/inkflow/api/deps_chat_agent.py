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
    """获取 ChatAgentService 实例（#597：5 只读 + save_draft + 3 设定库写入）.

    chat_stream.py 顶层导入本函数（绑定名同一性 → dependency_overrides 命中）；
    模型/密钥/base_url 解析镜像 get_agentic_writer_service（provider_config 同源）；
    #680: reader tools 装配期注入 project_id（闭包绑定，LLM 无需自报），并注入
    project_context_getter（context_service 7 源渲染 → 系统提示词增强）；
    #748: 新增 3 个设定库写入工具（create_character/world_setting/outline）+ 注入
    history_getter（ChatMessageService 加载项目历史消息 → 多轮对话有记忆）。
    """
    import uuid

    from fastapi import HTTPException

    from inkflow.core.config import config
    from inkflow.domain.services.model_resolution import resolve_model
    from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService
    from inkflow.infrastructure.agent.tools.reader_tools import ReaderToolDeps
    from inkflow.infrastructure.agent.tools.save_draft_tool import SaveDraftToolDeps
    from inkflow.infrastructure.agent.tools.setting_write_tools import SettingWriteToolDeps
    from inkflow.infrastructure.llm.provider_config import (
        _BUILTIN_PROVIDERS,
        get_provider_config,
        parse_model_string,
    )

    # 模型/密钥/base_url 同源装配（F5 provider_config）：resolve_model 统一解析链
    # （#735 agent > project > global）；空默认模型时回退到首个有 key 且含 chat 模型的
    # provider（#738，避免空 key 构造 ChatOpenAI → Missing credentials 500）
    model = resolve_model(None, None, config.llm_default_model) or ""
    api_key = ""
    base_url = ""
    if model:
        try:
            provider, _ = parse_model_string(model)
            provider_cfg = get_provider_config(provider)
            api_key = provider_cfg.api_key
            base_url = provider_cfg.base_url or ""
        except ValueError:
            pass
    else:
        for provider in _BUILTIN_PROVIDERS:
            try:
                provider_cfg = get_provider_config(provider)
            except ValueError:
                continue
            fallback_model = provider_cfg.default_model
            if not fallback_model and provider_cfg.models:
                fallback_model = provider_cfg.models[0]
            if fallback_model:
                model = fallback_model
                api_key = provider_cfg.api_key
                base_url = provider_cfg.base_url or ""
                break
        if not api_key:
            raise HTTPException(
                status_code=422,
                detail="未配置默认模型，请在设置中配置 LLM Provider 和默认模型",
            )

    context_svc = deps_module.get_context_service(db)

    async def _project_context_getter(prompt: str, project_id: str) -> str:
        """#680 渲染项目上下文段：context_service.build_context + render_system_prompt."""
        from inkflow.domain.models.context import ContextRequest

        result = await context_svc.build_context(
            ContextRequest(
                project_id=uuid.UUID(project_id),
                # ContextRequest.chapter_id 可选（#680）：data.chapter_id 缺省时传 None，
                # 当前 5 源均忽略 chapter_id（仅按项目注入），无章节 chat 也能注入上下文
                chapter_id=uuid.UUID(data.chapter_id) if data.chapter_id else None,
                model=model,
                writing_requirements=prompt,
            )
        )
        return context_svc.render_system_prompt(result)

    async def _history_getter(project_id: str) -> list:
        """#748 加载项目最近 chat 历史（角色 user/ai 消息 → 多轮记忆注入）。"""
        from inkflow.domain.services.chat_message_service import ChatMessageService
        from inkflow.infrastructure.database.repositories.chat_message_repo import (
            SQLiteChatMessageRepository,
        )

        cm_svc = ChatMessageService(repo=SQLiteChatMessageRepository(db))
        items, _total = await cm_svc.list_messages(uuid.UUID(project_id), offset=0, limit=20)
        return list(items)

    reader_tools = deps_module.build_reader_tools(
        ReaderToolDeps(
            character_service=deps_module.get_character_service(db),
            foreshadowing_service=deps_module.get_foreshadowing_service(db),
            summary_service=deps_module.get_summary_service(db),
            chapter_audit_service=deps_module.get_chapter_audit_service(db),
        ),
        project_id=uuid.UUID(data.project_id),
    )
    save_draft_tool = deps_module.build_save_draft_tool(
        SaveDraftToolDeps(
            draft_service=deps_module.get_draft_service(db),
            audit_service=deps_module.get_audit_service(db),
            expected_project_id=uuid.UUID(data.project_id),
            expected_chapter_id=uuid.UUID(data.chapter_id) if data.chapter_id else None,
        )
    )
    setting_write_tools = deps_module.build_setting_write_tools(
        SettingWriteToolDeps(
            character_service=deps_module.get_character_service(db),
            world_service=deps_module.get_world_service(db),
            outline_service=deps_module.get_outline_service(db),
            audit_service=deps_module.get_audit_service(db),
            expected_project_id=uuid.UUID(data.project_id),
        )
    )
    agent = deps_module.build_deep_agent(
        model=model,
        api_key=api_key,
        base_url=base_url,
        tools=[*reader_tools, save_draft_tool, *setting_write_tools],
        system_prompt=_CHAT_SYSTEM_AGENT_PROMPT,
        profile_key=None,
    )
    return ChatAgentService(
        agent=agent,
        system_prompt=_CHAT_SYSTEM_AGENT_PROMPT,
        project_context_getter=_project_context_getter,
        history_getter=_history_getter,
    )
