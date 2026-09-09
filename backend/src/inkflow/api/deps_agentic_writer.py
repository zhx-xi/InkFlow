"""#1037 agentic writer 装配依赖 — 自 deps.py 迁出（防超 900 行护栏）.

deps.py 以 `from inkflow.api.deps_agentic_writer import get_agentic_writer_service`
re-export，writing.py 与单测仍从 inkflow.api.deps 导入（命名空间不变）。

迁移要点（相对 deps.py 原函数体，行为等价）：
- service getter 与装配类/仓储类经 deps_module（= inkflow.api.deps）命名空间在调用期解析：
  f27 绑定名快照契约——单测 patch 目标是 inkflow.api.deps.<名>
  （test_deps_agentic_model_resolution.py），本模块不得在模块级重新绑定同名符号，
  否则 patch 失效。
- db 默认值用本地 _get_db 惰性代理：deps.get_db 在 deps.py 定义，本模块在 deps.py
  import 阶段被加载，模块级直取会 AttributeError（循环 import 规避）。
- 函数体内 config / resolve_llm_credentials / agentic_writer 装配符号与
  AgenticWriterService 保持函数内 import：patch 目标是源模块（如
  inkflow.infrastructure.agent.agentic_writer），非 deps 命名空间绑定。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

import inkflow.api.deps as deps_module

if TYPE_CHECKING:
    from inkflow.domain.models.agent_run import AgenticWriteRequest
    from inkflow.domain.services.agentic_writer_service import AgenticWriterService


async def _get_db() -> AsyncGenerator[AsyncSession, None]:
    """deps.get_db 惰性代理（规避 deps ↔ 本模块模块级循环 import）。"""
    from inkflow.api.deps import get_db

    async for session in get_db():
        yield session


def get_agentic_writer_service(
    db: AsyncSession = Depends(_get_db),
) -> AgenticWriterService:
    """获取 AgenticWriterService 实例（agentic 编排，装配 F26/F27 工具）。

    F59-M4（B7）：本轨装配期为同步函数、无 project_id → 只按全局档位解析
    （与既有 resolve_llm_credentials(config.llm_default_model) 的「该轨模型也
    只读全局」行为一致）。
    """
    from inkflow.api._llm_resolver import resolve_llm_credentials
    from inkflow.core.config import config
    from inkflow.domain.services.agentic_writer_service import AgenticWriterService
    from inkflow.domain.services.model_resolution import resolve_reasoning_effort
    from inkflow.infrastructure.agent.agentic_writer import (
        AgenticWriterDeps,
        build_agentic_writer,
        build_writer_agent_system_prompt,
    )
    # 循环依赖注意：直接 Python 调用无 FastAPI 依赖缓存——内联构建共享同源实例
    draft_service = deps_module.DraftService(
        draft_repo=deps_module.SQLiteDraftRepository(db),
        chapter_service=deps_module.get_chapter_service(db),
        audit_service=deps_module.AuditLogService(deps_module.SQLiteAuditLogRepository(db)),
        memory_service=deps_module.get_memory_service(db),
    )
    audit_service = deps_module.AuditLogService(deps_module.SQLiteAuditLogRepository(db))
    deps = AgenticWriterDeps(
        character_service=deps_module.get_character_service(db),
        foreshadowing_service=deps_module.get_foreshadowing_service(db),
        summary_service=deps_module.get_summary_service(db),
        chapter_audit_service=deps_module.get_chapter_audit_service(db),
        draft_service=draft_service,
        audit_service=audit_service,
        # #976 D3（2026-09-06 拍板扩展）：agentic 轨按章 id 反查卷（同 chat 语义）
        volume_lookup=deps_module._make_draft_volume_lookup(db),
    )
    prompt_manager = deps_module.LangChainPromptManager()

    def _build_agent(request: AgenticWriteRequest) -> object:
        """每次 run 构建 agent——系统提示与工具期望上下文按请求注入（#275）."""
        system_prompt = build_writer_agent_system_prompt(
            prompt_manager,
            project_id=request.project_id,
            chapter_id=request.chapter_id,
        )
        return build_agentic_writer(
            model=model,
            api_key=api_key,
            base_url=base_url,
            deps=deps,
            system_prompt=system_prompt,
            expected_project_id=request.project_id,
            expected_chapter_id=request.chapter_id,
            reasoning_effort=effort,
        )
    # 模型/密钥/base_url 同源装配（#758 空默认回退首个 chat provider，镜像 #738，防空 key 500）
    model, api_key, base_url = resolve_llm_credentials(config.llm_default_model)
    # F59-M4（B7）：全局思考档位（None 项目级 → 全局兜底；全 None → "default"）
    effort = resolve_reasoning_effort(None, None, config.llm_reasoning_effort)
    return AgenticWriterService(
        agent_factory=_build_agent,
        draft_service=draft_service,
        audit_service=audit_service,
        run_repo=deps_module.SQLiteAgentRunRepository(db),
        chapter_service=deps_module.get_chapter_service(db),
    )
