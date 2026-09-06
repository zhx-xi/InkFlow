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

import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TYPE_CHECKING

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

import inkflow.api.deps as deps_module
from inkflow.infrastructure.agent.pipeline_templates import _CHAT_SYSTEM_AGENT_PROMPT
from inkflow.infrastructure.agent.tools import (
    UnifiedToolDeps,
    build_tools_by_grants,
    resolve_grants,
)
from inkflow.infrastructure.agent.tools.reader_tools import Tool

if TYPE_CHECKING:
    from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService


async def _get_db() -> AsyncGenerator[AsyncSession, None]:
    """deps.get_db 惰性代理（规避 deps ↔ 本模块模块级循环 import）。"""
    from inkflow.api.deps import get_db

    async for session in get_db():
        yield session


def _make_draft_volume_lookup(
    db: AsyncSession,
) -> Callable[[uuid.UUID, uuid.UUID | None], Awaitable[str | None]]:
    """#976 D3：草稿卷解析闭包工厂（chat/agentic 装配轨共享，2026-09-06 拍板扩展）.

    按 chapter_id 反查 ChapterService.get_chapter(chapter_id).volume_id →
    str(uuid.UUID(int=卷行 id))（int↔UUID 惯例，与前端 Volume.id 一致）；
    chapter_id None / 章不存在 / 章无卷 / 任意异常 → None 静默
    （卷解析绝不许崩工具路径）。project_id 保留为签名形状参数（工具调用恒传二参）。
    """
    import uuid

    from inkflow.domain.services.chapter_service import ChapterService

    chapter_svc = ChapterService(db)

    async def _lookup(
        project_id: uuid.UUID, chapter_id: uuid.UUID | None
    ) -> str | None:
        if chapter_id is None:
            return None
        try:
            chapter = await chapter_svc.get_chapter(chapter_id)
            if chapter is None or chapter.volume_id is None:
                return None
            volume_id = chapter.volume_id
            if isinstance(volume_id, int):
                return str(uuid.UUID(int=volume_id))
            return str(volume_id)
        except Exception:
            return None

    return _lookup


async def get_chat_agent_service(
    data: deps_module.ChatStreamRequest,
    db: AsyncSession = Depends(_get_db),
) -> ChatAgentService:
    """获取 ChatAgentService 实例（#597 只读 + #748 设定库写入 + #766 写/删/agent 链）.

    chat_stream.py 顶层导入本函数（绑定名同一性 → dependency_overrides 命中）；
    模型/密钥/base_url 解析镜像 get_agentic_writer_service（provider_config 同源）；
    #680: reader tools 装配期注入 project_id（闭包绑定，LLM 无需自报），并注入
    project_context_getter（context_service 7 源渲染 → 系统提示词增强）；
    #748: 新增 3 个设定库写入工具（create_character/world_setting/outline）+ 注入
    history_getter（ChatMessageService 加载项目历史消息 → 多轮对话有记忆）；
    #766 阶段②: 装配守卫读 conversation.delete_permission——manual 不注入删除工具，
    ask_once/auto 注入（func 内部按授权分支 interrupt 或直接执行）；
    #766 阶段③: 注入 agent_run/agent_call（agent 链执行/调用，D5 不给配置 CRUD）。
    """
    import uuid

    from inkflow.api._llm_resolver import resolve_llm_credentials
    from inkflow.core.config import config
    from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService
    from inkflow.infrastructure.agent.tools.agent_chain_tools import AgentChainToolDeps
    from inkflow.infrastructure.agent.tools.delete_tools import DeleteToolDeps
    from inkflow.infrastructure.agent.tools.memory_tools import MemoryToolDeps
    from inkflow.infrastructure.agent.tools.outline_tools import OutlineToolDeps
    from inkflow.infrastructure.agent.tools.reader_tools import ReaderToolDeps
    from inkflow.infrastructure.agent.tools.save_draft_tool import SaveDraftToolDeps
    from inkflow.infrastructure.agent.tools.setting_update_tools import SettingUpdateToolDeps
    from inkflow.infrastructure.agent.tools.setting_write_tools import SettingWriteToolDeps
    from inkflow.infrastructure.agent.tools.world_readwrite_tools import WorldRwToolDeps
    from inkflow.infrastructure.agent.tools.writing_tools import WritingToolDeps

    # 模型/密钥/base_url 同源装配（#929 §3）：统一走 resolve_llm_credentials——
    # 空默认/named provider 无 key → fail-fast 422 + 诊断日志，绝不遍历注册表
    # 取 models[0]（embedding 误装配为 chat 的缺陷通道，#929 R1/#738 回退废止）。
    model, api_key, base_url = resolve_llm_credentials(config.llm_default_model)

    # #766 阶段② 装配守卫：读 conversation.delete_permission 决定是否挂载删除工具
    # （manual=不注册；ask_once/auto=注册，func 内部按授权分支 interrupt 或直接执行）。
    # conversation_id 缺省（旧客户端/无会话）→ 按 manual 兜底，删除工具不注册。
    conv_svc = deps_module.get_conversation_service(db)
    conv = None
    if data.conversation_id is not None:
        conv = await conv_svc.get(uuid.UUID(data.conversation_id))
    delete_permission = getattr(conv, "delete_permission", "manual") or "manual"

    async def _run_single_agent(agent: object, input_text: str) -> str:
        """单 agent 执行钩子（Q1=A 拍板）：按 agent 配置构建 deep agent 并执行一次，返回输出文本.

        #954 F58 运行时物化：agent 授权统一经 resolve_grants 读取（grants 优先，
        存量 tool_ids-only 行宽松反查）→ build_tools_by_grants 展开（复用外层
        已构造的各子 deps——闭包延迟绑定，调用期均已就绪；delete 子 deps 在
        manual 授权下为 None，build_tools_by_grants 跳过该组）；reader 工具
        绑定当前项目（#680 闭包绑定）。
        """
        from langchain_core.messages import HumanMessage

        unified_deps = UnifiedToolDeps(
            reader=reader_deps,
            save_draft=save_draft_deps,
            setting_write=setting_write_deps,
            setting_update=setting_update_deps,
            outline=outline_deps,
            world_rw=world_rw_deps,
            memory=memory_deps,
            writing=writing_deps,
            delete=delete_deps,
            agent_chain=agent_chain_deps,
        )
        built_agent = deps_module.build_deep_agent(
            model=model,
            api_key=api_key,
            base_url=base_url,
            tools=build_tools_by_grants(
                resolve_grants(agent),
                unified_deps,
                project_id=uuid.UUID(data.project_id),
            ),
            system_prompt=getattr(agent, "system_prompt", "") or "",
            profile_key=None,
        )
        # 鸭子类型：deepagents CompiledStateGraph 提供 ainvoke（Runnable 契约）
        result = await built_agent.ainvoke(
            {"messages": [HumanMessage(content=input_text)]},
            config={"configurable": {"thread_id": str(uuid.uuid4())}},
        )
        history = result.get("messages", []) if isinstance(result, dict) else []
        for message in reversed(history):
            if getattr(message, "type", "") == "ai":
                return getattr(message, "content", "") or ""
        return ""

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
        # #748 agent 聊天历史：项目级读取（跨线程），多轮记忆注入
        items, _total = await cm_svc.list_messages(uuid.UUID(project_id), offset=0, limit=20)
        return list(items)

    reader_deps = ReaderToolDeps(
        character_service=deps_module.get_character_service(db),
        foreshadowing_service=deps_module.get_foreshadowing_service(db),
        summary_service=deps_module.get_summary_service(db),
        chapter_audit_service=deps_module.get_chapter_audit_service(db),
        world_service=deps_module.get_world_service(db),
    )
    reader_tools = deps_module.build_reader_tools(
        reader_deps,
        project_id=uuid.UUID(data.project_id),
    )
    save_draft_deps = SaveDraftToolDeps(
        draft_service=deps_module.get_draft_service(db),
        audit_service=deps_module.get_audit_service(db),
        expected_project_id=uuid.UUID(data.project_id),
        expected_chapter_id=uuid.UUID(data.chapter_id) if data.chapter_id else None,
        # #976 D3（2026-09-06 拍板扩展）：chat 轨草稿同样按章归卷组
        volume_lookup=_make_draft_volume_lookup(db),
    )
    save_draft_tool = deps_module.build_save_draft_tool(save_draft_deps)
    setting_write_deps = SettingWriteToolDeps(
        character_service=deps_module.get_character_service(db),
        world_service=deps_module.get_world_service(db),
        audit_service=deps_module.get_audit_service(db),
        expected_project_id=uuid.UUID(data.project_id),
    )
    setting_write_tools = deps_module.build_setting_write_tools(setting_write_deps)
    setting_update_deps = SettingUpdateToolDeps(
        character_service=deps_module.get_character_service(db),
        world_service=deps_module.get_world_service(db),
        audit_service=deps_module.get_audit_service(db),
        expected_project_id=uuid.UUID(data.project_id),
    )
    setting_update_tools = deps_module.build_setting_update_tools(setting_update_deps)
    outline_deps = OutlineToolDeps(
        outline_service=deps_module.get_outline_service(db),
        chapter_service=deps_module.get_chapter_service(db),
        audit_service=deps_module.get_audit_service(db),
        expected_project_id=uuid.UUID(data.project_id),
    )
    outline_tools = deps_module.build_outline_tools(outline_deps)
    world_rw_deps = WorldRwToolDeps(
        map_service=deps_module.get_map_service(db),
        timeline_service=deps_module.get_timeline_service(db),
        foreshadowing_service=deps_module.get_foreshadowing_service(db),
        audit_service=deps_module.get_audit_service(db),
        expected_project_id=uuid.UUID(data.project_id),
    )
    world_rw_tools = deps_module.build_world_rw_tools(world_rw_deps)
    memory_deps = MemoryToolDeps(
        memory_service=deps_module.get_memory_service(db),
        audit_service=deps_module.get_audit_service(db),
        expected_project_id=uuid.UUID(data.project_id),
    )
    memory_tools = deps_module.build_memory_tools(memory_deps)
    writing_deps = WritingToolDeps(
        writing_service=deps_module.get_writing_service(db),
        audit_service=deps_module.get_audit_service(db),
        expected_project_id=uuid.UUID(data.project_id),
        expected_chapter_id=uuid.UUID(data.chapter_id) if data.chapter_id else None,
    )
    writing_tools = deps_module.build_writing_tools(writing_deps)
    delete_deps: DeleteToolDeps | None = None
    delete_tools: list[Tool] = []
    if delete_permission != "manual":
        from inkflow.domain.models.agent_tools import ToolAuth

        delete_deps = DeleteToolDeps(
            character_service=deps_module.get_character_service(db),
            world_service=deps_module.get_world_service(db),
            outline_service=deps_module.get_outline_service(db),
            map_service=deps_module.get_map_service(db),
            timeline_service=deps_module.get_timeline_service(db),
            foreshadowing_service=deps_module.get_foreshadowing_service(db),
            memory_service=deps_module.get_memory_service(db),
            audit_service=deps_module.get_audit_service(db),
            auth=ToolAuth(delete_permission=delete_permission),
            expected_project_id=uuid.UUID(data.project_id),
        )
        delete_tools = deps_module.build_delete_tools(delete_deps)

    agent_chain_deps = AgentChainToolDeps(
        agent_service=deps_module.get_agent_service(db),
        agent_entity_service=deps_module.get_agent_entity_service(db),
        run_agent=_run_single_agent,
        expected_project_id=uuid.UUID(data.project_id),
    )
    agent_chain_tools = deps_module.build_agent_chain_tools(agent_chain_deps)
    agent = deps_module.build_deep_agent(
        model=model,
        api_key=api_key,
        base_url=base_url,
        tools=[
            *reader_tools,
            save_draft_tool,
            *setting_write_tools,
            *setting_update_tools,
            *outline_tools,
            *world_rw_tools,
            *memory_tools,
            *writing_tools,
            *delete_tools,
            *agent_chain_tools,
        ],
        system_prompt=_CHAT_SYSTEM_AGENT_PROMPT,
        profile_key=None,
    )
    # #821：InMemorySaver 需要 thread_id —— conversation_id 缺失时生成稳定 uuid 兜底
    thread_id = str(data.conversation_id) if data.conversation_id else str(uuid.uuid4())
    return ChatAgentService(
        agent=agent,
        system_prompt=_CHAT_SYSTEM_AGENT_PROMPT,
        project_context_getter=_project_context_getter,
        history_getter=_history_getter,
        thread_id=thread_id,
    )
